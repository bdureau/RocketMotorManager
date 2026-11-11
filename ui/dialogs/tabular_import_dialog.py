"""Import preview dialog shared by CSV and Excel files.

The user adjusts the reading options (CSV: encoding, separator, decimal
separator, header; Excel: worksheet, header), maps the columns to Time and
Thrust with their units, sees invalid rows highlighted and a preview graph,
then validates. The converted points are available in :attr:`points`.
"""

from __future__ import annotations

from localization import _

import logging
from typing import Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.error_handler import reporter
from models.errors import RocketMotorError, ValidationError
from models.thrust_point import ThrustPoint
from models.units import Quantity, units_for
from services.csv_service import ENCODINGS, SEPARATOR_NAMES, CsvDialect, CsvService
from services.excel_service import ExcelService
from services.tabular_data import ColumnMapping, ConversionResult, TabularData, guess_columns

logger = logging.getLogger(__name__)
PREVIEW_ROWS = 500


class TabularImportDialog(QDialog):
    """Preview, map and validate CSV or Excel data."""

    def __init__(self, path: str, kind: str, csv_service: CsvService, excel_service: ExcelService,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.path = path
        self.kind = kind
        self._csv = csv_service
        self._excel = excel_service
        self._csv_text = ""
        self._table = TabularData()
        self._result: Optional[ConversionResult] = None
        self.points: list[ThrustPoint] = []
        self.setWindowTitle(_("Import {kind} - preview").format(kind="CSV" if kind == "csv" else "Excel"))
        self.resize(960, 640)
        self._build_ui()
        self._initial_load()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        options = QGroupBox(_("Reading options"))
        options_form = QFormLayout(options)
        self.header_check = QCheckBox(_("First row contains column names"))
        self.header_check.setToolTip(_("Tick when the first row holds headers instead of numbers."))
        if self.kind == "csv":
            self.encoding_combo = QComboBox()
            self.encoding_combo.addItems(ENCODINGS)
            self.encoding_combo.setToolTip(_("Text encoding of the file (detected automatically)."))
            self.separator_combo = QComboBox()
            for value, name in SEPARATOR_NAMES.items():
                self.separator_combo.addItem(_(name), value)
            self.separator_combo.setToolTip(_("Character separating the columns (detected automatically)."))
            self.decimal_combo = QComboBox()
            self.decimal_combo.addItem(_("Point (1.5)"), ".")
            self.decimal_combo.addItem(_("Comma (1,5)"), ",")
            self.decimal_combo.setToolTip(_("Decimal separator used in the numbers (detected automatically)."))
            options_form.addRow(_("Encoding"), self.encoding_combo)
            options_form.addRow(_("Column separator"), self.separator_combo)
            options_form.addRow(_("Decimal separator"), self.decimal_combo)
        else:
            self.sheet_combo = QComboBox()
            self.sheet_combo.setToolTip(_("Worksheet containing the thrust data."))
            options_form.addRow(_("Worksheet"), self.sheet_combo)
        options_form.addRow("", self.header_check)

        mapping = QGroupBox(_("Column mapping"))
        mapping_form = QFormLayout(mapping)
        self.time_combo, self.thrust_combo = QComboBox(), QComboBox()
        self.time_combo.setToolTip(_("Column containing the time values."))
        self.thrust_combo.setToolTip(_("Column containing the thrust values."))
        self.time_unit = QComboBox()
        self.time_unit.addItems(units_for(Quantity.TIME))
        self.time_unit.setToolTip(_("Unit of the time column; values are converted to seconds."))
        self.thrust_unit = QComboBox()
        self.thrust_unit.addItems(units_for(Quantity.FORCE))
        self.thrust_unit.setToolTip(_("Unit of the thrust column; values are converted to Newtons."))
        mapping_form.addRow(_("Time column"), self._pair(self.time_combo, self.time_unit))
        mapping_form.addRow(_("Thrust column"), self._pair(self.thrust_combo, self.thrust_unit))
        self.skip_invalid = QCheckBox(_("Remove invalid rows"))
        self.skip_invalid.setChecked(True)
        self.skip_invalid.setToolTip(_("Invalid rows (highlighted in red) are skipped. Untick to refuse the import if any row is invalid."))
        mapping_form.addRow("", self.skip_invalid)

        self.preview_table = QTableWidget()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setToolTip(_("Raw data preview. Rows in red cannot be converted."))
        self.figure = Figure(figsize=(3.5, 2.5), layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumWidth(300)
        self.status = QLabel()
        self.status.setWordWrap(True)

        top = QHBoxLayout()
        top.addWidget(options, 1)
        top.addWidget(mapping, 1)
        middle = QHBoxLayout()
        middle.addWidget(self.preview_table, 3)
        middle.addWidget(self.canvas, 2)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Import"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(middle, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

    @staticmethod
    def _pair(first: QWidget, second: QWidget) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(first, 3)
        row.addWidget(second, 1)
        return widget

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _initial_load(self) -> None:
        try:
            if self.kind == "csv":
                self._csv_text, encoding = self._csv.load_text(self.path)
                dialect = self._csv.detect_dialect(self._csv_text, encoding)
                self._set_dialect_widgets(dialect)
                for combo in (self.encoding_combo, self.separator_combo, self.decimal_combo):
                    combo.currentIndexChanged.connect(self._reload)
            else:
                self.sheet_combo.addItems(self._excel.list_sheets(self.path))
                self.sheet_combo.currentIndexChanged.connect(self._reload)
            self.header_check.toggled.connect(self._reload)
            for widget in (self.time_combo, self.thrust_combo, self.time_unit, self.thrust_unit):
                widget.currentIndexChanged.connect(self._convert)
            self.skip_invalid.toggled.connect(self._convert)
            self._reload(first=True)
        except RocketMotorError as exc:
            self.status.setText(str(exc))
            self.ok_button.setEnabled(False)
            logger.warning("Import preview failed: %s", exc)

    def _set_dialect_widgets(self, dialect: CsvDialect) -> None:
        index = self.encoding_combo.findText(dialect.encoding)
        if index < 0:
            self.encoding_combo.addItem(dialect.encoding)
            index = self.encoding_combo.count() - 1
        self.encoding_combo.setCurrentIndex(index)
        self.separator_combo.setCurrentIndex(max(0, self.separator_combo.findData(dialect.separator)))
        self.decimal_combo.setCurrentIndex(max(0, self.decimal_combo.findData(dialect.decimal_separator)))
        self.header_check.setChecked(dialect.has_header)

    def _reload(self, *_args, first: bool = False) -> None:
        """Re-read the data with the current options."""
        try:
            if self.kind == "csv":
                encoding = self.encoding_combo.currentText()
                if not first:
                    self._csv_text, encoding = self._csv.load_text(self.path, encoding)
                dialect = CsvDialect(self.separator_combo.currentData(), self.decimal_combo.currentData(),
                                     encoding, self.header_check.isChecked())
                self._table = self._csv.parse(self._csv_text, dialect)
            else:
                header = "yes" if self.header_check.isChecked() else "no"
                if first:
                    header = "auto"
                self._table = self._excel.read_sheet(self.path, self.sheet_combo.currentText(), header)
                if first:
                    self.header_check.blockSignals(True)
                    self.header_check.setChecked(bool(self._table.headers))
                    self.header_check.blockSignals(False)
        except (RocketMotorError, LookupError, UnicodeError) as exc:
            self.status.setText(str(exc))
            self._table = TabularData()
        self._fill_columns()
        self._fill_preview()
        self._convert()

    def _fill_columns(self) -> None:
        names = self._table.column_names()
        time_col, thrust_col = guess_columns(self._table)
        for combo, default in ((self.time_combo, time_col), (self.thrust_combo, thrust_col)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.setCurrentIndex(min(default, max(0, len(names) - 1)))
            combo.blockSignals(False)
        header_text = " ".join(names).lower()
        if "(ms)" in header_text or "[ms]" in header_text:
            self.time_unit.setCurrentText("ms")
        for unit in ("lbf", "kgf"):
            if f"({unit})" in header_text or f"[{unit}]" in header_text:
                self.thrust_unit.setCurrentText(unit)

    def _fill_preview(self) -> None:
        table = self._table
        rows = min(len(table.rows), PREVIEW_ROWS)
        self.preview_table.clear()
        self.preview_table.setColumnCount(table.column_count)
        self.preview_table.setRowCount(rows)
        self.preview_table.setHorizontalHeaderLabels(table.column_names())
        for r in range(rows):
            for c in range(table.column_count):
                value = table.cell(r, c)
                self.preview_table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _mapping(self) -> ColumnMapping:
        decimal = self.decimal_combo.currentData() if self.kind == "csv" else "."
        return ColumnMapping(self.time_combo.currentIndex(), self.thrust_combo.currentIndex(),
                             self.time_unit.currentText(), self.thrust_unit.currentText(), decimal)

    def _convert(self, *_args) -> None:
        self._result = None
        self._highlight({})
        if self._table.column_count < 2:
            self.status.setText(_("At least two columns are needed (time and thrust)."))
            self.ok_button.setEnabled(False)
            self._plot([])
            return
        try:
            self._result = self._mapping().convert(self._table, skip_invalid=True)
        except ValidationError as exc:
            self.status.setText(str(exc))
            self.ok_button.setEnabled(False)
            self._plot([])
            return
        invalid = dict(self._result.invalid_rows)
        self._highlight(invalid)
        message = _("{valid} valid point(s), {invalid} invalid row(s).").format(valid=str(len(self._result.points)), invalid=str(len(invalid)))
        if invalid and not self.skip_invalid.isChecked():
            message += " " + _("Tick 'Remove invalid rows' to import the valid points.")
        if any(b.time_s <= a.time_s for a, b in zip(self._result.points, self._result.points[1:])):
            message += " " + _("Warning: times are not strictly increasing (use Sort after import).")
        self.status.setText(message)
        self.ok_button.setEnabled(not invalid or self.skip_invalid.isChecked())
        self._plot(self._result.points)

    def _highlight(self, invalid: dict[int, str]) -> None:
        red = QBrush(QColor("#F8D7DA"))
        for r in range(self.preview_table.rowCount()):
            for c in range(self.preview_table.columnCount()):
                item = self.preview_table.item(r, c)
                if item is None:
                    continue
                item.setBackground(red if r in invalid else QBrush())
                item.setToolTip(invalid.get(r, ""))

    def _plot(self, points: list[ThrustPoint]) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        if points:
            ax.plot([p.time_s for p in points], [p.thrust_n for p in points], ".-", markersize=3)
        ax.set_xlabel(_("Time (s)"), fontsize=8)
        ax.set_ylabel(_("Thrust (N)"), fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, linestyle="--", alpha=0.5)
        self.canvas.draw_idle()

    def _accept(self) -> None:
        if self._result is None:
            return
        if self._result.invalid_rows and not self.skip_invalid.isChecked():
            reporter().warning(self, _("Invalid rows"), _("Some rows are invalid. Tick 'Remove invalid rows' or fix the file."))
            return
        self.points = list(self._result.points)
        self.accept()
