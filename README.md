# Rocket Motor Manager

Desktop application (Python 3 / PyQt6) to create, import, edit, convert, analyse,
visualise and archive rocket motor thrust data, fully compatible with the RASP
**.eng** format used by OpenRocket and RockSim.

Author: **Boris du Reau** — © 2026 Boris du Reau. All rights reserved.

## Features

| Area | What it does |
|------|--------------|
| Motor editor | Name, manufacturer, designation, delays, diameter, length, propellant / casing / nozzle masses (total mass computed), propellant type, description, comments |
| Thrust curve | Matplotlib graph: zoom, pan, reset, cursor read-out and interpolated thrust, grid, auto axes, PNG/SVG/PDF export, drag points, double-click to add, right-click to delete |
| Data table | Edit cells, add, duplicate, delete (multi-selection), sort, copy/paste from Excel, invalid rows highlighted, synchronised with the graph, unlimited undo/redo |
| Import | ENG (multi-motor files, comments, precise line errors), CSV (separator / decimal / encoding detection, column mapping, units, preview, invalid rows), Excel .xlsx/.xls (sheet choice, preview) |
| SRM workbooks | Richard Nakka SRM 1.x / SRM 2023 (.xls/.xlsx): motor data read from the *Data and Kn*, *Output*, *Performance*, *Pressure* and *Nozzle Design* sheets, choice of curve (Performance simplified / full / resampled, Output table), cross-check with the workbook results, auto-detection on Excel import |
| Digitizer | Photos/scans/screenshots (PNG, JPG, TIFF, BMP): rotation, crop, perspective, contrast, grey levels, noise filters; 3-point + extra-point least-squares calibration; colour auto-detection / pipette, tolerance, outlier removal, manual point editing, Matplotlib preview, transfer to the editor |
| Analysis | Total impulse (trapezoids), max/average thrust, burn time (full curve or NAR 5 %), initial/final thrust, time to max, masses, propellant fraction, Isp, impulse class, suggested designation; unavailable values explained |
| Export | Strict, validated ENG writer; CSV with separator/decimal/encoding/units/metadata options |
| Project | Versioned native XML (`.rmm.xml`) with migrations, structural validation, exact float round-trip, atomic saves |
| Labels | Independent designer: dimensions, paper, margins, colours, fonts, alignment, borders, layouts, field selection and order, free text, logo; 6 predefined templates + user templates; print preview, printing, PDF sheet, PNG/JPEG at any dpi, physical size respected |
| Quality | Centralised error handling, rotating log (DEBUG→ERROR), background threads for heavy image work, preferences (theme, units, colours, folders, printing, language), interface and PDF manual in 9 languages (gettext .po), tooltips everywhere, 180 automated tests |

## Quick start (Windows)

```bat
install.bat      :: creates .venv and installs dependencies
run.bat          :: starts the application
run_tests.bat    :: runs the automated tests
build_exe.bat    :: builds dist\RocketMotorManager\RocketMotorManager.exe (one folder)
build_onefile.bat :: builds dist\RocketMotorManager.exe (single file, resources inside)
build_onefile_external.bat :: single-file exe + resources/documentation folders beside it
```

Manual start on any OS:

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python main.py [file.rmm.xml | file.eng | file.csv | image.png]
python -m pytest
```

## Project structure

```
RocketMotorManager/
├── main.py                       entry point
├── localization/                 gettext: _(), ngettext(), N_(), language installation
├── application/                  bootstrap, controller, configuration, logging, errors, workers
│   ├── app.py                    QApplication + main window creation
│   ├── application_controller.py MotorDocument (state, undo stack) + ApplicationController
│   ├── configuration.py          JSON preferences, recent files
│   ├── error_handler.py          global exception hook + ErrorReporter
│   ├── logging_setup.py          rotating log file in %LOCALAPPDATA%
│   ├── paths.py                  user folders and bundled resources (PyInstaller aware)
│   ├── translator.py             Qt base translations (standard dialogs)
│   ├── version.py                name, version, copyright
│   └── workers.py                QThreadPool background tasks
├── models/                       business model (no Qt)
│   ├── motor.py                  Motor aggregate + PlotSettings
│   ├── thrust_point.py           ThrustPoint
│   ├── motor_metadata.py         MotorMetadata (total mass logic)
│   ├── motor_calculations.py     all physics (impulse, burn time, Isp, class...)
│   ├── units.py                  unit registry and conversions
│   ├── validation.py             ValidationReport rules
│   ├── label_template.py         label template data
│   └── errors.py                 exception hierarchy
├── services/                     file formats and processing
│   ├── eng_service.py            RASP .eng reader/writer
│   ├── csv_service.py            CSV detection, import, export
│   ├── excel_service.py          .xlsx (openpyxl) / .xls (xlrd) via pandas
│   ├── tabular_data.py           shared column mapping / conversion
│   ├── srm_service.py            Richard Nakka SRM workbook importer
│   ├── xml_service.py            native project format + migrations
│   ├── thrust_analysis.py        analysis facade, resample/simplify/smooth
│   ├── image_digitizer.py        corrections, calibration, extraction (OpenCV)
│   ├── label_service.py          QPainter renderer, sheets, templates, exports
│   └── file_utils.py             encodings, atomic writes, number format
├── ui/                           windows and dialogs
│   ├── main_window.py, motor_editor.py, thrust_editor.py
│   ├── digitizer_window.py, label_editor.py, preferences_window.py
│   ├── label_printing.py, common.py, theme.py
│   └── dialogs/                  import preview, CSV export, analysis, validation, about
├── widgets/                      thrust_plot, thrust_table, image_calibration_widget, label_preview
├── resources/                    icons (SVG + app.ico), label templates (JSON), locale (.pot/.po/.mo)
├── documentation/                user_manual_<lang>.pdf, technical_documentation.html,
│                                 locale (manual .pot/.po/.mo), screenshots/<lang>, fonts (DejaVu)
├── tests/                        pytest suites + reference data
└── tools/                        generate_icons.py, capture_screenshots.py, generate_manual.py, build_translations.py,
                                  check_bundle.py
