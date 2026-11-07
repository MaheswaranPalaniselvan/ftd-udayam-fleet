@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo FlawlessTech Data - Enterprise XLSX to HTML Converter
echo ========================================================
echo.

set INPUT_FILE=%~1
if "%INPUT_FILE%"=="" set INPUT_FILE=results.xlsx

set OUTPUT_FILE=%~2
if "%OUTPUT_FILE%"=="" (
    for %%F in ("%INPUT_FILE%") do set OUTPUT_FILE=%%~dpnF.html
)

echo Input Excel File:   %INPUT_FILE%
echo Output HTML Viewer: %OUTPUT_FILE%
echo.

uv run python xlsx_to_html.py --input "%INPUT_FILE%" --output "%OUTPUT_FILE%" --open

echo.
pause
