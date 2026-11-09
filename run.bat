@echo off
rem Rocket Motor Manager - launcher (source version)
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo The application is not installed yet. Running install.bat...
    call install.bat || exit /b 1
)
start "" .venv\Scripts\pythonw.exe main.py %*
