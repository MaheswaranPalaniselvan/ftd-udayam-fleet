# FlawlessTech Data - Machine Setup & Environment Initializer (PowerShell)
[CmdletBinding()]
param()

$Host.UI.RawUI.WindowTitle = "FlawlessTech Data - Machine Setup"
$ErrorActionPreference = "Stop"

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "   FlawlessTech Data - Udayam Extractor Automated Machine Setup     " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 1. Verify or install uv
Write-Host "[1/4] Checking system prerequisites..." -ForegroundColor Yellow
$uvCmd = Get-Command "uv" -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    $uvLocalPath = "$env:USERPROFILE\.local\bin\uv.exe"
    if (Test-Path $uvLocalPath) {
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    } else {
        Write-Host "  -> 'uv' not found. Installing standalone package manager..." -ForegroundColor Gray
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    }
}
Write-Host "  -> [OK] uv package manager ready." -ForegroundColor Green
Write-Host ""

# 2. Synchronize virtual environment
Write-Host "[2/4] Setting up isolated Python environment and installing dependencies..." -ForegroundColor Yellow
try {
    & uv sync
    Write-Host "  -> [OK] Dependencies synchronized successfully." -ForegroundColor Green
} catch {
    Write-Host "  -> Fallback: installing required packages directly..." -ForegroundColor Gray
    & uv pip install ddddocr fastapi httpx openpyxl playwright "scrapling[all]" uvicorn pyinstaller
}
Write-Host ""

# 3. Install Playwright browser binaries
Write-Host "[3/4] Installing browser automation binaries (Chromium)..." -ForegroundColor Yellow
try {
    & uv run playwright install chromium
    Write-Host "  -> [OK] Playwright browser installed." -ForegroundColor Green
} catch {
    Write-Host "  -> [WARN] Playwright browser install had warnings." -ForegroundColor DarkYellow
}
Write-Host ""

# 4. Create Desktop Shortcut
Write-Host "[4/4] Creating Desktop Shortcut..." -ForegroundColor Yellow
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $DesktopPath = [Environment]::GetFolderPath('Desktop')
    $ShortcutPath = Join-Path $DesktopPath "Udayam Extractor.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = (Join-Path $ScriptDir "run_extractor.bat")
    $Shortcut.WorkingDirectory = $ScriptDir
    $Shortcut.Description = "FlawlessTech Data - Udayam HTML Extractor & Coverage Dashboard"
    $Shortcut.Save()
    Write-Host "  -> [OK] Desktop shortcut created: $ShortcutPath" -ForegroundColor Green
} catch {
    Write-Host "  -> [WARN] Could not create desktop shortcut: $_" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " [SUCCESS] SETUP COMPLETE! This machine is now ready for extraction. " -ForegroundColor Green
Write-Host ""
Write-Host " You can launch the application via: "
Write-Host "   1. Desktop Shortcut: 'Udayam Extractor' " -ForegroundColor White
Write-Host "   2. Double-clicking: run_extractor.bat " -ForegroundColor White
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host ""
Read-Host -Prompt "Press Enter to exit"
