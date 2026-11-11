"""Options dialog for the CSV export."""

from __future__ import annotations

from localization import _

from typing import Optional

from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QWidget

from models.units import Quantity, units_for
from services.csv_service import CsvExportOptions


class CsvExportDialog(QDialog):
    """Let the user choose separator, decimal mark, encoding, units, header."""

    def __init__(self, decimal_separator: str = ".", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Export CSV - options"))
        form = QFormLayout(self)
        self.separator = QComboBox()
        for text, value in ((_("Comma (,)"), ","), (_("Semicolon (;)"), ";"), (_("Tab"), "\t")):
            self.separator.addItem(text, value)
        self.separator.setToolTip(_("Character separating the two columns."))
        self.decimal = QComboBox()
        self.decimal.addItem(_("Point (1.5)"), ".")
        self.decimal.addItem(_("Comma (1,5)"), ",")
        self.decimal.setToolTip(_("Decimal mark. With a comma, the semicolon separator is selected automatically."))
        self.decimal.setCurrentIndex(self.decimal.findData(decimal_separator))
        self.decimal.currentIndexChanged.connect(self._sync_separator)
        self.encoding = QComboBox()
        self.encoding.addItems(["utf-8", "utf-8-sig", "cp1252", "latin-1"])
        self.encoding.setToolTip(_("Text encoding. 'utf-8-sig' is best for opening in Excel."))
        self.time_unit = QComboBox()
        self.time_unit.addItems(units_for(Quantity.TIME))
        self.time_unit.setToolTip(_("Unit of the exported time column."))
        self.thrust_unit = QComboBox()
        self.thrust_unit.addItems(units_for(Quantity.FORCE))
        self.thrust_unit.setToolTip(_("Unit of the exported thrust column."))
        self.decimals = QSpinBox()
        self.decimals.setRange(1, 10)
        self.decimals.setValue(6)
        self.decimals.setToolTip(_("Maximum number of decimals (trailing zeros are removed)."))
        self.metadata = QCheckBox(_("Include motor properties as '#' header lines"))
        self.metadata.setChecked(True)
        self.metadata.setToolTip(_("Adds commented lines with the motor properties before the data."))
        form.addRow(_("Column separator"), self.separator)
        form.addRow(_("Decimal separator"), self.decimal)
        form.addRow(_("Encoding"), self.encoding)
        form.addRow(_("Time unit"), self.time_unit)
        form.addRow(_("Thrust unit"), self.thrust_unit)
        form.addRow(_("Decimals"), self.decimals)
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