```

**Separation of responsibilities:** `models` contain the physics and validation
with no GUI dependency; `services` handle files and processing; the UI only
collects user input and calls the controller/services. Every modification of the
motor goes through `MotorDocument.modify()`, which records an undoable snapshot
and emits `changed`, keeping the properties panel, graph and table synchronised.

## File formats

* **ENG** – header `name diameter(mm) length(mm) delays propellant(kg) total(kg) manufacturer`,
  then `time thrust` lines (s, N); `;` comments; (0,0) implicit; ASCII, CRLF.
* **Project** – `RocketMotorProject formatVersion="1.1"` XML. Older versions are
  migrated on load (see `MIGRATIONS` in `services/xml_service.py`).

## Building the executable

`build_exe.bat` runs the tests, compiles the translations, regenerates the icons,
the screenshots and the manuals of every language, then runs PyInstaller with `RocketMotorManager.spec` (one-folder build, windowed,
icon `resources/icons/app.ico`, version resource `version_info.txt`). The result
in `dist\RocketMotorManager` runs on Windows without a Python installation; it can
be zipped or wrapped in an installer (Inno Setup, NSIS).

**Single-file executable.** `build_onefile.bat` runs
`PyInstaller main.py --onefile --windowed --icon=resources/icons/app.ico` with
every `--add-data` (icons, label templates, images, translations, manuals,
technical documentation) and `--hidden-import` the application needs, then
checks the result. Any build can be checked with:

```bat
python tools\check_bundle.py dist\RocketMotorManager.exe     :: --onefile build
python tools\check_bundle.py dist\RocketMotorManager         :: one-folder build
```

It compares the content of the executable with the resources of the source
tree and lists anything missing (exit code 1).

**Single-file executable with external resources.** `build_onefile_external.bat`
builds an executable that contains only the code and copies the resources beside
it:

```
dist\RocketMotorManager_onefile\
├── RocketMotorManager.exe
├── resources\        icons, templates, images, locale (*.mo)
└── documentation\    user_manual_<lang>.pdf, technical_documentation.html
```

Deliver the whole folder. The application looks for each resource first beside
the executable, then inside the bundle, then in the source tree
(`application/paths.py`), so a manual, a translation or a label template can be
replaced without rebuilding, and an external file overrides an embedded one.

## Translations

The interface is available in **English, Français, Deutsch, Español, Italiano,
Nederlands, Polski, Português and Русский** (*Edit > Preferences > General >
Language*, restart required). Translations use GNU gettext:

```
resources/locale/rocketmotormanager.pot                  template (extracted from the sources)
resources/locale/<lang>/LC_MESSAGES/rocketmotormanager.po translations (edit these)
resources/locale/<lang>/LC_MESSAGES/rocketmotormanager.mo compiled (loaded by the application)
```

* Code: mark texts with `_("text")`, `ngettext("{n} point", "{n} points", n)` or
  `N_("text")` for constants (`from localization import _`). Placeholders use
  named `str.format` fields (`{path}`), never positional ones.
* Edit a `.po` file with Poedit, Lokalize or a text editor, then run
  `python tools/build_translations.py` (extract → update → check → compile).
  Placeholder mismatches are reported and block the compilation.
* New language: `python tools/build_translations.py init xx`, translate, add the
  code to `LANGUAGES` in `localization/__init__.py`, then rebuild.
* Qt's standard dialogs (Yes/No buttons, file dialogs, print preview) use Qt's
  own `qtbase_<lang>.qm` catalogues; Qt only ships Brazilian Portuguese.

### User manual

*Help > Manual* (F1) opens `documentation/user_manual_<lang>.pdf` for the
interface language (English if that language has no manual). The manual texts
are a second gettext catalogue, `manual`:

```
documentation/locale/manual.pot                       template (extracted from tools/generate_manual.py)
documentation/locale/<lang>/LC_MESSAGES/manual.po     translations (edit these)
documentation/locale/<lang>/LC_MESSAGES/manual.mo     compiled (used by generate_manual.py)
```

* Interface elements are written `[[&File|&New Motor]]` in the manual texts:
  the generator replaces them with the captions of the application catalogue
  ("Fichier > Nouveau moteur"), so the manual always matches the translated
  interface. Translators keep these references unchanged (checked by
  `build_translations.py` and the tests).
* `python tools/capture_screenshots.py --lang all` captures the illustrations
  of every language into `documentation/screenshots/<lang>/`.
* `python tools/generate_manual.py [fr de ...]` builds the PDF manuals (all
  languages by default) with the DejaVu fonts of `documentation/fonts`
  (Latin, Polish and Cyrillic characters).

## Log and settings

* Preferences: `%APPDATA%\RocketMotorManager\preferences.json`
* User label templates: `%APPDATA%\RocketMotorManager\label_templates\`
* Log: `%LOCALAPPDATA%\RocketMotorManager\logs\rocket_motor_manager.log`
