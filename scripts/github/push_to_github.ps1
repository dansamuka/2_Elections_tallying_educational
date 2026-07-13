[CmdletBinding()]
param(
    [string]$RepositoryName = "",
    [ValidateSet("public", "private")]
    [string]$Visibility = "public",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Write-Step([string]$Text) {
    Write-Host "`n==> $Text" -ForegroundColor Cyan
}

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Add-PathIfExists([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return
    }
    if ((Test-Path $Candidate) -and (($env:Path -split ';') -notcontains $Candidate)) {
        $env:Path = "$env:Path;$Candidate"
    }
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if (-not [string]::IsNullOrWhiteSpace($machinePath)) { $parts += $machinePath }
    if (-not [string]::IsNullOrWhiteSpace($userPath)) { $parts += $userPath }
    if ($parts.Count -gt 0) {
        $env:Path = $parts -join ";"
    }

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    Add-PathIfExists (Join-Path $programFiles "Git\cmd")
    Add-PathIfExists (Join-Path $programFiles "GitHub CLI")
}

function Install-WithWinget([string]$Id, [string]$Label) {
    if (-not (Test-Command "winget")) {
        throw "$Label is required, and winget is unavailable. Install $Label, then run PUSH_TO_GITHUB.cmd again."
    }

    $answer = Read-Host "$Label is not installed. Install it now with winget? [Y/n]"
    if ($answer -and $answer.ToLowerInvariant().StartsWith("n")) {
        throw "$Label is required."
    }

    & winget install --id $Id --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "$Label installation failed with exit code $LASTEXITCODE."
    }
    Refresh-ProcessPath
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

Write-Host "Kenya Election Tallying Wall - one-click GitHub publisher" -ForegroundColor Green
Write-Host "This script validates the repository, creates or updates a GitHub repository, pushes main, and enables GitHub Pages."

Refresh-ProcessPath

if (-not (Test-Command "git")) {
    Install-WithWinget "Git.Git" "Git"
}
if (-not (Test-Command "gh")) {
    Install-WithWinget "GitHub.cli" "GitHub CLI"
}
if (-not (Test-Command "git")) {
    throw "Git was installed but is not visible yet. Close this window and run PUSH_TO_GITHUB.cmd again."
}
if (-not (Test-Command "gh")) {
    throw "GitHub CLI was installed but is not visible yet. Close this window and run PUSH_TO_GITHUB.cmd again."
}

Write-Step "Checking GitHub authentication"
& gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "A browser window will open for secure GitHub sign-in." -ForegroundColor Yellow
    & gh auth login --hostname github.com --git-protocol https --web
    Assert-LastExitCode "GitHub authentication was not completed."
}

$Owner = ((& gh api user --jq .login) | Out-String).Trim()
Assert-LastExitCode "Could not read the authenticated GitHub account."
if (-not $Owner) {
    throw "Could not determine the authenticated GitHub username."
}

if (-not $RepositoryName) {
    $defaultName = "kenya-election-tallying-wall"
    $typed = Read-Host "Repository name [$defaultName]"
    if ([string]::IsNullOrWhiteSpace($typed)) {
        $RepositoryName = $defaultName
    } else {
        $RepositoryName = $typed.Trim()
    }
}
if ($RepositoryName -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Repository name may contain only letters, numbers, dots, underscores, and hyphens."
}

if (-not $SkipTests) {
    Write-Step "Preparing and testing the repository"
    if (Test-Path ".venv\Scripts\python.exe") {
        $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
    } elseif (Test-Command "py") {
        & py -3 -m venv .venv
        Assert-LastExitCode "Could not create the Python virtual environment."
        $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
    } elseif (Test-Command "python") {
        & python -m venv .venv
        Assert-LastExitCode "Could not create the Python virtual environment."
        $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
    } else {
        throw "Python 3.11 or newer is required to run the validation suite."
    }

    & $Python -m pip install --upgrade pip
    Assert-LastExitCode "Could not upgrade pip."
    & $Python -m pip install -e ".[dev,pdf]"
    Assert-LastExitCode "Could not install the project dependencies."
    & $Python -m pytest
    Assert-LastExitCode "Tests failed; the repository was not pushed."
    & $Python -m olkalou_engine.cli --root . publish --simulations 100
    Assert-LastExitCode "Could not generate the live site payload."
    & $Python -m olkalou_engine.cli --root . archive-build banissa-2025
    Assert-LastExitCode "Could not generate the Banissa archive payload."
}

