"""Capture screenshots of the application for the user manual.

Run from the project root::

    python tools/capture_screenshots.py                 # English -> documentation/screenshots/en
    python tools/capture_screenshots.py --lang fr       # French  -> documentation/screenshots/fr
    python tools/capture_screenshots.py --lang all      # every language (one process each)

Works without a display (offscreen platform). Preferences are written to a
temporary folder so the user's settings are untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEMP = tempfile.mkdtemp(prefix="rmm_shots_")
os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = _TEMP
os.environ["XDG_STATE_HOME"] = os.environ["LOCALAPPDATA"] = _TEMP

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

SCREENSHOTS = ROOT / "documentation" / "screenshots"
OUTPUT = SCREENSHOTS / "en"


def save(widget: QWidget, name: str) -> None:
    """Grab a widget to PNG."""
    QApplication.processEvents()
    widget.grab().save(str(OUTPUT / f"{name}.png"))  # OUTPUT may be redirected by --out
    print("captured", name)


def synthetic_graph() -> np.ndarray:
    """A scanned-looking thrust curve picture for the digitizer screenshot."""
    image = np.full((520, 780, 3), (236, 242, 245), dtype=np.uint8)
    origin, sx, sy = (80, 450), 330.0, 22.0
    for i in range(1, 9):
        x = origin[0] + int(i * 0.25 * sx)
        cv2.line(image, (x, 30), (x, origin[1]), (200, 200, 200), 1)
        cv2.putText(image, f"{i * 0.25:.2f}", (x - 14, origin[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1)
    for i in range(1, 5):
        y = origin[1] - int(i * 4 * sy)
        cv2.line(image, (origin[0], y), (760, y), (200, 200, 200), 1)
        cv2.putText(image, str(i * 4), (origin[0] - 30, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1)
    cv2.line(image, origin, (760, origin[1]), (20, 20, 20), 2)
    cv2.line(image, origin, (origin[0], 20), (20, 20, 20), 2)
    cv2.putText(image, "Time (s)", (680, 500), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1)
    cv2.putText(image, "Thrust (N)", (90, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1)
    t = np.linspace(0, 1.86, 500)
    f = np.clip(t / 0.15, 0, 1) * (10 * np.exp(-((t - 0.19) / 0.06) ** 2) + np.where(t < 1.82, 4.3, 4.3 * (1.86 - t) / 0.04))
    curve = np.array([[origin[0] + ti * sx, origin[1] - fi * sy] for ti, fi in zip(t, f)], np.int32)
    cv2.polylines(image, [curve], False, (40, 40, 200), 3, cv2.LINE_AA)
    noise = np.random.default_rng(1).normal(0, 4, image.shape)
    return np.clip(image + noise, 0, 255).astype(np.uint8)


def main() -> None:
    global OUTPUT  # redirected by --out (script-level setting)
    import argparse

    import localization
    from application.translator import TranslationManager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="en", help="interface language (en, fr, de, es, it, nl, pl, pt, ru) or 'all'")
    parser.add_argument("--out", default=None, help="output folder (default: documentation/screenshots/<lang>)")
    args = parser.parse_args()
    if args.lang == "all":
        import subprocess

        for language in localization.LANGUAGES:
            subprocess.run([sys.executable, __file__, "--lang", language], check=True)
        return
    if args.lang not in localization.LANGUAGES:
        parser.error(f"unknown language '{args.lang}'")
    OUTPUT = Path(args.out) if args.out else SCREENSHOTS / args.lang
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    localization.install(args.lang)
    TranslationManager().install(app, args.lang)
    from application.application_controller import ApplicationController
    from services import image_digitizer as dig
    from ui.dialogs.analysis_dialog import AnalysisDialog
    from ui.dialogs.tabular_import_dialog import TabularImportDialog
    from ui.main_window import MainWindow
    from ui.preferences_window import PreferencesWindow

    controller = ApplicationController()
    window = MainWindow(controller)
    window.resize(1400, 820)
    window.show()
    motor = controller.read_eng(str(ROOT / "tests" / "data" / "sample_C6.eng")).motors[0]
    motor.metadata.designation = "C6-5"
    motor.metadata.propellant_type = "Black powder"
    motor.metadata.casing_mass_g = 10.3
    motor.metadata.nozzle_closure_mass_g = 2.0
    controller.load_imported_motor(motor)
    window.thrust_editor.table.select_row(3)
    window.thrust_editor.plot.select_point(3)
    save(window, "main_window")

    analysis = AnalysisDialog(controller.document.motor, "curve", "metric", window)
    analysis.show()
    save(analysis, "analysis")
    analysis.close()

    importer = TabularImportDialog(str(ROOT / "tests" / "data" / "comma_decimal.csv"), "csv",
                                   controller.csv_service, controller.excel_service, window)
    importer.show()
    save(importer, "csv_import")
    importer.close()

    from services.srm_service import SrmService
    from ui.dialogs.srm_import_dialog import SrmImportDialog

    srm_path = ROOT / "tests" / "data" / "SRM_2023.xls"
    srm = SrmImportDialog(SrmService().read(srm_path), str(srm_path), window)
    srm.show()
    save(srm, "srm_import")
    srm.close()

    window.show_digitizer()
    digitizer = window._digitizer
    digitizer.resize(1300, 780)
    digitizer.load_array(synthetic_graph())
    for label, x, y, t, f in (("Origin", 80, 450, 0.0, 0.0), ("Time max", 740, 450, 2.0, 0.0), ("Thrust max", 80, 98, 0.0, 16.0)):
        digitizer.calibration.set_point(dig.CalibrationPoint(x, y, t, f, label))
    digitizer._refresh_calibration()
    digitizer._auto_color()
    digitizer._on_extracted(dig.digitize(digitizer._display, digitizer.calibration, digitizer._collect_settings()))
    digitizer.tabs.setCurrentIndex(2)
    save(digitizer, "digitizer")
    digitizer._transferred = True
    digitizer.close()

    window.show_label_designer()
    editor = window._label_editor
    editor.resize(1200, 760)
    save(editor, "label_designer")
    editor.close()

    preferences = PreferencesWindow(controller.preferences, window)
    preferences.show()
    save(preferences, "preferences")
    preferences.close()
    controller.document.mark_saved("")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    main()
