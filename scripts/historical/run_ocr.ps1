[CmdletBinding()]
param(
    [string]$ElectionId = "banissa-2025",
    [ValidateSet("auto", "embedded", "tesseract", "gcv", "textract", "dual-cloud")]
    [string]$Engine = "auto",
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Assert-Exit([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $tesseract = Join-Path $programFiles "Tesseract-OCR"
    if ((Test-Path $tesseract) -and (($env:Path -split ';') -notcontains $tesseract)) {
        $env:Path = "$env:Path;$tesseract"
    }
}

Write-Host "Historical election OCR and same-repository updater" -ForegroundColor Green
Write-Host "Election: $ElectionId"
Write-Host "OCR engine: $Engine"

if (Test-Path ".venv\Scripts\python.exe") {
    $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m venv .venv
    Assert-Exit "Could not create the Python virtual environment."
    $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m venv .venv
    Assert-Exit "Could not create the Python virtual environment."
    $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
    throw "Python 3.11 or newer is required."
}

& $Python -m pip install --upgrade pip
Assert-Exit "Could not upgrade pip."
& $Python -m pip install -e ".[dev,pdf,historical-ocr]"
Assert-Exit "Could not install the historical OCR dependencies."

Refresh-Path
if (($Engine -eq "auto" -or $Engine -eq "tesseract") -and -not (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "Tesseract is not installed. Install it with winget now? [Y/n]"
        if (-not $answer -or -not $answer.ToLowerInvariant().StartsWith("n")) {
            & winget install --id UB-Mannheim.TesseractOCR --exact --accept-package-agreements --accept-source-agreements
            Assert-Exit "Tesseract installation failed."
            Refresh-Path
        }
    } else {
        Write-Warning "Tesseract is unavailable. Embedded PDF text will still be processed; scanned pages will remain quarantined."
    }
}

& $Python -m olkalou_engine.cli --root . ocr-doctor
& $Python -m pytest
Assert-Exit "Tests failed. OCR output was not pushed."

$argsList = @("-m", "olkalou_engine.cli", "--root", ".", "archive-ocr", $ElectionId, "--engine", $Engine)
if ($Rebuild) { $argsList += "--rebuild" }
& $Python @argsList
Assert-Exit "Historical OCR failed."
& $Python -m olkalou_engine.cli --root . archive-build $ElectionId
Assert-Exit "Could not rebuild the historical website payload."

Write-Host "`nOCR review queue:" -ForegroundColor Cyan
Write-Host "data\elections\$ElectionId\ocr\review_queue.csv"
Write-Host "No OCR value has been published. Two-person review is still required."

$push = Read-Host "Push these updated files to dansamuka/2_Elections_tallying_educational now? [Y/n]"
if (-not $push -or -not $push.ToLowerInvariant().StartsWith("n")) {
    & (Join-Path $RepoRoot "scripts\github\push_to_github.ps1") -RepositoryName "2_Elections_tallying_educational" -SkipTests
    Assert-Exit "GitHub update failed."
}
