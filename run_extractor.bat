@echo off
title FlawlessTech Data - Udyam HTML Extractor & CSV Exporter
cd /d "%~dp0"
echo Starting Udyam HTML Extractor...
uv run python client/gui/extractor_gui.py
pause
