"""Main application window: menus, toolbar, docks and file workflows."""

from __future__ import annotations

import localization
from localization import N_, _, ngettext

import copy
import logging
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QByteArray, QSize, Qt, QThreadPool, QUrl
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QToolBar,
    QToolButton,
)

from application.application_controller import ApplicationController
from application.error_handler import reporter
from application.workers import TaskWorker
from application.paths import resource_path
from application.version import APP_NAME
from models.errors import RocketMotorError
from models.label_template import LabelTemplate
from models.thrust_point import ThrustPoint
from services.image_digitizer import SUPPORTED_IMAGE_FILTER
from services.label_service import LabelService, label_values
from services.xml_service import PROJECT_EXTENSION
from ui import label_printing
from ui.common import icon
from ui.dialogs.about_dialog import AboutDialog
from ui.dialogs.analysis_dialog import AnalysisDialog
from ui.dialogs.csv_export_dialog import CsvExportDialog
from ui.dialogs.srm_import_dialog import SrmImportDialog
from ui.dialogs.tabular_import_dialog import TabularImportDialog
from ui.dialogs.validation_dialog import ValidationDialog
from ui.digitizer_window import DigitizerWindow
from ui.label_editor import LabelEditorWindow
from ui.motor_editor import MotorEditorWidget
from ui.preferences_window import PreferencesWindow
from ui.theme import apply_theme, plot_colors
from ui.thrust_editor import ThrustEditorWidget
from widgets.thrust_plot import EXPORT_FORMATS

logger = logging.getLogger(__name__)

PROJECT_FILTER = N_("Rocket Motor Manager project (*.rmm.xml *.xml)")
ENG_FILTER = N_("RASP engine files (*.eng *.ENG)")
CSV_FILTER = N_("CSV / text files (*.csv *.txt *.tsv *.dat)")
EXCEL_FILTER = N_("Excel workbooks (*.xlsx *.xlsm *.xls)")
SRM_FILTER = N_("SRM workbooks (Richard Nakka) (*.xls *.xlsx *.xlsm)")


def manual_path(language: str) -> Path:
    """User manual of a language: ``documentation/user_manual_<lang>.pdf``,
    falling back to the English manual when that language has none."""
    for code in (language, "en"):
        candidate = resource_path("documentation", f"user_manual_{code}.pdf")
        if candidate.exists():
            return candidate
    return resource_path("documentation", f"user_manual_{language}.pdf")


