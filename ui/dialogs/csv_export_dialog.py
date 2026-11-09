"""Options dialog for the CSV export."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QWidget

from models.units import Quantity, units_for
from services.csv_service import CsvExportOptions


class CsvExportDialog(QDialog):
    """Let the user choose separator, decimal mark, encoding, units, header."""

    def __init__(self, decimal_separator: str = ".", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export CSV - options"))
        form = QFormLayout(self)
        self.separator = QComboBox()
        for text, value in ((self.tr("Comma (,)"), ","), (self.tr("Semicolon (;)"), ";"), (self.tr("Tab"), "\t")):
            self.separator.addItem(text, value)
        self.separator.setToolTip(self.tr("Character separating the two columns."))
        self.decimal = QComboBox()
        self.decimal.addItem(self.tr("Point (1.5)"), ".")
        self.decimal.addItem(self.tr("Comma (1,5)"), ",")
        self.decimal.setToolTip(self.tr("Decimal mark. With a comma, the semicolon separator is selected automatically."))
        self.decimal.setCurrentIndex(self.decimal.findData(decimal_separator))
        self.decimal.currentIndexChanged.connect(self._sync_separator)
        self.encoding = QComboBox()
        self.encoding.addItems(["utf-8", "utf-8-sig", "cp1252", "latin-1"])
        self.encoding.setToolTip(self.tr("Text encoding. 'utf-8-sig' is best for opening in Excel."))
        self.time_unit = QComboBox()
        self.time_unit.addItems(units_for(Quantity.TIME))
        self.time_unit.setToolTip(self.tr("Unit of the exported time column."))
        self.thrust_unit = QComboBox()
        self.thrust_unit.addItems(units_for(Quantity.FORCE))
        self.thrust_unit.setToolTip(self.tr("Unit of the exported thrust column."))
        self.decimals = QSpinBox()
        self.decimals.setRange(1, 10)
        self.decimals.setValue(6)
        self.decimals.setToolTip(self.tr("Maximum number of decimals (trailing zeros are removed)."))
        self.metadata = QCheckBox(self.tr("Include motor properties as '#' header lines"))
        self.metadata.setChecked(True)
        self.metadata.setToolTip(self.tr("Adds commented lines with the motor properties before the data."))
        form.addRow(self.tr("Column separator"), self.separator)
        form.addRow(self.tr("Decimal separator"), self.decimal)
        form.addRow(self.tr("Encoding"), self.encoding)
        form.addRow(self.tr("Time unit"), self.time_unit)
        form.addRow(self.tr("Thrust unit"), self.thrust_unit)
        form.addRow(self.tr("Decimals"), self.decimals)
        form.addRow("", self.metadata)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._sync_separator()

    def _sync_separator(self) -> None:
        if self.decimal.currentData() == "," and self.separator.currentData() == ",":
            self.separator.setCurrentIndex(self.separator.findData(";"))

    def options(self) -> CsvExportOptions:
        """Selected options."""
        return CsvExportOptions(
            separator=self.separator.currentData(), decimal_separator=self.decimal.currentData(),
            encoding=self.encoding.currentText(), time_unit=self.time_unit.currentText(),
            thrust_unit=self.thrust_unit.currentText(), include_metadata=self.metadata.isChecked(),
            max_decimals=self.decimals.value(),
        )
