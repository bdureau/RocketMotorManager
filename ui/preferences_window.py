"""Preferences dialog (persisted as JSON by the ConfigurationManager)."""

from __future__ import annotations

from localization import _, available_languages

import copy
from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QWidget, QVBoxLayout,
)

from application.configuration import Preferences
from models.label_template import PAPER_FORMATS
from models.motor_calculations import BURN_TIME_METHODS
from ui.common import ColorButton


class PreferencesWindow(QDialog):
    """Edit a copy of the preferences; :meth:`result_preferences` returns it."""

    def __init__(self, preferences: Preferences, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Preferences"))
        self.resize(520, 420)
        self._initial_language = preferences.language
        self._prefs = copy.deepcopy(preferences)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), _("General"))
        self.tabs.addTab(self._units_tab(), _("Units"))
        self.tabs.addTab(self._graph_tab(), _("Graph"))
        self.tabs.addTab(self._folders_tab(), _("Folders"))
        self.tabs.addTab(self._printing_tab(), _("Printing"))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setToolTip(_("Reset every preference to its default value."))
        restore.clicked.connect(self._restore_defaults)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self._load(self._prefs)

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.language = QComboBox()
        for code, name in available_languages().items():
            self.language.addItem(name, code)
        self.language.setToolTip(_("Interface language (restart required)."))
        self.theme = QComboBox()
        self.theme.addItem(_("Light"), "light")
        self.theme.addItem(_("Dark"), "dark")
        self.theme.setToolTip(_("Colour theme of the application."))
        form.addRow(_("Language"), self.language)
        form.addRow(_("Theme"), self.theme)
        return tab

    def _units_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.unit_system = QComboBox()
        self.unit_system.addItem(_("Metric (N, N.s, g, mm)"), "metric")
        self.unit_system.addItem(_("Imperial (lbf, lbf.s, oz, in)"), "imperial")
        self.unit_system.setToolTip(_("Units used to display the analysis results and on labels. "
                                            "Data is always stored in SI units (s, N, g, mm)."))
        self.decimal = QComboBox()
        self.decimal.addItem(_("Point (1.5)"), ".")
        self.decimal.addItem(_("Comma (1,5)"), ",")
        self.decimal.setToolTip(_("Default decimal separator for CSV exports. Input fields accept both."))
        self.burn_method = QComboBox()
        for key, caption in BURN_TIME_METHODS.items():
            self.burn_method.addItem(_(caption), key)
        self.burn_method.setToolTip(_("Burn time definition used for the average thrust."))
        form.addRow(_("Unit system"), self.unit_system)
        form.addRow(_("Decimal separator"), self.decimal)
        form.addRow(_("Burn time"), self.burn_method)
        return tab

    def _graph_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.line_color = ColorButton()
        self.line_color.setToolTip(_("Colour of the thrust curve."))
        self.marker_color = ColorButton()
        self.marker_color.setToolTip(_("Colour of the point markers."))
        self.show_grid = QCheckBox(_("Show grid"))
        self.show_markers = QCheckBox(_("Show point markers"))
        self.fill_curve = QCheckBox(_("Fill the area under the curve"))
        form.addRow(_("Curve colour"), self.line_color)
        form.addRow(_("Marker colour"), self.marker_color)
        form.addRow("", self.show_grid)
        form.addRow("", self.show_markers)
        form.addRow("", self.fill_curve)
        return tab

    def _folders_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.save_dir = QLineEdit()
        self.save_dir.setToolTip(_("Default folder proposed when saving projects and exports."))
        self.import_dir = QLineEdit()
        self.import_dir.setToolTip(_("Default folder proposed when importing files."))
        form.addRow(_("Default save folder"), self._folder_row(self.save_dir))
        form.addRow(_("Import folder"), self._folder_row(self.import_dir))
        return tab

    def _folder_row(self, edit: QLineEdit) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton(_("Browse..."))
        browse.clicked.connect(lambda: self._browse(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return widget

    def _printing_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.paper = QComboBox()
        self.paper.addItems(PAPER_FORMATS.keys())
        self.paper.setToolTip(_("Default paper format for label sheets."))
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip(_("Default resolution of PNG/JPEG label exports."))
        form.addRow(_("Paper format"), self.paper)
        form.addRow(_("Image resolution"), self.dpi)
        return tab

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _browse(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, _("Choose a folder"), edit.text())
        if folder:
            edit.setText(folder)

    @staticmethod
    def _select(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index < 0 and isinstance(value, str):
            index = combo.findText(value)
        combo.setCurrentIndex(max(0, index))

    def _load(self, prefs: Preferences) -> None:
        self._select(self.language, prefs.language)
        self._select(self.theme, prefs.theme)
        self._select(self.unit_system, prefs.unit_system)
        self._select(self.decimal, prefs.decimal_separator)
        self._select(self.burn_method, prefs.burn_time_method)
        self.line_color.set_color(prefs.plot_line_color)
        self.marker_color.set_color(prefs.plot_marker_color)
        self.show_grid.setChecked(prefs.show_grid)
        self.show_markers.setChecked(prefs.plot_show_markers)
        self.fill_curve.setChecked(prefs.plot_fill_under_curve)
        self.save_dir.setText(prefs.default_save_dir)
        self.import_dir.setText(prefs.import_dir)
        self._select(self.paper, prefs.print_paper_format)
        self.dpi.setValue(prefs.print_dpi)

    def _restore_defaults(self) -> None:
        defaults = Preferences(recent_files=self._prefs.recent_files, window_geometry=self._prefs.window_geometry,
                               window_state=self._prefs.window_state)
        self._load(defaults)

    def _accept(self) -> None:
        prefs = self._prefs
        prefs.language = self.language.currentData()
        prefs.theme = self.theme.currentData()
        prefs.unit_system = self.unit_system.currentData()
        prefs.decimal_separator = self.decimal.currentData()
        prefs.burn_time_method = self.burn_method.currentData()
        prefs.plot_line_color = self.line_color.color()
        prefs.plot_marker_color = self.marker_color.color()
        prefs.show_grid = self.show_grid.isChecked()
        prefs.plot_show_markers = self.show_markers.isChecked()
        prefs.plot_fill_under_curve = self.fill_curve.isChecked()
        prefs.default_save_dir = self.save_dir.text().strip()
        prefs.import_dir = self.import_dir.text().strip()
        prefs.print_paper_format = self.paper.currentText()
        prefs.print_dpi = self.dpi.value()
        if prefs.language != self._initial_language:
            QMessageBox.information(self, _("Language"), _("The new language will be used after restarting the application."))
        self.accept()

    def result_preferences(self) -> Preferences:
        """The edited preferences."""
        return self._prefs
