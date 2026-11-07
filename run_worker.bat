@echo off
title Udayam Fleet Worker
cd /d "%~dp0"
echo Starting Udayam Fleet Worker...
uv run python client/app.py
pause