Write-Step "Preparing the Git commit"
if (-not (Test-Path ".git")) {
    & git init
    Assert-LastExitCode "Could not initialize the local Git repository."
}
& git branch -M main
Assert-LastExitCode "Could not set the local branch to main."

$userName = ((& git config user.name 2>$null) | Out-String).Trim()
if (-not $userName) {
    $typedName = Read-Host "Git author name [$Owner]"
    if ([string]::IsNullOrWhiteSpace($typedName)) {
        $userName = $Owner
    } else {
        $userName = $typedName.Trim()
    }
    & git config user.name $userName
    Assert-LastExitCode "Could not configure the Git author name."
}

$userEmail = ((& git config user.email 2>$null) | Out-String).Trim()
if (-not $userEmail) {
    $defaultEmail = "$Owner@users.noreply.github.com"
    $typedEmail = Read-Host "Git author email [$defaultEmail]"
    if ([string]::IsNullOrWhiteSpace($typedEmail)) {
        $userEmail = $defaultEmail
    } else {
        $userEmail = $typedEmail.Trim()
    }
    & git config user.email $userEmail
    Assert-LastExitCode "Could not configure the Git author email."
}

& git add --all
Assert-LastExitCode "Could not stage the repository files."
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & git commit -m "Build provenance-first election tallying wall and historical replay module"
    Assert-LastExitCode "Could not create the Git commit."
} else {
    Write-Host "No new file changes to commit." -ForegroundColor DarkGray
}

$FullRepo = "$Owner/$RepositoryName"
$remoteUrl = "https://github.com/$FullRepo.git"
Write-Step "Creating or connecting $FullRepo"
& gh repo view $FullRepo --json name 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    & git remote get-url origin 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        & git remote remove origin
        Assert-LastExitCode "Could not remove the old origin remote."
    }

    if ($Visibility -eq "private") {
        & gh repo create $FullRepo --private --description "Provenance-first Kenyan election tallying wall with historical by-election archive and replay tooling" --source . --remote origin
    } else {
        & gh repo create $FullRepo --public --description "Provenance-first Kenyan election tallying wall with historical by-election archive and replay tooling" --source . --remote origin
    }
    Assert-LastExitCode "GitHub repository creation failed."
} else {
    & git remote get-url origin 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        & git remote set-url origin $remoteUrl
    } else {
        & git remote add origin $remoteUrl
    }
    Assert-LastExitCode "Could not connect the local repository to GitHub."
}

Write-Step "Pushing main"
& git push --set-upstream origin main
Assert-LastExitCode "Git push failed. Confirm that the GitHub repository is empty and that your account has permission to push to it."

Write-Step "Enabling GitHub Pages workflow deployment"
$pagesBody = '{"build_type":"workflow"}'
$pagesTemp = Join-Path $env:TEMP "election-pages-$PID.json"
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($pagesTemp, $pagesBody, $utf8WithoutBom)
try {
    & gh api --method POST -H "Accept: application/vnd.github+json" "repos/$FullRepo/pages" --input $pagesTemp 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        & gh api --method PUT -H "Accept: application/vnd.github+json" "repos/$FullRepo/pages" --input $pagesTemp 1>$null 2>$null
    }
} finally {
    Remove-Item $pagesTemp -ErrorAction SilentlyContinue
}

$RepoUrl = "https://github.com/$FullRepo"
$PagesUrl = "https://$($Owner.ToLowerInvariant()).github.io/$RepositoryName/"
Write-Host "`nRepository: $RepoUrl" -ForegroundColor Green
Write-Host "Expected Pages URL after the workflow completes: $PagesUrl" -ForegroundColor Green
Write-Host "GitHub Actions: $RepoUrl/actions" -ForegroundColor Green

$open = Read-Host "Open the repository in your browser now? [Y/n]"
if (-not $open -or -not $open.ToLowerInvariant().StartsWith("n")) {
    Start-Process $RepoUrl
}
