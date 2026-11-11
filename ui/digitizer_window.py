"""Curve digitizer window (independent window).

Left: the image with overlays (original picture and digitized points shown
together). Right: correction, calibration and extraction tools, and a
Matplotlib preview of the reconstructed curve. "Transfer to motor editor"
emits :attr:`DigitizerWindow.points_ready`.
"""

from __future__ import annotations

from localization import N_, _

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QPushButton, QSlider, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from application.error_handler import reporter
from application.workers import TaskWorker
from models.errors import CalibrationError, RocketMotorError
from models.motor_calculations import total_impulse
from models.thrust_point import ThrustPoint
from services import image_digitizer as dig
from ui.common import icon, parse_float
from widgets.image_calibration_widget import ImageCalibrationWidget, ViewMode

logger = logging.getLogger(__name__)

#: Captions of the calibration references (the English names are the keys
#: stored in CalibrationPoint.label; they are translated when displayed).
_CALIBRATION_CAPTIONS = (N_("Origin"), N_("Time max"), N_("Thrust max"), N_("Extra"))

_DENOISE_CAPTIONS = {"none": N_("None"), "median": N_("Median"), "gaussian": N_("Gaussian"),
                     "bilateral": N_("Bilateral"), "nlmeans": N_("Non-local means")}

_CALIBRATION_LABELS = {
    ViewMode.CALIB_ORIGIN: "Origin",
    ViewMode.CALIB_TIME: "Time max",
    ViewMode.CALIB_THRUST: "Thrust max",
    ViewMode.CALIB_EXTRA: "Extra",
}

_MODE_HINTS = {
    ViewMode.NAVIGATE: N_("Navigate: drag to pan, wheel to zoom."),
    ViewMode.CALIB_ORIGIN: N_("Click the graph origin (intersection of the axes)."),
    ViewMode.CALIB_TIME: N_("Click a point of the time axis whose value you know (e.g. the last graduation)."),
    ViewMode.CALIB_THRUST: N_("Click a point of the thrust axis whose value you know (e.g. the top graduation)."),
    ViewMode.CALIB_EXTRA: N_("Click any point whose time and thrust you know (improves precision)."),
    ViewMode.PICK_COLOR: N_("Click on the curve to pick its colour."),
    ViewMode.CROP: N_("Drag a rectangle around the area to keep."),
    ViewMode.PERSPECTIVE: N_("Click the four corners of the graph frame (any order)."),
    ViewMode.EDIT_POINTS: N_("Drag a point to move it, click to add, right-click to delete, Shift+drag to erase an area."),
}


