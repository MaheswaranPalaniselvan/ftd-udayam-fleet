@echo off
setlocal enabledelayedexpansion
title FlawlessTech Data - Machine Setup & Environment Initializer

echo =====================================================================
echo    FlawlessTech Data - Udayam Extractor Automated Machine Setup
echo =====================================================================
echo.
echo [1/4] Checking system prerequisites and environment...

cd /d "%~dp0"

:: 1. Check if uv is installed
where uv >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] 'uv' package manager not detected on this machine.
    echo [INFO] Downloading and installing standalone uv package manager...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    
    :: Add local bin to current session PATH
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%LOCALAPPDATA%\bin;!PATH!"
    
    where uv >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to automatically install uv.
        echo Please install Python 3.12+ or uv manually from https://docs.astral.sh/uv/
        pause
        exit /b 1
    )
)

echo [OK] Package manager (uv) verified.
echo.

:: 2. Synchronize virtual environment & install all dependencies
echo [2/4] Setting up isolated Python environment and installing dependencies...
echo       (playwright, scrapling, ddddocr, openpyxl, httpx, fastapi)...
uv sync
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] 'uv sync' encountered an issue, trying direct package installation...
    uv pip install ddddocr fastapi httpx openpyxl playwright "scrapling[all]" uvicorn pyinstaller
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Dependency installation failed. Please check internet connection.
        pause
        exit /b 1
    )
)

echo [OK] All Python dependencies installed successfully.
echo.

:: 3. Install Playwright browser automation binaries
echo [3/4] Installing browser automation binaries (Chromium)...
uv run playwright install chromium
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Playwright browser install had warnings. Continuing...
) else (
    echo [OK] Chromium browser automation binaries installed.
)
echo.

:: 4. Create Desktop Shortcut for easy one-click launching
echo [4/4] Creating Desktop Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$WshShell = New-Object -ComObject WScript.Shell; " ^
    "$DesktopPath = [Environment]::GetFolderPath('Desktop'); " ^
    "$Shortcut = $WshShell.CreateShortcut(\"$DesktopPath\Udayam Extractor.lnk\"); " ^
    "$Shortcut.TargetPath = (Resolve-Path '.\run_extractor.bat').Path; " ^
    "$Shortcut.WorkingDirectory = (Resolve-Path '.').Path; " ^
    "$Shortcut.Description = 'FlawlessTech Data - Udayam HTML Extractor & Coverage Dashboard'; " ^
    "$Shortcut.Save(); " ^
    "Write-Host '[OK] Desktop shortcut created: ' $DesktopPath'\Udayam Extractor.lnk'"

echo.
echo =====================================================================
echo [SUCCESS] SETUP COMPLETE! This machine is now ready for extraction.
echo.
echo You can now run the tool using:
echo   1. Double-click the 'Udayam Extractor' icon on your Desktop
echo   2. Or run: run_extractor.bat
echo =====================================================================
echo.
pause
