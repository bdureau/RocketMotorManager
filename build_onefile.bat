@echo off
rem ---------------------------------------------------------------------
rem Rocket Motor Manager - build a single-file Windows executable
rem Output: dist\RocketMotorManager.exe (then checked by tools\check_bundle.py)
rem Copyright (c) 2026 Boris du Reau
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
rem Absolute project path: the generated spec goes to build\onefile (so that
rem RocketMotorManager.spec is never overwritten) and PyInstaller resolves
rem relative paths from the spec folder.
set "R=%~dp0"
if not exist .venv call install.bat
call .venv\Scripts\activate.bat
echo Compiling the translations...
python tools\build_translations.py || goto :error
if not exist documentation\user_manual_en.pdf python tools\generate_manual.py || goto :error
echo Building the single-file executable...
python -m PyInstaller "%R%main.py" --onefile --windowed --noconfirm --clean ^
  --name RocketMotorManager ^
  --specpath build\onefile ^
  --icon="%R%resources\icons\app.ico" ^
  --version-file "%R%version_info.txt" ^
  --add-data "%R%resources\icons;resources/icons" ^
  --add-data "%R%resources\templates;resources/templates" ^
  --add-data "%R%resources\images;resources/images" ^
  --add-data "%R%resources\locale;resources/locale" ^
  --add-data "%R%documentation\user_manual_*.pdf;documentation" ^
  --add-data "%R%documentation\technical_documentation.html;documentation" ^
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
echo Checking the bundled resources...
python tools\check_bundle.py dist\RocketMotorManager.exe || goto :error
echo.
echo Build complete: dist\RocketMotorManager.exe
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1
