@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo FlawlessTech Data - Udyam Custom List CLI Extractor
echo ===================================================

if "%~1"=="" (
    echo Usage: run_cli_extractor.bat numbers.txt [output.xlsx] [concurrency]
    echo Or run directly: uv run python extract_list.py --help
    echo.
    set /p INPUT_FILE="Enter path to file with Udyam numbers: "
) else (
    set INPUT_FILE=%~1
)

set OUTPUT_FILE=%~2
if "%OUTPUT_FILE%"=="" set OUTPUT_FILE=results.xlsx

set CONCURRENCY=%~3
if "%CONCURRENCY%"=="" set CONCURRENCY=2

uv run python extract_list.py --input "%INPUT_FILE%" --output "%OUTPUT_FILE%" --concurrency %CONCURRENCY%
pause