class MainWindow(QMainWindow):
    """The Rocket Motor Manager main window."""

    def __init__(self, controller: ApplicationController) -> None:
        super().__init__()
        self.controller = controller
        self.document = controller.document
        self.actions: dict[str, QAction] = {}
        self._digitizer: Optional[DigitizerWindow] = None
        self._label_editor: Optional[LabelEditorWindow] = None
        self.setWindowIcon(icon("app"))
        self.setAcceptDrops(True)
        self._build_central()
        self._create_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()
        self._connect()
        self._restore_layout()
        self._apply_visual_preferences()
        self._update_title()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_central(self) -> None:
        self.thrust_editor = ThrustEditorWidget(self.document)
        self.setCentralWidget(self.thrust_editor)
        self.motor_editor = MotorEditorWidget(self.document, self.controller.analysis_service)
        self.properties_dock = QDockWidget(_("Motor properties"), self)
        self.properties_dock.setObjectName("properties_dock")
        self.properties_dock.setWidget(self.motor_editor)
        self.properties_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                                         | QDockWidget.DockWidgetFeature.DockWidgetClosable
                                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.properties_dock)

    def _action(self, key: str, text: str, slot: Callable, icon_name: str = "", shortcut=None, tip: str = "",
                checkable: bool = False) -> QAction:
        action = QAction(icon(icon_name) if icon_name else icon("none"), text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut) if isinstance(shortcut, str) else shortcut)
        action.setToolTip(f"{tip} ({action.shortcut().toString()})" if tip and shortcut is not None else tip or text)
        action.setStatusTip(tip or text)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        self.actions[key] = action
        return action

    def _create_actions(self) -> None:
        sk = QKeySequence.StandardKey
        a = self._action
        a("new", _("&New Motor"), self.new_motor, "new", sk.New, _("Create a new empty motor"))
        a("open", _("&Open Motor..."), self.open_motor_dialog, "open", sk.Open, _("Open a motor project (XML)"))
        a("save", _("&Save Motor"), self.save_motor, "save", sk.Save, _("Save the motor project"))
        a("save_as", _("Save Motor &As..."), self.save_motor_as, "save_as", sk.SaveAs, _("Save the project under a new name"))
        a("import_eng", _("Import &ENG..."), self.import_eng, "eng", "Ctrl+E", _("Import a RASP .eng thrust curve file"))
        a("export_eng", _("E&xport as ENG..."), self.export_eng, "export", "Ctrl+Shift+E", _("Export the motor as an OpenRocket/RockSim .eng file"))
        a("import_csv", _("Import &CSV..."), self.import_csv, "csv", None, _("Import thrust points from a CSV or text file"))
        a("export_csv", _("Export CS&V..."), self.export_csv, "csv", None, _("Export the thrust points to a CSV file"))
        a("import_excel", _("Import Exce&l..."), self.import_excel, "csv", None, _("Import thrust points from an Excel workbook (.xlsx, .xls)"))
        a("import_srm", _("Import &SRM Workbook (Nakka)..."), self.import_srm, "eng", None,
          _("Import motor data and thrust curve from a Richard Nakka SRM design workbook (SRM 1.x, SRM 2023)"))
        a("import_image", _("Import Thrust Curve &Image..."), self.import_image, "image", None, _("Digitize a thrust curve from a photo or scan"))
        a("export_graph", _("Export &Graph..."), self.export_graph, "image", None, _("Export the thrust curve as PNG, SVG or PDF"))
        a("exit", _("E&xit"), self.close, "exit", sk.Quit, _("Quit the application"))

        undo = self.document.undo_stack.createUndoAction(self, _("&Undo"))
        undo.setIcon(icon("undo"))
        undo.setShortcut(sk.Undo)
        redo = self.document.undo_stack.createRedoAction(self, _("&Redo"))
        redo.setIcon(icon("redo"))
        redo.setShortcut(sk.Redo)
        self.actions["undo"], self.actions["redo"] = undo, redo
        a("add_point", _("&Add Thrust Point"), self.thrust_editor.add_point, "add_point", "Ctrl+Ins", _("Add a thrust point after the selection"))
        a("delete_point", _("&Delete Thrust Point"), self.thrust_editor.delete_points, "delete_point", "Ctrl+Del", _("Delete the selected thrust point(s)"))
        a("select_all", _("Select &All"), self.select_all, "", sk.SelectAll, _("Select every thrust point"))
        a("sort", _("&Sort Points"), self.document.sort_points, "sort", None, _("Sort the thrust points chronologically"))
        a("preferences", _("&Preferences..."), self.show_preferences, "settings", sk.Preferences if not QKeySequence(sk.Preferences).isEmpty() else "Ctrl+,", _("Application preferences"))

        a("show_graph", _("Show Thrust &Graph"), self.thrust_editor.show_plot, "", None, _("Show or hide the thrust curve"), True)
        a("show_table", _("Show Data &Table"), self.thrust_editor.show_table, "", None, _("Show or hide the thrust data table"), True)
        self.actions["show_properties"] = self.properties_dock.toggleViewAction()
        self.actions["show_properties"].setText(_("Show Motor &Properties"))
        a("reset_zoom", _("&Reset Graph Zoom"), self.thrust_editor.plot.reset_zoom, "zoom_reset", "Ctrl+0", _("Fit the graph to the data"))
        a("show_grid", _("Show &Grid"), self.toggle_grid, "grid", "Ctrl+G", _("Show or hide the graph grid"), True)
        self.actions["show_graph"].setChecked(True)
        self.actions["show_table"].setChecked(True)

        a("print_preview", _("Print Pre&view..."), self.label_print_preview, "print", None, _("Preview the label sheet"))
        a("print_pdf", _("Print &PDF..."), self.label_print_pdf, "pdf", sk.Print, _("Export the label sheet as PDF"))
        a("export_label_png", _("Export Label as P&NG..."), lambda: self.label_export_image("png"), "image", None, _("Export the label as a PNG image"))
        a("export_label_jpeg", _("Export Label as &JPEG..."), lambda: self.label_export_image("jpg"), "image", None, _("Export the label as a JPEG image"))

        a("analysis", _("Thrust &Analysis..."), self.show_analysis, "analyze", "F5", _("Compute and display the motor characteristics"))
        a("digitizer", _("Curve &Digitizer..."), self.show_digitizer, "digitize", "F6", _("Digitize a thrust curve from an image"))
        a("label_designer", _("&Label Designer..."), self.show_label_designer, "label", "F7", _("Design and print motor labels"))
        a("validation", _("Data &Validation..."), self.show_validation, "validate", "F8", _("Check the motor data for errors"))

        a("manual", _("&Manual"), self.open_manual, "manual", sk.HelpContents, _("Open the PDF user manual"))
        a("documentation", _("&Documentation"), self.open_documentation, "help", None, _("Open the technical documentation folder"))
        a("about", _("&About..."), lambda: AboutDialog(self).exec(), "info", None, _("About Rocket Motor Manager"))

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu(_("&File"))
        for key in ("new", "open", "save", "save_as", None, "import_eng", "export_eng", None, "import_csv", "export_csv",
                    "import_excel", "import_srm", None, "import_image", "export_graph", None):
            file_menu.addSeparator() if key is None else file_menu.addAction(self.actions[key])
        self.recent_menu = file_menu.addMenu(icon("open"), _("Recent &Files"))
        file_menu.addSeparator()
        file_menu.addAction(self.actions["exit"])
        self._fill_recent_menu()

        edit_menu = bar.addMenu(_("&Edit"))
        for key in ("undo", "redo", None, "add_point", "delete_point", "sort", "select_all", None, "preferences"):
            edit_menu.addSeparator() if key is None else edit_menu.addAction(self.actions[key])

        view_menu = bar.addMenu(_("&View"))
        for key in ("show_graph", "show_table", "show_properties", None, "reset_zoom", "show_grid"):
            view_menu.addSeparator() if key is None else view_menu.addAction(self.actions[key])

        print_menu = bar.addMenu(_("&Print"))
        for key in ("print_preview", "print_pdf", None, "export_label_png", "export_label_jpeg"):
            print_menu.addSeparator() if key is None else print_menu.addAction(self.actions[key])

        tools_menu = bar.addMenu(_("&Tools"))
        for key in ("analysis", "digitizer", "label_designer", "validation"):
            tools_menu.addAction(self.actions[key])

        help_menu = bar.addMenu(_("&Help"))
        for key in ("manual", "documentation", None, "about"):
            help_menu.addSeparator() if key is None else help_menu.addAction(self.actions[key])

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(_("Main toolbar"))
        toolbar.setObjectName("main_toolbar")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(toolbar)
        for key in ("new", "open", "save"):
            toolbar.addAction(self.actions[key])
        toolbar.addSeparator()
        toolbar.addWidget(self._menu_button(_("Import"), "import", _("Import ENG, CSV, Excel or an image"),
                                            ("import_eng", "import_csv", "import_excel", "import_srm", "import_image")))
        toolbar.addWidget(self._menu_button(_("Export"), "export", _("Export ENG, CSV or the graph"),
                                            ("export_eng", "export_csv", "export_graph")))
        toolbar.addSeparator()
        for key in ("undo", "redo", "add_point", "delete_point"):
            toolbar.addAction(self.actions[key])
        toolbar.addSeparator()
        for key, text in (("analysis", _("Analyze")), ("digitizer", _("Digitize")), ("label_designer", _("Label"))):
            action = self.actions[key]
            action.setIconText(text)
            toolbar.addAction(action)
        self.actions["add_point"].setIconText(_("Add Point"))
        self.actions["delete_point"].setIconText(_("Delete Point"))

    def _menu_button(self, text: str, icon_name: str, tip: str, keys: tuple[str, ...]) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setIcon(icon(icon_name))
        button.setToolTip(tip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setAutoRaise(True)
        menu = QMenu(button)
        for key in keys:
            menu.addAction(self.actions[key])
        button.setMenu(menu)
        return button

    def _build_status_bar(self) -> None:
        self.file_label = QLabel()
        self.summary_label = QLabel()
        self.cursor_label = QLabel()
        self.statusBar().addWidget(self.file_label, 1)
        self.statusBar().addPermanentWidget(self.summary_label)
        self.statusBar().addPermanentWidget(self.cursor_label)

    def _connect(self) -> None:
        self.document.changed.connect(self._update_summary)
        self.document.modified_changed.connect(self._update_title)
        self.document.file_path_changed.connect(self._update_title)
        self.controller.recent_files_changed.connect(self._fill_recent_menu)
        self.controller.preferences_changed.connect(self._apply_visual_preferences)
        self.thrust_editor.plot.cursor_info.connect(self.cursor_label.setText)
        self._update_summary()

    # ------------------------------------------------------------------
    # Window state
    # ------------------------------------------------------------------
    def _restore_layout(self) -> None:
        prefs = self.controller.preferences
        if prefs.window_geometry:
            self.restoreGeometry(QByteArray.fromHex(prefs.window_geometry.encode()))
        else:
            self.resize(1400, 860)
        if prefs.window_state:
            self.restoreState(QByteArray.fromHex(prefs.window_state.encode()))

    def _save_layout(self) -> None:
        prefs = self.controller.preferences
        prefs.window_geometry = bytes(self.saveGeometry().toHex()).decode()
        prefs.window_state = bytes(self.saveState().toHex()).decode()
        self.controller.configuration.save()

    def _apply_visual_preferences(self) -> None:
        prefs = self.controller.preferences
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, prefs.theme)
        self.thrust_editor.set_colors(plot_colors(prefs.theme))
        self.motor_editor.set_analysis_service(self.controller.analysis_service)
        self.actions["show_grid"].setChecked(self.document.motor.plot_settings.show_grid)

    def _update_title(self, *_args) -> None:
        name = self.document.display_name()
        self.setWindowTitle(f"{name}[*] - {APP_NAME}")
        self.setWindowModified(self.document.is_modified)
        self.file_label.setText(self.document.file_path or _("Not saved"))
        self.actions["show_grid"].setChecked(self.document.motor.plot_settings.show_grid)

    def _update_summary(self, *_args) -> None:
        motor = self.document.motor
        result = self.document.characteristics()
        text = ngettext("{n} point", "{n} points", motor.point_count()).format(n=motor.point_count())
        if result.total_impulse_ns is not None:
            text += f"  |  I = {result.total_impulse_ns:.2f} N.s"
            if result.impulse_class:
                text += f" ({result.impulse_class})"
        self.summary_label.setText(text)
        self._update_title()

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = self.controller.preferences.recent_files
        for index, path in enumerate(recent, start=1):
            action = self.recent_menu.addAction(f"&{index}  {Path(path).name}")
            action.setToolTip(path)
            action.setStatusTip(path)
            action.triggered.connect(lambda _c=False, p=path: self.open_recent(p))
        if recent:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction(_("Clear list"), self.controller.clear_recent)
        self.recent_menu.setEnabled(bool(recent))

    # ------------------------------------------------------------------
    # Data protection
    # ------------------------------------------------------------------
    def maybe_save(self) -> bool:
        """Ask to save unsaved changes. Returns False if the user cancels."""
        if not self.document.is_modified:
            return True
        answer = QMessageBox.warning(
            self, _("Unsaved changes"),
            _("The motor '{name}' has unsaved changes.\nDo you want to save them?").format(name=self.document.display_name()),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_motor()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.maybe_save():
            event.ignore()
            return
        for window in (self._digitizer, self._label_editor):
            if window is not None:
                window.close()
                if window.isVisible():
                    event.ignore()
                    return
        self._save_layout()
        logger.info("Application closed")
        event.accept()

    def _ask_open(self, title: str, file_filter: str) -> str:
        folder = self.controller.preferences.import_dir
        path, _selected_filter = QFileDialog.getOpenFileName(self, title, folder, _(file_filter) + ";;" + _("All files (*)"))
        if path:
            self.controller.preferences.import_dir = str(Path(path).parent)
        return path

    def _ask_save(self, title: str, file_filter: str, suggested: str, extension: str) -> str:
        """Ask a target path; the dialog confirms before overwriting a file."""
        start = str(Path(self.controller.preferences.default_save_dir) / suggested)
        path, _selected_filter = QFileDialog.getSaveFileName(self, title, start, _(file_filter))
        if path and not path.lower().endswith(extension.lower()):
            path += extension
            if Path(path).exists() and QMessageBox.question(
                self, title, _("'{name}' already exists. Replace it?").format(name=Path(path).name)
            ) != QMessageBox.StandardButton.Yes:
                return ""
        return path

    def _suggested_name(self) -> str:
        meta = self.document.motor.metadata
        base = meta.designation or meta.name or "motor"
        return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in base)

    # ------------------------------------------------------------------
    # File menu
    # ------------------------------------------------------------------
    def new_motor(self) -> None:
        """File > New Motor."""
        if self.maybe_save():
            self.controller.new_motor()
            self.thrust_editor.plot.reset_zoom()

    def open_motor_dialog(self) -> None:
        """File > Open Motor."""
        if not self.maybe_save():
            return
        folder = self.controller.preferences.default_save_dir
        path, _selected_filter = QFileDialog.getOpenFileName(self, _("Open motor project"), folder, _(PROJECT_FILTER) + ";;" + _("All files (*)"))
        if path:
            self.open_path(path)

    def open_recent(self, path: str) -> None:
        """Open a recent file (removed from the list if missing)."""
        if not Path(path).exists():
            reporter().warning(self, _("Recent files"), _("The file no longer exists:\n{path}").format(path=path))
            self.controller.forget_recent(path)
            return
        if self.maybe_save():
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        """Open any supported file type by extension (used by drag & drop)."""
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".eng":
                return self._load_eng(path)
            if suffix in (".csv", ".txt", ".tsv", ".dat"):
                return self._import_tabular(path, "csv")
            if suffix in (".xlsx", ".xlsm", ".xls"):
                return self._import_excel_path(path)
            if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
                self.show_digitizer(path)
                return True
            result = self.controller.open_project(path)
            for warning in result.warnings:
                self.statusBar().showMessage(warning, 8000)
            self.thrust_editor.plot.reset_zoom()
            self.statusBar().showMessage(_("Opened {path}").format(path=path), 5000)
            return True
        except RocketMotorError as exc:
            reporter().error(self, exc, _("Cannot open the file."))
            return False

    def save_motor(self) -> bool:
        """File > Save Motor (asks a name the first time)."""
        if not self.document.file_path:
            return self.save_motor_as()
        return self._save_to(self.document.file_path)

    def save_motor_as(self) -> bool:
        """File > Save Motor As."""
        path = self._ask_save(_("Save motor project"), PROJECT_FILTER, self._suggested_name() + PROJECT_EXTENSION,
                              PROJECT_EXTENSION)
        return self._save_to(path) if path else False

    def _save_to(self, path: str) -> bool:
        if self._label_editor is not None and self._label_editor.isVisible():
            self._store_label(self._label_editor.current_template())
        try:
            self.controller.save_project(path)
        except RocketMotorError as exc:
            reporter().error(self, exc, _("The project could not be saved."))
            return False
        self.statusBar().showMessage(_("Saved {path}").format(path=path), 5000)
        return True

    def import_eng(self) -> None:
        """File > Import ENG."""
        if not self.maybe_save():
            return
        path = self._ask_open(_("Import ENG file"), ENG_FILTER)
        if path:
            try:
                self._load_eng(path)
            except RocketMotorError as exc:
                reporter().error(self, exc, _("Cannot import the ENG file."))

    def _load_eng(self, path: str) -> bool:
        result = self.controller.read_eng(path)
        motor = result.motors[0]
        if len(result.motors) > 1:
            names = [f"{m.metadata.name} ({m.metadata.manufacturer})" for m in result.motors]
            choice, ok = QInputDialog.getItem(self, _("Select a motor"),
                                              _("This file contains several motors:"), names, 0, False)
            if not ok:
                return False
            motor = result.motors[names.index(choice)]
        self.controller.load_imported_motor(motor)
        self.thrust_editor.plot.reset_zoom()
        if result.warnings:
            reporter().warning(self, _("ENG import"), "\n".join(result.warnings))
        self.statusBar().showMessage(_("Imported {name} from {path}").format(name=motor.metadata.name, path=path), 6000)
        return True

    def export_eng(self) -> None:
        """File > Export as ENG (validated first)."""
        report = self.controller.validate()
        if report.issues and (not report.is_valid or report.warnings):
            dialog = ValidationDialog(report, _("ENG export - validation"),
                                      _("Export anyway") if report.is_valid else "", self)
            dialog.row_requested.connect(self.thrust_editor.table.select_row)
            if not report.is_valid:
                dialog.exec()
                return
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
        path = self._ask_save(_("Export as ENG"), ENG_FILTER, self._suggested_name() + ".eng", ".eng")
        if not path:
            return
        try:
            self.controller.export_eng(path, allow_warnings=True)
        except RocketMotorError as exc:
            reporter().error(self, exc)
            return
        self.statusBar().showMessage(_("ENG file exported: {path}").format(path=path), 6000)

    def import_csv(self) -> None:
        """File > Import CSV."""
        path = self._ask_open(_("Import CSV file"), CSV_FILTER)
        if path:
            self._import_tabular(path, "csv")

    def import_excel(self) -> None:
        """File > Import Excel."""
        path = self._ask_open(_("Import Excel file"), EXCEL_FILTER)
        if path:
            self._import_excel_path(path)

    def _import_excel_path(self, path: str) -> bool:
        """Import an Excel file, offering the structured SRM import when the
        workbook is a Richard Nakka SRM workbook."""
        if self.controller.srm_service.is_srm_workbook(path):
            answer = QMessageBox.question(
                self, _("SRM workbook detected"),
                _("'{name}' is a Richard Nakka SRM motor design workbook.\n\nYes: import the motor (properties and thrust curve) from its sheets.\nNo: import columns manually as a plain table.").format(name=Path(path).name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                return self._import_srm(path)
            if answer != QMessageBox.StandardButton.No:
                return False
        return self._import_tabular(path, "excel")

    def import_srm(self) -> None:
        """File > Import SRM Workbook."""
        path = self._ask_open(_("Import SRM workbook"), SRM_FILTER)
        if path:
            self._import_srm(path)

    def _import_srm(self, path: str) -> bool:
        """Read an SRM workbook in the background, then open the import dialog."""
        if not self.maybe_save():
            return False
        self.statusBar().showMessage(_("Reading SRM workbook {name}...").format(name=Path(path).name))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        worker = TaskWorker(self.controller.srm_service.read, path)
        worker.signals.finished.connect(lambda workbook: self._on_srm_read(workbook, path))
        worker.signals.failed.connect(self._on_srm_failed)
        QThreadPool.globalInstance().start(worker)
        return True

    def _on_srm_failed(self, exc: Exception) -> None:
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
        reporter().error(self, exc, _("Cannot import the SRM workbook."))

    def _on_srm_read(self, workbook, path: str) -> None:
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
        dialog = SrmImportDialog(workbook, path, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.motor is None:
            return
        self.controller.load_imported_motor(dialog.motor)
        self.thrust_editor.plot.reset_zoom()
        self.statusBar().showMessage(
            _("Imported {name} from SRM workbook {path}").format(name=dialog.motor.metadata.name, path=path), 6000)

    def _import_tabular(self, path: str, kind: str) -> bool:
        dialog = TabularImportDialog(path, kind, self.controller.csv_service, self.controller.excel_service, self)
        if dialog.exec() != dialog.DialogCode.Accepted or not dialog.points:
            return False
        return self.replace_points(dialog.points, Path(path).name)

    def replace_points(self, points: list[ThrustPoint], source: str) -> bool:
        """Replace the current thrust curve after confirmation (undoable)."""
        if self.document.motor.points:
            answer = QMessageBox.question(
                self, _("Replace thrust data"),
                _("Replace the {current} current thrust point(s) with {imported} imported point(s)?\n(This can be undone with Ctrl+Z.)").format(current=str(self.document.motor.point_count()), imported=str(len(points))),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.controller.replace_points(points, source)
        self.thrust_editor.plot.reset_zoom()
        self.statusBar().showMessage(_("{count} point(s) imported from {source}").format(count=str(len(points)), source=source), 6000)
        return True

    def export_csv(self) -> None:
        """File > Export CSV."""
        if not self.document.motor.points:
            reporter().warning(self, _("Export CSV"), _("There is no thrust point to export."))
            return
        dialog = CsvExportDialog(self.controller.preferences.decimal_separator, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        path = self._ask_save(_("Export CSV"), CSV_FILTER, self._suggested_name() + ".csv", ".csv")
        if not path:
            return
        try:
            self.controller.export_csv(path, dialog.options())
        except (RocketMotorError, ValueError) as exc:
            reporter().error(self, exc)
            return
        self.statusBar().showMessage(_("CSV file exported: {path}").format(path=path), 6000)

    def import_image(self) -> None:
        """File > Import Thrust Curve Image."""
        path = self._ask_open(_("Import thrust curve image"), SUPPORTED_IMAGE_FILTER)
        if path:
            self.show_digitizer(path)

    def export_graph(self) -> None:
        """Export the graph as PNG, SVG or PDF."""
        start = str(Path(self.controller.preferences.default_save_dir) / (self._suggested_name() + "_thrust.png"))
        path, selected = QFileDialog.getSaveFileName(self, _("Export graph"), start, _(EXPORT_FORMATS))
        if not path:
            return
        if Path(path).suffix.lower() not in (".png", ".svg", ".pdf"):
            path += ".svg" if "svg" in selected.lower() else ".pdf" if "pdf" in selected.lower() else ".png"
        try:
            self.thrust_editor.plot.export(path)
        except (OSError, ValueError) as exc:
            reporter().error(self, exc, _("The graph could not be exported."))
            return
        self.statusBar().showMessage(_("Graph exported: {path}").format(path=path), 6000)

    # ------------------------------------------------------------------
    # Edit / View
    # ------------------------------------------------------------------
    def select_all(self) -> None:
        """Edit > Select All (thrust points)."""
        self.thrust_editor.table.select_all()

    def toggle_grid(self, checked: bool) -> None:
        """View > Show Grid (saved with the project)."""
        settings = copy.copy(self.document.motor.plot_settings)
        settings.show_grid = checked
        self.document.set_plot_settings(settings)

    def show_preferences(self) -> None:
        """Edit > Preferences."""
        dialog = PreferencesWindow(self.controller.preferences, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        prefs = dialog.result_preferences()
        self.controller.apply_preferences(prefs)
        settings = copy.copy(self.document.motor.plot_settings)
        settings.line_color, settings.marker_color = prefs.plot_line_color, prefs.plot_marker_color
        settings.show_grid, settings.show_markers = prefs.show_grid, prefs.plot_show_markers
        settings.fill_under_curve = prefs.plot_fill_under_curve
        if settings != self.document.motor.plot_settings:
            self.document.set_plot_settings(settings)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def show_analysis(self) -> None:
        """Tools > Thrust Analysis."""
        prefs = self.controller.preferences
        AnalysisDialog(self.document.motor, prefs.burn_time_method, prefs.unit_system, self).exec()

    def show_validation(self) -> None:
        """Tools > Data Validation."""
        dialog = ValidationDialog(self.controller.validate(), parent=self)
        dialog.row_requested.connect(self.thrust_editor.table.select_row)
        dialog.exec()

    def show_digitizer(self, image_path: str = "") -> None:
        """Tools > Curve Digitizer (optionally with an image)."""
        if self._digitizer is None:
            self._digitizer = DigitizerWindow(None, self.controller.preferences.import_dir)
            self._digitizer.setWindowIcon(icon("digitize"))
            self._digitizer.points_ready.connect(self._on_digitized)
        self._digitizer.show()
        self._digitizer.raise_()
        self._digitizer.activateWindow()
        if image_path:
            self._digitizer.load_image(image_path)

    def _on_digitized(self, points: list) -> None:
        if self.replace_points(points, _("the curve digitizer")):
            self.raise_()
            self.activateWindow()

    def show_label_designer(self) -> None:
        """Tools > Label Designer."""
        if self._label_editor is None:
            prefs = self.controller.preferences
            self._label_editor = LabelEditorWindow(self.document, lambda: self.controller.preferences.unit_system,
                                                   prefs.print_dpi, prefs.default_save_dir)
            self._label_editor.template_stored.connect(self._store_label)
        self._label_editor.show()
        self._label_editor.raise_()
        self._label_editor.activateWindow()

    def _store_label(self, template: LabelTemplate) -> None:
        if self.document.motor.label != template:
            self.document.set_label(template)

    # ------------------------------------------------------------------
    # Print menu (labels)
    # ------------------------------------------------------------------
    def _current_label(self) -> tuple[LabelTemplate, dict[str, str]]:
        if self._label_editor is not None and self._label_editor.isVisible():
            template = self._label_editor.current_template()
        elif self.document.motor.label is not None:
            template = copy.deepcopy(self.document.motor.label)
        else:
            builtin = LabelService.builtin_templates()
            name = self.controller.preferences.label_default_template
            template = copy.deepcopy(next((t for t in builtin if t.name == name), builtin[0]))
            template.paper_format = self.controller.preferences.print_paper_format
        values = label_values(self.document.motor, self.document.characteristics(), self.controller.preferences.unit_system)
        return template, values

    def label_print_preview(self) -> None:
        """Print > Print Preview."""
        label_printing.print_preview(self, *self._current_label())

    def label_print_pdf(self) -> None:
        """Print > Print PDF."""
        template, values = self._current_label()
        label_printing.export_pdf(self, template, values, self.controller.preferences.default_save_dir)

    def label_export_image(self, image_format: str) -> None:
        """Print > Export Label as PNG/JPEG."""
        template, values = self._current_label()
        label_printing.export_image(self, template, values, image_format, self.controller.preferences.print_dpi,
                                    self.controller.preferences.default_save_dir)

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------
    def open_manual(self) -> None:
        """Help > Manual: the PDF manual of the interface language."""
        manual = manual_path(localization.current_language())
        if not manual.exists():
            reporter().warning(self, _("Manual"), _("The user manual was not found:\n{manual}").format(manual=str(manual)))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(manual)))

    def open_documentation(self) -> None:
        """Help > Documentation."""
        folder = resource_path("documentation")
        target = folder / "technical_documentation.html"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target if target.exists() else folder)))

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not urls:
            return
        path = urls[0]
        suffix = Path(path).suffix.lower()
        if suffix in (".eng", ".xml") and not self.maybe_save():
            return
        self.open_path(path)
