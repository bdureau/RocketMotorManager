@echo off
rem ---------------------------------------------------------------------
rem Rocket Motor Manager - single-file executable with EXTERNAL resources
rem Output folder: dist\RocketMotorManager_onefile\
rem     RocketMotorManager.exe        (code only, no data files inside)
rem     resources\icons, templates, images, locale (*.mo)
rem     documentation\user_manual_<lang>.pdf, technical_documentation.html
rem Deliver the whole folder: the application reads its resources next to
rem the .exe (application\paths.py), so they can be updated without
rem rebuilding (new manual, corrected translation, new label template...).
rem Copyright (c) 2026 Boris du Reau
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "R=%~dp0"
set "OUT=%R%dist\RocketMotorManager_onefile"
if not exist .venv call install.bat
call .venv\Scripts\activate.bat
echo Compiling the translations...
python tools\build_translations.py || goto :error
if not exist documentation\user_manual_en.pdf python tools\generate_manual.py || goto :error
echo Building the single-file executable (without data files)...
python -m PyInstaller "%R%main.py" --onefile --windowed --noconfirm --clean ^
  --name RocketMotorManager ^
  --distpath "%OUT%" ^
  --specpath build\onefile_external ^
  --workpath build\onefile_external ^
  --icon="%R%resources\icons\app.ico" ^
  --version-file "%R%version_info.txt" ^
  --hidden-import openpyxl ^
  --hidden-import xlrd ^
  --hidden-import matplotlib.backends.backend_qtagg ^
  --hidden-import matplotlib.backends.backend_pdf ^
  --hidden-import matplotlib.backends.backend_svg ^
  --hidden-import scipy.signal ^
  --hidden-import PyQt6.QtSvg ^
  --hidden-import PyQt6.QtPrintSupport ^
  --exclude-module tkinter ^
  --exclude-module pytest ^
  --exclude-module PyQt5 ^
  --exclude-module PySide6 || goto :error
echo Copying the resources and the documentation beside the executable...
call :copy resources\icons "%OUT%\resources\icons" * || goto :error
call :copy resources\templates "%OUT%\resources\templates" * || goto :error
call :copy resources\images "%OUT%\resources\images" * || goto :error
call :copy resources\locale "%OUT%\resources\locale" *.mo || goto :error
call :copy documentation "%OUT%\documentation" user_manual_*.pdf technical_documentation.html || goto :error
echo Checking the resources...
python tools\check_bundle.py "%OUT%\RocketMotorManager.exe" || goto :error
echo.
echo Build complete: %OUT%
echo Deliver the whole folder (RocketMotorManager.exe + resources + documentation).
pause
exit /b 0

:copy
rem robocopy source destination patterns... (/S = sub-folders; exit codes 0-7 mean success)
set "SRC=%~1"
set "DST=%~2"
shift
shift
set "PATTERNS="
:patterns
if "%~1"=="" goto :do_copy
set "PATTERNS=%PATTERNS% %1"
shift
goto :patterns
:do_copy
robocopy "%SRC%" "%DST%" %PATTERNS% /S /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
exit /b 0

:error
echo Build failed.
pause
exit /b 1