class CalibrationValueDialog(QDialog):
    """Ask the physical values of a calibration reference."""

    def __init__(self, label: str, time_default: float, thrust_default: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Calibration point - {label}").format(label=_(label)))
        form = QFormLayout(self)
        self.time = QDoubleSpinBox()
        self.time.setRange(0.0, 1000.0)
        self.time.setDecimals(4)
        self.time.setSuffix(" s")
        self.time.setValue(time_default)
        self.time.setToolTip(_("Time value of the clicked point in seconds."))
        self.thrust = QDoubleSpinBox()
        self.thrust.setRange(0.0, 1e6)
        self.thrust.setDecimals(4)
        self.thrust.setSuffix(" N")
        self.thrust.setValue(thrust_default)
        self.thrust.setToolTip(_("Thrust value of the clicked point in Newtons."))
        form.addRow(_("Time"), self.time)
        form.addRow(_("Thrust"), self.thrust)
        if label == "Time max":
            self.thrust.setEnabled(False)
            self.time.setFocus()
        elif label == "Thrust max":
            self.time.setEnabled(False)
            self.thrust.setFocus()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class DigitizerWindow(QMainWindow):
    """Thrust curve digitizer."""

    points_ready = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None, start_dir: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Curve Digitizer"))
        self.setWindowIcon(icon("digitize"))
        self.resize(1300, 820)
        self._start_dir = start_dir
        self._original: Optional[np.ndarray] = None
        self._history: list[np.ndarray] = []  # geometric corrections (undoable)
        self._base: Optional[np.ndarray] = None  # image after geometric corrections
        self._display: Optional[np.ndarray] = None  # after photometric corrections
        self.calibration = dig.AxisCalibration()
        self.settings = dig.DigitizerSettings()
        self._pixels = np.empty((0, 2))
        self._points: list[ThrustPoint] = []
        self._pool = QThreadPool.globalInstance()
        self._busy = False
        self._transferred = False
        self._photometric_timer = QTimer(self)
        self._photometric_timer.setSingleShot(True)
        self._photometric_timer.setInterval(250)
        self._photometric_timer.timeout.connect(self._apply_photometric)
        self._build_ui()
        self._update_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.view = ImageCalibrationWidget()
        self.view.clicked.connect(self._on_view_click)
        self.view.crop_selected.connect(self._on_crop)
        self.view.perspective_selected.connect(self._on_perspective)
        self.view.points_edited.connect(self._on_points_edited)
        self.view.cursor_moved.connect(self._on_cursor)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._image_tab(), _("1. Image"))
        self.tabs.addTab(self._calibration_tab(), _("2. Calibration"))
        self.tabs.addTab(self._extraction_tab(), _("3. Extraction"))
        self.figure = Figure(figsize=(4, 2.6), layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setToolTip(_("Reconstructed thrust curve (physical units)."))
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.transfer_button = QPushButton(icon("transfer"), _("Transfer to motor editor"))
        self.transfer_button.setToolTip(_("Replace the thrust points of the current motor with the digitized curve."))
        self.transfer_button.clicked.connect(self._transfer)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.tabs)
        right_layout.addWidget(self.canvas, 1)
        right_layout.addWidget(self.stats)
        right_layout.addWidget(self.transfer_button)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        self.view.setMinimumWidth(420)
        right.setMinimumWidth(380)
        right.setMaximumWidth(560)
        splitter.setSizes([800, 480])
        self.setCentralWidget(splitter)
        self._build_toolbar()
        self.mode_label = QLabel()
        self.cursor_label = QLabel()
        self.statusBar().addWidget(self.mode_label, 1)
        self.statusBar().addPermanentWidget(self.cursor_label)
        self._set_mode(ViewMode.NAVIGATE)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(_("Digitizer"))
        toolbar.setObjectName("digitizer_toolbar")
        self.addToolBar(toolbar)
        for text, icon_name, slot, shortcut, tip in (
            (_("Open image..."), "image", self.open_image_dialog, QKeySequence.StandardKey.Open,
             _("Open a photo, screenshot or scan (PNG, JPG, TIFF, BMP).")),
            (_("Fit to window"), "zoom_reset", self.view.fit, None, _("Show the whole image.")),
            (_("Navigate"), "target", lambda: self._set_mode(ViewMode.NAVIGATE), None,
             _("Pan and zoom tool (Esc).")),
        ):
            action = QAction(icon(icon_name), text, self)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            if shortcut is not None:
                action.setShortcut(shortcut)
            toolbar.addAction(action)
        escape = QAction(self)
        escape.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        escape.triggered.connect(lambda: self._set_mode(ViewMode.NAVIGATE))
        self.addAction(escape)

    def _button(self, text: str, tip: str, slot, icon_name: str = "") -> QPushButton:
        button = QPushButton(icon(icon_name), text) if icon_name else QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _image_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(-180.0, 180.0)
        self.rotation.setDecimals(2)
        self.rotation.setSingleStep(0.25)
        self.rotation.setSuffix(" °")
        self.rotation.setToolTip(_("Rotation angle (counter-clockwise, degrees) used to straighten the graph."))
        grid.addWidget(QLabel(_("Rotation")), 0, 0)
        grid.addWidget(self.rotation, 0, 1)
        grid.addWidget(self._button(_("Rotate"), _("Apply the rotation angle."), self._apply_rotation, "rotate"), 0, 2)
        grid.addWidget(self._button(_("Crop"), _("Drag a rectangle on the image to crop it."),
                                    lambda: self._set_mode(ViewMode.CROP), "crop"), 1, 0)
        grid.addWidget(self._button(_("Perspective"), _("Click the four corners of the graph frame to straighten a photo."),
                                    lambda: self._set_mode(ViewMode.PERSPECTIVE), "perspective"), 1, 1)
        grid.addWidget(self._button(_("Undo correction"), _("Undo the last rotation / crop / perspective."),
                                    self._undo_geometry, "undo"), 1, 2)
        self.contrast = QSlider(Qt.Orientation.Horizontal)
        self.contrast.setRange(20, 300)
        self.contrast.setValue(100)
        self.contrast.setToolTip(_("Contrast (100 % = unchanged)."))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(-100, 100)
        self.brightness.setValue(0)
        self.brightness.setToolTip(_("Brightness offset (0 = unchanged)."))
        self.grayscale = QCheckBox(_("Grey levels"))
        self.grayscale.setToolTip(_("Convert to grey levels (for black curves on coloured paper)."))
        self.denoise = QComboBox()
        for method in dig.DENOISE_METHODS:
            self.denoise.addItem(_(_DENOISE_CAPTIONS[method]), method)
        self.denoise.setToolTip(_("Noise filter: median (salt and pepper), gaussian (blur), bilateral "
                                        "(keeps edges), non-local means (photos, slow)."))
        self.denoise_strength = QSpinBox()
        self.denoise_strength.setRange(1, 10)
        self.denoise_strength.setValue(2)
        self.denoise_strength.setToolTip(_("Strength of the noise filter."))
        grid.addWidget(QLabel(_("Contrast")), 2, 0)
        grid.addWidget(self.contrast, 2, 1, 1, 2)
        grid.addWidget(QLabel(_("Brightness")), 3, 0)
        grid.addWidget(self.brightness, 3, 1, 1, 2)
        grid.addWidget(self.grayscale, 4, 0)
        grid.addWidget(self.denoise, 4, 1)
        grid.addWidget(self.denoise_strength, 4, 2)
        grid.addWidget(self._button(_("Reset all corrections"), _("Return to the original image."),
                                    self._reset_corrections), 5, 0, 1, 3)
        grid.setRowStretch(6, 1)
        for signal in (self.contrast.valueChanged, self.brightness.valueChanged, self.grayscale.toggled,
                       self.denoise.currentIndexChanged, self.denoise_strength.valueChanged):
            signal.connect(lambda *_: self._photometric_timer.start())
        return tab

    def _calibration_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QGridLayout()
        for index, (mode, text, tip) in enumerate((
            (ViewMode.CALIB_ORIGIN, _("Set origin"), _("Click the origin of the graph (time t0, thrust F0).")),
            (ViewMode.CALIB_TIME, _("Set time-axis point"), _("Click a known graduation on the time axis.")),
            (ViewMode.CALIB_THRUST, _("Set thrust-axis point"), _("Click a known graduation on the thrust axis.")),
            (ViewMode.CALIB_EXTRA, _("Add extra point"), _("Add any point with known time and thrust to improve precision.")),
        )):
            row.addWidget(self._button(text, tip, lambda _c=False, m=mode: self._set_mode(m), "target"), index // 2, index % 2)
        layout.addLayout(row)
        self.calibration_table = QTableWidget(0, 5)
        self.calibration_table.setHorizontalHeaderLabels([_("Reference"), "x (px)", "y (px)", _("Time (s)"), _("Thrust (N)")])
        self.calibration_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calibration_table.setToolTip(_("Calibration references. Time and thrust cells can be edited."))
        self.calibration_table.itemChanged.connect(self._on_calibration_edit)
        layout.addWidget(self.calibration_table)
        buttons = QHBoxLayout()
        buttons.addWidget(self._button(_("Remove selected"), _("Delete the selected reference."), self._remove_calibration))
        buttons.addWidget(self._button(_("Clear"), _("Delete every reference."), self._clear_calibration))
        layout.addLayout(buttons)
        self.calibration_status = QLabel()
        self.calibration_status.setWordWrap(True)
        layout.addWidget(self.calibration_status)
        return tab

    def _extraction_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        color_row = QHBoxLayout()
        color_row.addWidget(self._button(_("Auto-detect"), _("Detect the curve colour automatically."), self._auto_color))
        color_row.addWidget(self._button(_("Pick"), _("Click on the curve to pick its colour."),
                                         lambda: self._set_mode(ViewMode.PICK_COLOR), "pipette"))
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(46, 22)
        self.color_swatch.setToolTip(_("Colour of the curve to extract."))
        color_row.addWidget(self.color_swatch)
        form.addRow(_("Curve colour"), color_row)
        self.tolerance = QSlider(Qt.Orientation.Horizontal)
        self.tolerance.setRange(1, 100)
        self.tolerance.setValue(int(self.settings.tolerance))
        self.tolerance.setToolTip(_("Colour tolerance (CIE-Lab distance). Increase for faded or anti-aliased curves."))
        self.tolerance_label = QLabel()
        tolerance_row = QHBoxLayout()
        tolerance_row.addWidget(self.tolerance, 1)
        tolerance_row.addWidget(self.tolerance_label)
        form.addRow(_("Tolerance"), tolerance_row)
        self.extract_mode = QComboBox()
        self.extract_mode.addItem(_("Line centre"), "center")
        self.extract_mode.addItem(_("Top edge (filled curves)"), "top")
        self.extract_mode.setToolTip(_("Which pixel is used in each column of the image."))
        form.addRow(_("Detection"), self.extract_mode)
        self.use_area = QCheckBox(_("Only inside the calibrated area (axes excluded)"))
        self.use_area.setChecked(True)
        self.use_area.setToolTip(_("Restrict the search to the rectangle defined by the calibration points."))
        form.addRow("", self.use_area)
        self.outliers = QDoubleSpinBox()
        self.outliers.setRange(0.0, 20.0)
        self.outliers.setValue(self.settings.outlier_threshold)
        self.outliers.setToolTip(_("Outlier threshold in robust deviations (0 = disabled). Lower removes more points."))
        form.addRow(_("Outlier threshold"), self.outliers)
        self.max_points = QSpinBox()
        self.max_points.setRange(0, 5000)
        self.max_points.setValue(100)
        self.max_points.setSpecialValueText(_("All"))
        self.max_points.setToolTip(_("Resample the curve to this number of equally spaced points (All = one per pixel column)."))
        form.addRow(_("Number of points"), self.max_points)
        self.simplify = QDoubleSpinBox()
        self.simplify.setRange(0.0, 100.0)
        self.simplify.setDecimals(3)
        self.simplify.setSuffix(" N")
        self.simplify.setToolTip(_("Remove points while staying within this thrust tolerance (0 = keep all)."))
        form.addRow(_("Simplify tolerance"), self.simplify)
        self.close_curve = QCheckBox(_("End the curve with zero thrust"))
        self.close_curve.setChecked(True)
        self.close_curve.setToolTip(_("Append a final zero-thrust point (required by the ENG format)."))
        form.addRow("", self.close_curve)
        self.show_mask = QCheckBox(_("Show detected pixels"))
        self.show_mask.setToolTip(_("Overlay the pixels matching the colour in magenta."))
        self.show_mask.toggled.connect(self._refresh_mask)
        form.addRow("", self.show_mask)
        buttons = QGridLayout()
        self.extract_button = self._button(_("Extract curve"), _("Run the automatic extraction."), self._extract, "digitize")
        buttons.addWidget(self.extract_button, 0, 0)
        buttons.addWidget(self._button(_("Edit points"), _("Correct the extracted points manually."),
                                       lambda: self._set_mode(ViewMode.EDIT_POINTS), "add_point"), 0, 1)
        buttons.addWidget(self._button(_("Remove outliers"), _("Remove aberrant points from the current curve."),
                                       self._remove_outliers), 1, 0)
        buttons.addWidget(self._button(_("Clear points"), _("Delete every extracted point."), self._clear_points), 1, 1)
        form.addRow(buttons)
        self.tolerance.valueChanged.connect(self._on_tolerance)
        self._on_tolerance(self.tolerance.value())
        self._show_color()
        return tab

    # ------------------------------------------------------------------
    # Image loading and corrections
    # ------------------------------------------------------------------
    def open_image_dialog(self) -> None:
        """Ask for an image file and load it."""
        path, _selected_filter = QFileDialog.getOpenFileName(self, _("Open thrust curve image"), self._start_dir,
                                              _(dig.SUPPORTED_IMAGE_FILTER))
        if path:
            self.load_image(path)

    def load_image(self, path: str) -> bool:
        """Load an image file; returns False on error."""
        try:
            image = dig.load_image(path)
        except RocketMotorError as exc:
            reporter().error(self, exc)
            return False
        self._start_dir = str(Path(path).parent)
        self._original = image
        self._base = image
        self._history.clear()
        self._reset_photometric_widgets()
        self._display = image
        self.calibration.clear()
        self._set_pixels(np.empty((0, 2)))
        self.view.set_image(image, fit=True)
        self.setWindowTitle(_("Curve Digitizer - {name}").format(name=Path(path).name))
        self._refresh_calibration()
        self.tabs.setCurrentIndex(0)
        logger.info("Digitizer image loaded: %s (%dx%d)", path, image.shape[1], image.shape[0])
        return True

    def load_array(self, image: np.ndarray) -> None:
        """Load an image from memory (used by tests and screenshots)."""
        self._original = self._base = self._display = dig.normalize_image(image)
        self._history.clear()
        self.calibration.clear()
        self._set_pixels(np.empty((0, 2)))
        self.view.set_image(self._display, fit=True)
        self._refresh_calibration()

    def _confirm_geometry_change(self) -> bool:
        if not self.calibration.points and not len(self._pixels):
            return True
        answer = QMessageBox.question(self, _("Image correction"),
                                      _("Changing the image geometry clears the calibration and the extracted points. Continue?"))
        return answer == QMessageBox.StandardButton.Yes

    def _push_geometry(self, image: np.ndarray) -> None:
        self._history.append(self._base)
        self._base = image
        self.calibration.clear()
        self._set_pixels(np.empty((0, 2)))
        self._refresh_calibration()
        self._apply_photometric(fit=True)

    def _apply_rotation(self) -> None:
        if self._base is None or abs(self.rotation.value()) < 1e-9 or not self._confirm_geometry_change():
            return
        self._push_geometry(dig.rotate(self._base, self.rotation.value()))
        self.rotation.setValue(0.0)

    def _on_crop(self, rect: tuple) -> None:
        self._set_mode(ViewMode.NAVIGATE)
        if self._base is None or not self._confirm_geometry_change():
            return
        try:
            self._push_geometry(dig.crop(self._base, rect))
        except ValueError as exc:
            reporter().warning(self, _("Crop"), str(exc))

    def _on_perspective(self, corners: list) -> None:
        self._set_mode(ViewMode.NAVIGATE)
        if self._base is None or not self._confirm_geometry_change():
            return
        try:
            self._push_geometry(dig.correct_perspective(self._base, corners))
        except ValueError as exc:
            reporter().warning(self, _("Perspective"), str(exc))

    def _undo_geometry(self) -> None:
        if self._history and self._confirm_geometry_change():
            self._base = self._history.pop()
            self.calibration.clear()
            self._set_pixels(np.empty((0, 2)))
            self._refresh_calibration()
            self._apply_photometric(fit=True)

    def _reset_corrections(self) -> None:
        if self._original is None or not self._confirm_geometry_change():
            return
        self._history.clear()
        self._base = self._original
        self._reset_photometric_widgets()
        self.calibration.clear()
        self._set_pixels(np.empty((0, 2)))
        self._refresh_calibration()
        self._apply_photometric(fit=True)

    def _reset_photometric_widgets(self) -> None:
        for widget, value in ((self.contrast, 100), (self.brightness, 0), (self.denoise_strength, 2)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        for widget in (self.grayscale, self.denoise):
            widget.blockSignals(True)
        self.grayscale.setChecked(False)
        self.denoise.setCurrentIndex(0)
        for widget in (self.grayscale, self.denoise):
            widget.blockSignals(False)

    def _photometric_settings(self) -> dig.ImageCorrection:
        return dig.ImageCorrection(
            contrast=self.contrast.value() / 100.0, brightness=float(self.brightness.value()),
            grayscale=self.grayscale.isChecked(), denoise=self.denoise.currentData(),
            denoise_strength=self.denoise_strength.value(),
        )

    def _apply_photometric(self, fit: bool = False) -> None:
        """Apply contrast/brightness/grey/denoise in a background thread."""
        if self._base is None:
            return
        worker = TaskWorker(dig.apply_corrections, self._base, self._photometric_settings())
        worker.signals.finished.connect(lambda image: self._on_photometric_done(image, fit))
        worker.signals.failed.connect(lambda exc: reporter().error(self, exc))
        self.statusBar().showMessage(_("Processing image..."))
        self._pool.start(worker)

    def _on_photometric_done(self, image: np.ndarray, fit: bool) -> None:
        if self._base is None or image.shape[:2] != self._base.shape[:2]:
            return
        self._display = image
        self.view.set_image(image, fit=fit)
        self._refresh_mask()
        self.statusBar().clearMessage()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def _set_mode(self, mode: ViewMode) -> None:
        self.view.set_mode(mode)
        self.mode_label.setText(_(_MODE_HINTS[mode]))

    def _on_cursor(self, x: float, y: float) -> None:
        text = f"x = {x:.1f} px, y = {y:.1f} px"
        if self.calibration.is_ready():
            time_s, thrust_n = self.calibration.pixel_to_physical(np.array([[x, y]]))[0]
            text += f"   →   t = {time_s:.4f} s, F = {thrust_n:.3f} N"
        self.cursor_label.setText(text)

    def _on_view_click(self, mode: ViewMode, x: float, y: float) -> None:
        if mode == ViewMode.PICK_COLOR and self._display is not None:
            try:
                self.settings.color_bgr = dig.color_at(self._display, x, y)
            except ValueError:
                return
            self._show_color()
            self._refresh_mask()
            self._set_mode(ViewMode.NAVIGATE)
            return
        if mode not in _CALIBRATION_LABELS:
            return
        label = _CALIBRATION_LABELS[mode]
        origin = next((p for p in self.calibration.points if p.label == "Origin"), None)
        t0, f0 = (origin.time_s, origin.thrust_n) if origin else (0.0, 0.0)
        dialog = CalibrationValueDialog(label, t0, f0, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        time_s, thrust_n = dialog.time.value(), dialog.thrust.value()
        if label == "Time max":
            thrust_n = f0
        elif label == "Thrust max":
            time_s = t0
        self.calibration.set_point(dig.CalibrationPoint(x, y, time_s, thrust_n, label))
        if label == "Origin":  # keep the axis references consistent with a new origin
            for point in self.calibration.points:
                if point.label == "Time max":
                    point.thrust_n = thrust_n
                elif point.label == "Thrust max":
                    point.time_s = time_s
        self._refresh_calibration()
        self._next_calibration_step(mode)

    def _next_calibration_step(self, mode: ViewMode) -> None:
        sequence = [ViewMode.CALIB_ORIGIN, ViewMode.CALIB_TIME, ViewMode.CALIB_THRUST]
        labels = {p.label for p in self.calibration.points}
        if mode in sequence:
            for following in sequence:
                if _CALIBRATION_LABELS[following] not in labels:
                    self._set_mode(following)
                    return
        self._set_mode(ViewMode.NAVIGATE)
        if self.calibration.is_ready():
            self.tabs.setCurrentIndex(2)

    def _refresh_calibration(self) -> None:
        table = self.calibration_table
        table.blockSignals(True)
        table.setRowCount(len(self.calibration.points))
        for row, point in enumerate(self.calibration.points):
            values = (_(point.label), f"{point.px:.1f}", f"{point.py:.1f}", f"{point.time_s:g}", f"{point.thrust_n:g}")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column < 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, column, item)
        table.blockSignals(False)
        self.view.set_calibration_markers([(p.px, p.py, _(p.label)) for p in self.calibration.points])
        if self.calibration.is_ready():
            rms = self.calibration.rms_error()
            text = _("✔ Calibration ready.")
            if len(self.calibration.points) > 3:
                text += " " + _("Fit residual: {rms} px.").format(rms=f"{rms:.2f}")
            self.calibration_status.setStyleSheet("color: #2E8B57;")
        else:
            text = _("Define the origin, a time-axis point and a thrust-axis point.")
            self.calibration_status.setStyleSheet("color: #B9770E;")
        self.calibration_status.setText(text)
        if len(self._pixels):
            self._update_points_from_pixels()
        self._update_state()

    def _on_calibration_edit(self, item: QTableWidgetItem) -> None:
        row, column = item.row(), item.column()
        try:
            value = parse_float(item.text())
        except ValueError:
            value = None
        if value is None or value < 0:
            self._refresh_calibration()
            return
        point = self.calibration.points[row]
        if column == 3:
            point.time_s = value
        elif column == 4:
            point.thrust_n = value
        self._refresh_calibration()

    def _remove_calibration(self) -> None:
        rows = sorted({index.row() for index in self.calibration_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.calibration.remove(row)
        self._refresh_calibration()

    def _clear_calibration(self) -> None:
        self.calibration.clear()
        self._refresh_calibration()

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _on_tolerance(self, value: int) -> None:
        self.settings.tolerance = float(value)
        self.tolerance_label.setText(str(value))
        if self.show_mask.isChecked():
            self._refresh_mask()

    def _show_color(self) -> None:
        b, g, r = self.settings.color_bgr
        self.color_swatch.setStyleSheet(f"background: {QColor(r, g, b).name()}; border: 1px solid #888;")

    def _auto_color(self) -> None:
        if self._display is None:
            return
        roi = self.calibration.plot_area(self._display.shape) if self.calibration.is_ready() else None
        self.settings.color_bgr = dig.detect_curve_color(self._display, roi)
        self._show_color()
        self._refresh_mask()

    def _refresh_mask(self) -> None:
        if self._display is None or not self.show_mask.isChecked():
            self.view.set_mask(None)
            return
        self.view.set_mask(dig.color_mask(self._display, self.settings.color_bgr, self.settings.tolerance))

    def _collect_settings(self) -> dig.DigitizerSettings:
        settings = self.settings
        settings.mode = self.extract_mode.currentData()
        settings.use_plot_area = self.use_area.isChecked()
        settings.outlier_threshold = self.outliers.value()
        settings.max_points = self.max_points.value()
        settings.simplify_tolerance_n = self.simplify.value()
        settings.close_curve = self.close_curve.isChecked()
        return settings

    def _extract(self) -> None:
        if self._display is None or self._busy:
            return
        if not self.calibration.is_ready():
            reporter().warning(self, _("Calibration"), _("Calibrate the axes before extracting the curve (tab 2)."))
            self.tabs.setCurrentIndex(1)
            return
        self._busy = True
        self._update_state()
        self.statusBar().showMessage(_("Extracting the curve..."))
        worker = TaskWorker(dig.digitize, self._display, self.calibration, self._collect_settings())
        worker.signals.finished.connect(self._on_extracted)
        worker.signals.failed.connect(self._on_extract_failed)
        self._pool.start(worker)

    def _on_extracted(self, result: dig.DigitizerResult) -> None:
        self._busy = False
        self.statusBar().showMessage(
            _("{pixels} curve pixels found, {outliers} outlier(s) removed.").format(pixels=str(len(result.pixels)), outliers=str(result.removed_outliers)), 6000)
        self._set_pixels(result.pixels)

    def _on_extract_failed(self, exc: Exception) -> None:
        self._busy = False
        self.statusBar().clearMessage()
        self._update_state()
        if isinstance(exc, (ValueError, CalibrationError)):
            reporter().warning(self, _("Extraction"), str(exc))
        else:
            reporter().error(self, exc)

    def _remove_outliers(self) -> None:
        if len(self._pixels) < 5:
            return
        keep = dig.remove_outliers(self._pixels[:, 1], threshold=max(0.5, self.outliers.value() or 3.0))
        removed = int((~keep).sum())
        self._set_pixels(self._pixels[keep])
        self.statusBar().showMessage(_("{count} outlier(s) removed.").format(count=str(removed)), 4000)

    def _clear_points(self) -> None:
        self._set_pixels(np.empty((0, 2)))

    def _on_points_edited(self, pixels: np.ndarray) -> None:
        self._pixels = pixels
        self._update_points_from_pixels()

    def _set_pixels(self, pixels: np.ndarray) -> None:
        self._pixels = np.asarray(pixels, dtype=float).reshape(-1, 2)
        self.view.set_points(self._pixels)
        self._update_points_from_pixels()

    def _update_points_from_pixels(self) -> None:
        self._transferred = False
        self._points = []
        if len(self._pixels) and self.calibration.is_ready():
            self._points = dig.pixels_to_thrust_points(self._pixels, self.calibration, self._collect_settings())
        self._plot_preview()
        self._update_state()

    def _plot_preview(self) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        if self._points:
            ax.plot([p.time_s for p in self._points], [p.thrust_n for p in self._points], ".-", markersize=3, color="#1F77B4")
            ax.fill_between([p.time_s for p in self._points], [p.thrust_n for p in self._points], alpha=0.12)
        ax.set_xlabel(_("Time (s)"), fontsize=8)
        ax.set_ylabel(_("Thrust (N)"), fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, linestyle="--", alpha=0.5)
        self.canvas.draw_idle()
        if self._points:
            impulse = total_impulse(self._points)
            peak = max(p.thrust_n for p in self._points)
            self.stats.setText(_("{count} points · total impulse {impulse} N.s · max thrust {peak} N · duration {duration} s").format(count=str(len(self._points)), impulse=f"{impulse:.3f}", peak=f"{peak:.3f}", duration=f"{self._points[-1].time_s:.3f}"))
        else:
            self.stats.setText(_("No digitized point yet."))

    def _update_state(self) -> None:
        has_image = self._display is not None
        self.extract_button.setEnabled(has_image and not self._busy)
        self.transfer_button.setEnabled(bool(self._points))

    # ------------------------------------------------------------------
    # Transfer
    # ------------------------------------------------------------------
    def points(self) -> list[ThrustPoint]:
        """The digitized thrust points."""
        return list(self._points)

    def _transfer(self) -> None:
        if self._points:
            self._transferred = True
            self.points_ready.emit(list(self._points))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._points and not self._transferred and self.isVisible():
            answer = QMessageBox.question(self, _("Close digitizer"),
                                          _("The digitized curve has not been transferred. Close anyway?"))
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
