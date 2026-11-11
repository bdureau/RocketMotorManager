"""Import dialog for Richard Nakka SRM workbooks.

Shows what was read from the workbook, lets the user complete the data the
workbook does not contain (casing outside diameter, overall length,
hardware masses, manufacturer, delays) and choose which thrust curve is
imported, with a preview and a cross-check against the workbook results.
"""

from __future__ import annotations

from localization import _, ngettext

from pathlib import Path
from typing import Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.error_handler import reporter
from models.motor import Motor
from models.motor_calculations import MotorCalculator, total_impulse
from models.thrust_point import ThrustPoint
from services.file_utils import format_number
from services.srm_service import CURVE_SOURCE_CAPTIONS, CurveSource, SrmWorkbook
from ui.common import OptionalNumberEdit


class SrmImportDialog(QDialog):
    """Complete and validate the import of an SRM workbook."""

    def __init__(self, workbook: SrmWorkbook, path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.workbook = workbook
        self.path = path
        self.motor: Optional[Motor] = None
        self._curve: list[ThrustPoint] = []
        self.setWindowTitle(_("Import SRM workbook - {name}").format(name=Path(path).name))
        self.resize(1080, 720)
        self._build_ui()
        self._update_curve()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        left = QVBoxLayout()
        left.addWidget(self._source_group())
        left.addWidget(self._motor_group())
        left.addWidget(self._curve_group())
        left.addStretch(1)
        self.figure = Figure(figsize=(5, 3.4), layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setToolTip(_("Grey: full resolution curve of the workbook. Blue: points that will be imported."))
        self.comparison = QTableWidget(0, 3)
        self.comparison.setHorizontalHeaderLabels([_("Characteristic"), _("SRM workbook"), _("Imported curve")])
        self.comparison.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.comparison.verticalHeader().setVisible(False)
        self.comparison.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison.setToolTip(_("Cross-check between the values computed by the SRM workbook and the "
                                           "values recomputed from the imported thrust curve."))
        self.comparison.setMaximumHeight(190)
        self.warnings = QLabel("\n".join("⚠ " + w for w in self.workbook.warnings))
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #B9770E;")
        right = QVBoxLayout()
        right.addWidget(self.canvas, 1)
        right.addWidget(self.comparison)
        right.addWidget(self.warnings)
        columns = QHBoxLayout()
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(460)
        columns.addWidget(left_widget)
        columns.addLayout(right, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Import motor"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(columns, 1)
        layout.addWidget(buttons)

    def _source_group(self) -> QGroupBox:
        wb = self.workbook
        group = QGroupBox(_("Workbook content"))
        form = QFormLayout(group)
        rows = (
            (_("Version"), wb.version),
            (_("Title"), " ".join(p for p in (wb.title, wb.subtitle) if p) or "—"),
            (_("Propellant"), wb.propellant_description() or "—"),
            (_("Grain mass"), f"{format_number(wb.grain_mass_g, 1)} g" if wb.grain_mass_g is not None else "—"),
            (_("Chamber (inside)"), self._dims(wb.chamber_diameter_mm, wb.chamber_length_mm)),
        )
        for caption, value in rows:
            label = QLabel(value)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(caption, label)
        if wb.nozzle_length_mm is not None:
            form.addRow(_("Nozzle length"), QLabel(f"{format_number(wb.nozzle_length_mm, 1)} mm"))
        return group

    @staticmethod
    def _dims(diameter: Optional[float], length: Optional[float]) -> str:
        if diameter is None and length is None:
            return "—"
        return f"Ø {format_number(diameter or 0, 2)} mm × {format_number(length or 0, 1)} mm"

    def _motor_group(self) -> QGroupBox:
        wb = self.workbook
        group = QGroupBox(_("Motor properties to complete"))
        form = QFormLayout(group)
        self.name = QLineEdit(wb.suggested_name())
        self.name.setToolTip(_("Motor code written in the ENG file. Proposed from the class and the average thrust."))
        self.manufacturer = QLineEdit()
        self.manufacturer.setPlaceholderText(_("required for ENG export (e.g. your name or club)"))
        self.manufacturer.setToolTip(_("The SRM workbook does not contain a manufacturer."))
        self.delays = QLineEdit("P")
        self.delays.setToolTip(_("Ejection delays separated by '-'. 'P' = plugged (no ejection charge), usual for "
                                       "amateur motors with electronic deployment."))
        self.diameter = OptionalNumberEdit("mm")
        self.diameter.set_value(wb.chamber_diameter_mm)
        self.diameter.setToolTip(_("Casing OUTSIDE diameter in mm. Pre-filled with the chamber inside diameter of "
                                         "the workbook: add twice the casing wall thickness."))
        self.length = OptionalNumberEdit("mm")
        proposed_length = wb.chamber_length_mm
        if proposed_length is not None and wb.nozzle_length_mm is not None:
            proposed_length += wb.nozzle_length_mm
        self.length.set_value(round(proposed_length, 1) if proposed_length is not None else None)
        self.length.setToolTip(_("Overall motor length in mm. Pre-filled with the chamber length (plus the nozzle "
                                       "length when the workbook gives it)."))
        self.casing_mass = OptionalNumberEdit("g")
        self.casing_mass.setToolTip(_("Empty casing mass in grams (not in the workbook). Needed for the total mass."))
        self.nozzle_mass = OptionalNumberEdit("g")
        self.nozzle_mass.setToolTip(_("Nozzle and closure mass in grams (not in the workbook)."))
        form.addRow(_("Motor name"), self.name)
        form.addRow(_("Manufacturer"), self.manufacturer)
        form.addRow(_("Ejection delays"), self.delays)
        form.addRow(_("Outside diameter (mm)"), self.diameter)
        form.addRow(_("Overall length (mm)"), self.length)
        form.addRow(_("Casing mass (g)"), self.casing_mass)
        form.addRow(_("Nozzle and closure mass (g)"), self.nozzle_mass)
        return group

    def _curve_group(self) -> QGroupBox:
        group = QGroupBox(_("Thrust curve"))
        form = QFormLayout(group)
        self.source = QComboBox()
        for source, caption in CURVE_SOURCE_CAPTIONS.items():
            available = bool(self.workbook.output_curve) if source == CurveSource.OUTPUT_TABLE else bool(self.workbook.performance_curve)
            if available:
                self.source.addItem(_(caption), source)
        self.source.setToolTip(_(
            "Performance sheet: the curve computed by SRM (about 900 points, exact total impulse).\n"
            "Simplified: only the points needed to stay within the tolerance (compact ENG files).\n"
            "Output sheet: the 23-point summary table of the workbook (coarser, impulse slightly lower)."))
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0.01, 10.0)
        self.tolerance.setDecimals(2)
        self.tolerance.setSingleStep(0.1)
        self.tolerance.setValue(0.5)
        self.tolerance.setSuffix(" " + _("% of Fmax"))
        self.tolerance.setToolTip(_("Maximum thrust deviation allowed by the simplification."))
        self.points = QSpinBox()
        self.points.setRange(10, 2000)
        self.points.setValue(100)
        self.points.setToolTip(_("Number of equally spaced points of the resampled curve."))
        form.addRow(_("Source"), self.source)
        form.addRow(_("Simplification"), self.tolerance)
        form.addRow(_("Points"), self.points)
        self.source.currentIndexChanged.connect(self._update_curve)
        self.tolerance.valueChanged.connect(self._update_curve)
        self.points.valueChanged.connect(self._update_curve)
        return group

    # ------------------------------------------------------------------
    # Curve preview and cross-check
    # ------------------------------------------------------------------
    def _update_curve(self) -> None:
        source = self.source.currentData()
        if source is None:
            return
        self.tolerance.setEnabled(source == CurveSource.PERFORMANCE_SIMPLIFIED)
        self.points.setEnabled(source == CurveSource.PERFORMANCE_RESAMPLED)
        self._curve = self.workbook.curve(source, self.tolerance.value() / 100.0, self.points.value())
        self._plot()
        self._fill_comparison()

    def _plot(self) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        reference = self.workbook.performance_curve or self.workbook.output_curve
        ax.plot([p.time_s for p in reference], [p.thrust_n for p in reference], color="#BBBBBB", linewidth=3,
                label=_("Workbook curve"))
        ax.plot([p.time_s for p in self._curve], [p.thrust_n for p in self._curve], "o-", color="#1F77B4",
                markersize=3.5, linewidth=1.2, label=ngettext("Imported ({n} point)", "Imported ({n} points)", len(self._curve)).format(n=len(self._curve)))
        ax.set_xlabel(_("Time (s)"))
        ax.set_ylabel(_("Thrust (N)"))
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(loc="lower center", fontsize=8)
        self.canvas.draw_idle()

    def _fill_comparison(self) -> None:
        summary = self.workbook.summary
        result = MotorCalculator().analyse(Motor(points=self._curve, metadata=self.workbook.to_motor([]).metadata))
        impulse = total_impulse(self._curve) if len(self._curve) >= 2 else None
        rows = [
            (_("Total impulse (N.s)"), summary.total_impulse_ns, impulse, 2),
            (_("Maximum thrust (N)"), summary.maximum_thrust_n, result.maximum_thrust_n, 2),
            (_("Average thrust (N)"), summary.average_thrust_n, result.average_thrust_n, 2),
            (_("Thrust time (s)"), summary.thrust_time_s, result.burn_time_s, 4),
            (_("Specific impulse (s)"), summary.specific_impulse_s, result.specific_impulse_s, 2),
        ]
        self.comparison.setRowCount(len(rows) + 2)
        for index, (caption, srm_value, ours, decimals) in enumerate(rows):
            text = format_number(ours, decimals) if ours is not None else "—"
            if ours is not None and srm_value:
                text += f"   ({(ours - srm_value) / srm_value:+.2%})"
            self._set_row(index, caption, format_number(srm_value, decimals) if srm_value is not None else "—", text)
        self._set_row(len(rows), _("Motor class"), summary.motor_class or "—", result.impulse_class or "—")
        self._set_row(len(rows) + 1, _("Number of points"), str(len(self.workbook.performance_curve)), str(len(self._curve)))

    def _set_row(self, row: int, caption: str, srm_text: str, our_text: str) -> None:
        for column, text in enumerate((caption, srm_text, our_text)):
            self.comparison.setItem(row, column, QTableWidgetItem(text))

    # ------------------------------------------------------------------
    def _accept(self) -> None:
        if len(self._curve) < 2:
            reporter().warning(self, _("SRM import"), _("The selected thrust curve has fewer than two points."))
            return
        self.motor = self.workbook.to_motor(
            self._curve,
            name=self.name.text().strip(),
            manufacturer=self.manufacturer.text().strip(),
            diameter_mm=self.diameter.value(),
            length_mm=self.length.value(),
            delays=self.delays.text().strip() or "0",
            casing_mass_g=self.casing_mass.value(),
            nozzle_mass_g=self.nozzle_mass.value(),
            source_file=self.path,
        )
        self.motor.metadata.extra["srm_curve_source"] = self.source.currentData().value
        self.accept()
