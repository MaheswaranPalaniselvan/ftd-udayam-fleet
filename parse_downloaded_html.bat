@echo off
setlocal
cd /d "%~dp0"

echo =========================================================
echo FlawlessTech Data - Extract Directly from Downloaded HTML
echo =========================================================
echo.

set INPUT_FILE=%~1
if "%INPUT_FILE%"=="" set INPUT_FILE=numbers.txt

set OUTPUT_FILE=%~2
if "%OUTPUT_FILE%"=="" set OUTPUT_FILE=results.xlsx

set HTML_DIR=%~3
if "%HTML_DIR%"=="" set HTML_DIR=downloaded_html

echo Input List:      %INPUT_FILE%
echo HTML Directory:  %HTML_DIR%
echo Output File:     %OUTPUT_FILE%
echo.

uv run python extract_list.py --parse-only --html-dir "%HTML_DIR%" --input "%INPUT_FILE%" --output "%OUTPUT_FILE%"

echo.
pause
