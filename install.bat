@echo off
rem ---------------------------------------------------------------------
rem Rocket Motor Manager - installation from source (Windows)
rem Creates a virtual environment in .venv and installs the dependencies.
rem Copyright (c) 2026 Boris du Reau
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set PYTHON=py -3) else (set PYTHON=python)
%PYTHON% --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.10 or later is required: https://www.python.org/downloads/
    pause
    exit /b 1
)
if not exist .venv (
    echo Creating the virtual environment...
    %PYTHON% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements-dev.txt || goto :error
echo.
echo Installation complete. Start the application with run.bat
pause
exit /b 0
:error
echo Installation failed.
pause
exit /b 1
