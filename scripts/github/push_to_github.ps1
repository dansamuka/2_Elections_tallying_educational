[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$FullRepo = "dansamuka/2_Elections_tallying_educational"
$RepositoryName = "2_Elections_tallying_educational"
$RemoteUrl = "https://github.com/$FullRepo.git"
Set-Location $RepoRoot

function Write-Step([string]$Text) {
    Write-Host "`n==> $Text" -ForegroundColor Cyan
}

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Add-PathIfExists([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return }
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
    if ($parts.Count -gt 0) { $env:Path = $parts -join ";" }

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    Add-PathIfExists (Join-Path $programFiles "Git\cmd")
    Add-PathIfExists (Join-Path $programFiles "GitHub CLI")
    Add-PathIfExists (Join-Path $programFiles "Tesseract-OCR")
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
    if ($LASTEXITCODE -ne 0) { throw "$Label installation failed with exit code $LASTEXITCODE." }
    Refresh-ProcessPath
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

Write-Host "Kenya Election Tallying Wall - existing repository updater" -ForegroundColor Green
Write-Host "Target repository: $FullRepo"
Write-Host "This updater only replaces changed files in that existing repository. It will never create a new repository."

Refresh-ProcessPath
if (-not (Test-Command "git")) { Install-WithWinget "Git.Git" "Git" }
if (-not (Test-Command "gh")) { Install-WithWinget "GitHub.cli" "GitHub CLI" }
if (-not (Test-Command "git")) { throw "Git is not visible. Close this window and run again." }
if (-not (Test-Command "gh")) { throw "GitHub CLI is not visible. Close this window and run again." }

Write-Step "Checking GitHub authentication"
& gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "A browser window will open for secure GitHub sign-in." -ForegroundColor Yellow
    & gh auth login --hostname github.com --git-protocol https --web
    Assert-LastExitCode "GitHub authentication was not completed."
}

$Owner = ((& gh api user --jq .login) | Out-String).Trim()
Assert-LastExitCode "Could not read the authenticated GitHub account."
if (-not $Owner) { throw "Could not determine the authenticated GitHub username." }
& gh repo view $FullRepo --json name 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "The existing target repository $FullRepo is not accessible. This updater will not create a replacement repository."
}
$RepoExists = $true

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
    & $Python -m pip install -e ".[dev,pdf,historical-ocr]"
    Assert-LastExitCode "Could not install the project dependencies."
    & $Python -c "from datetime import datetime; from olkalou_engine.worker import EAT; assert EAT.utcoffset(datetime.now()).total_seconds() == 10800"
    Assert-LastExitCode "East Africa Time support could not be initialized. Delete .venv and run this script again."
    & $Python -m pytest
    Assert-LastExitCode "Tests failed; the repository was not pushed."
    & $Python -m olkalou_engine.cli --root . publish --simulations 100
    Assert-LastExitCode "Could not generate the live site payload."
    & $Python -m olkalou_engine.cli --root . archive-build banissa-2025
    Assert-LastExitCode "Could not generate the Banissa archive payload."
}

Write-Step "Synchronizing the existing repository history"
if (-not (Test-Path ".git")) {
    & git init
    Assert-LastExitCode "Could not initialize the local Git repository."
}
& git branch -M main
Assert-LastExitCode "Could not set the local branch to main."

& git remote get-url origin 1>$null 2>$null
if ($LASTEXITCODE -eq 0) {
    & git remote set-url origin $RemoteUrl
} else {
    & git remote add origin $RemoteUrl
}
Assert-LastExitCode "Could not connect the local repository to GitHub."

if ($RepoExists) {
    & git fetch origin main
    Assert-LastExitCode "Could not fetch the existing main branch. Check network access and repository permissions."
    # Align the commit parent with the remote while preserving this folder as the desired project snapshot.
    & git reset --mixed origin/main
    Assert-LastExitCode "Could not align the local update with origin/main."
}

$userName = ((& git config user.name 2>$null) | Out-String).Trim()
if (-not $userName) {
    & git config user.name $Owner
    Assert-LastExitCode "Could not configure the Git author name."
}
$userEmail = ((& git config user.email 2>$null) | Out-String).Trim()
if (-not $userEmail) {
    & git config user.email "$Owner@users.noreply.github.com"
    Assert-LastExitCode "Could not configure the Git author email."
}

Write-Step "Committing the replacement snapshot"
& git add --all
Assert-LastExitCode "Could not stage the repository files."
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & git commit -m "Add five-minute IEBC forms sync and OCR dashboard updates"
    Assert-LastExitCode "Could not create the Git commit."
} else {
    Write-Host "No changed files were found. The existing repository is already current." -ForegroundColor DarkGray
}


Write-Step "Pushing replacement files to main"
& git push --set-upstream origin main
Assert-LastExitCode "Git push failed. Check repository permissions and branch protection."

Write-Step "Ensuring GitHub Pages workflow deployment is enabled"
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
$PagesUrl = "https://dansamuka.github.io/$RepositoryName/"
Write-Host "`nRepository updated: $RepoUrl" -ForegroundColor Green
Write-Host "Pages URL: $PagesUrl" -ForegroundColor Green
Write-Host "GitHub Actions: $RepoUrl/actions" -ForegroundColor Green

$open = Read-Host "Open the repository in your browser now? [Y/n]"
if (-not $open -or -not $open.ToLowerInvariant().StartsWith("n")) {
    Start-Process $RepoUrl
}
