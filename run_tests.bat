@echo off
rem Rocket Motor Manager - automated tests
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pytest -v
pause
