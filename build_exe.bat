@echo off
rem ---------------------------------------------------------------------
rem Rocket Motor Manager - build the standalone Windows executable
rem Output: dist\RocketMotorManager\RocketMotorManager.exe
rem Copyright (c) 2026 Boris du Reau
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
if not exist .venv call install.bat
call .venv\Scripts\activate.bat
echo Running the tests...
python -m pytest -q || goto :error
echo Compiling the translations...
python tools\build_translations.py || goto :error
echo Regenerating icons, screenshots and the user manuals (every language)...
python tools\generate_icons.py || goto :error
python tools\capture_screenshots.py --lang all || goto :error
python tools\generate_manual.py || goto :error
echo Building the executable...
python -m PyInstaller --noconfirm --clean RocketMotorManager.spec || goto :error
echo.
echo Build complete: dist\RocketMotorManager\RocketMotorManager.exe
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1
