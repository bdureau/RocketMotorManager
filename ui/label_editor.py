"""Label designer window (independent window)."""

from __future__ import annotations

from localization import N_, _

import copy
import logging
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget,
)

from application.application_controller import CHANGE_LABEL, MotorDocument
from application.error_handler import reporter
from models.errors import RocketMotorError
from models.label_template import LABEL_FIELD_CAPTIONS, LABEL_FIELDS, LABEL_LAYOUTS, PAPER_FORMATS, LabelTemplate
from services.label_service import LabelService, find_template, label_values
from ui import label_printing
from ui.common import ColorButton, icon
from widgets.label_preview import LabelPreviewWidget

logger = logging.getLogger(__name__)


class LabelEditorWindow(QMainWindow):
    """Design, save templates, preview, print and export motor labels."""

    template_stored = pyqtSignal(object)

    def __init__(self, document: MotorDocument, unit_system_getter: Callable[[], str], default_dpi: int = 300,
                 export_folder: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Label Designer"))
        self.setWindowIcon(icon("label"))
        self.resize(1200, 760)
        self._document = document
        self._unit_system = unit_system_getter
        self._export_folder = export_folder
        self._service = LabelService()
        self._loading = False
        self.template = copy.deepcopy(document.motor.label) if document.motor.label else self._default_template()
        self._build_ui(default_dpi)
        self._load_template_widgets()
        document.changed.connect(self._on_document_changed)
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    def _default_template(self) -> LabelTemplate:
        builtin = self._service.builtin_templates()
        return copy.deepcopy(find_template(builtin, "Classic") or builtin[0])

    def _all_templates(self) -> list[tuple[str, LabelTemplate, bool]]:
        builtin = [(t.name, t, False) for t in self._service.builtin_templates()]
        user = [(t.name, t, True) for t in self._service.user_templates()]
        return builtin + user

    def _fill_template_combo(self, select: str = "") -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for name, _template, is_user in self._all_templates():
            self.template_combo.addItem(_("{name}  (user)").format(name=name) if is_user else name, name)
        index = self.template_combo.findData(select or self.template.name)
        self.template_combo.setCurrentIndex(index)
        self.template_combo.blockSignals(False)

    def _on_template_selected(self, index: int) -> None:
        if index < 0:
            return
        name = self.template_combo.itemData(index)
        chosen = find_template([t for _n, t, _u in self._all_templates()], name)
        if chosen is not None:
            logo = (self.template.logo_path, self.template.logo_x_mm, self.template.logo_y_mm,
                    self.template.logo_width_mm, self.template.logo_height_mm)
            self.template = copy.deepcopy(chosen)
            if not self.template.logo_path and logo[0]:  # keep the user's logo when switching template
                (self.template.logo_path, self.template.logo_x_mm, self.template.logo_y_mm,
                 self.template.logo_width_mm, self.template.logo_height_mm) = logo
            self._load_template_widgets()
            self._refresh_preview()

    def _save_template(self) -> None:
        name, ok = QInputDialog.getText(self, _("Save template"), _("Template name:"), text=self.template.name)
        if not ok or not name.strip():
            return
        self.template.name = name.strip()
        try:
            path = self._service.save_user_template(self.template)
        except RocketMotorError as exc:
            reporter().error(self, exc)
            return
        self._fill_template_combo(self.template.name)
        self.statusBar().showMessage(_("Template saved: {path}").format(path=str(path)), 5000)

    def _delete_template(self) -> None:
        name = self.template_combo.currentData()
        if not any(t.name == name for t in self._service.user_templates()):
            reporter().info(self, _("Delete template"), _("Predefined templates cannot be deleted."))
            return
        if QMessageBox.question(self, _("Delete template"), _("Delete the template '{name}'?").format(name=name)) \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_user_template(name)
        except RocketMotorError as exc:
            reporter().error(self, exc)
        self._fill_template_combo()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, default_dpi: int) -> None:
        controls = QWidget()
        layout = QVBoxLayout(controls)
        layout.addWidget(self._template_group())
        layout.addWidget(self._dimensions_group())
        layout.addWidget(self._paper_group())
        layout.addWidget(self._style_group())
        layout.addWidget(self._fields_group())
        layout.addWidget(self._logo_group())
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(controls)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(390)
        self.preview = LabelPreviewWidget()
        preview_scroll = QScrollArea()
        preview_scroll.setWidget(self.preview)
        preview_scroll.setWidgetResizable(True)
        self.zoom = QComboBox()
        for text, value in ((_("Fit"), 0.0), (_("Real size"), 1.0), ("200 %", 2.0), ("400 %", 4.0)):
            self.zoom.addItem(text, value)
        self.zoom.setToolTip(_("Preview zoom. 'Real size' depends on the screen calibration."))
        self.zoom.currentIndexChanged.connect(lambda _i: self.preview.set_zoom(self.zoom.currentData()))
        self.sheet_info = QLabel()
        top = QHBoxLayout()
        top.addWidget(QLabel(_("Zoom")))
        top.addWidget(self.zoom)
        top.addStretch(1)
        top.addWidget(self.sheet_info)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addLayout(top)
        right_layout.addWidget(preview_scroll, 1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self._build_toolbar(default_dpi)

    def _build_toolbar(self, default_dpi: int) -> None:
        toolbar = QToolBar(_("Label"))
        toolbar.setObjectName("label_toolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(default_dpi)
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip(_("Resolution of PNG and JPEG exports."))
        for text, icon_name, slot, shortcut, tip in (
            (_("Store in project"), "save", self._store, None,
             _("Save this label design in the motor project (XML).")),
            (_("Print Preview"), "print", lambda: label_printing.print_preview(self, self.template, self._values()),
             None, _("Preview the label sheet on the selected paper format.")),
            (_("Print..."), "print", lambda: label_printing.print_labels(self, self.template, self._values()),
             QKeySequence.StandardKey.Print, _("Print the label sheet.")),
            (_("Print PDF"), "pdf", lambda: label_printing.export_pdf(self, self.template, self._values(), self._export_folder),
             None, _("Export the label sheet as a PDF file.")),
            (_("Export PNG"), "image",
             lambda: label_printing.export_image(self, self.template, self._values(), "png", self.dpi.value(), self._export_folder),
             None, _("Export one label as a high-resolution PNG image.")),
            (_("Export JPEG"), "image",
             lambda: label_printing.export_image(self, self.template, self._values(), "jpg", self.dpi.value(), self._export_folder),
             None, _("Export one label as a JPEG image.")),
        ):
            action = QAction(icon(icon_name), text, self)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            if shortcut is not None:
                action.setShortcut(shortcut)
            toolbar.addAction(action)
        toolbar.addWidget(QLabel("  " + _("Resolution") + " "))
        toolbar.addWidget(self.dpi)

    def _spin(self, minimum: float, maximum: float, step: float, suffix: str, tip: str, decimals: int = 1) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        spin.setToolTip(tip)
        spin.valueChanged.connect(self._on_widget_changed)
        return spin

    def _template_group(self) -> QGroupBox:
        group = QGroupBox(_("Template"))
        row = QHBoxLayout(group)
        self.template_combo = QComboBox()
        self.template_combo.setToolTip(_("Predefined and user templates."))
        self.template_combo.activated.connect(self._on_template_selected)
        save = QPushButton(icon("save"), "")
        save.setToolTip(_("Save the current design as a reusable template."))
        save.clicked.connect(self._save_template)
        delete = QPushButton(icon("delete_point"), "")
        delete.setToolTip(_("Delete the selected user template."))
        delete.clicked.connect(self._delete_template)
        row.addWidget(self.template_combo, 1)
        row.addWidget(save)
        row.addWidget(delete)
        self._fill_template_combo()
        return group

    def _dimensions_group(self) -> QGroupBox:
        group = QGroupBox(_("Dimensions"))
        form = QFormLayout(group)
        self.width_mm = self._spin(10, 300, 1, " mm", _("Label width in millimetres."))
        self.height_mm = self._spin(5, 300, 1, " mm", _("Label height in millimetres."))
        self.inner_margin = self._spin(0, 20, 0.5, " mm", _("Margin between the border and the text."))
        self.border_width = self._spin(0, 5, 0.1, " mm", _("Border thickness (0 = no border)."), 2)
        self.border_radius = self._spin(0, 20, 0.5, " mm", _("Corner radius of the border."))
        form.addRow(_("Width"), self.width_mm)
        form.addRow(_("Height"), self.height_mm)
        form.addRow(_("Inner margin"), self.inner_margin)
        form.addRow(_("Border width"), self.border_width)
        form.addRow(_("Corner radius"), self.border_radius)
        return group

    def _paper_group(self) -> QGroupBox:
        group = QGroupBox(_("Paper and sheet"))
        form = QFormLayout(group)
        self.paper = QComboBox()
        self.paper.addItems(PAPER_FORMATS.keys())
        self.paper.setToolTip(_("Paper format used for printing and PDF export."))
        self.paper.currentIndexChanged.connect(self._on_widget_changed)
        self.page_margin = self._spin(0, 50, 1, " mm", _("Margin around the sheet."))
        self.spacing = self._spin(0, 30, 0.5, " mm", _("Space between labels on the sheet."))
        self.copies = QSpinBox()
        self.copies.setRange(1, 500)
        self.copies.setToolTip(_("Number of labels to print."))
        self.copies.valueChanged.connect(self._on_widget_changed)
        self.fill_page = QCheckBox(_("Fill the whole page"))
        self.fill_page.setToolTip(_("Print as many labels as fit on one page."))
        self.fill_page.toggled.connect(self._on_widget_changed)
        form.addRow(_("Paper format"), self.paper)
        form.addRow(_("Page margin"), self.page_margin)
        form.addRow(_("Spacing"), self.spacing)
        form.addRow(_("Copies"), self.copies)
        form.addRow("", self.fill_page)
        return group

    def _style_group(self) -> QGroupBox:
        group = QGroupBox(_("Colours and text"))
        form = QFormLayout(group)
        self.colors: dict[str, ColorButton] = {}
        for attribute, caption, tip in (
            ("background_color", N_("Background"), N_("Background colour of the label.")),
            ("text_color", N_("Text"), N_("Colour of the information lines.")),
            ("accent_color", N_("Accent / title"), N_("Colour of the title (and of the banner).")),
            ("border_color", N_("Border"), N_("Colour of the border.")),
        ):
            button = ColorButton()
            button.setToolTip(_(tip))
            button.color_changed.connect(self._on_widget_changed)
            self.colors[attribute] = button
            form.addRow(_(caption), button)
        self.font_combo = QFontComboBox()
        self.font_combo.setToolTip(_("Font family."))
        self.font_combo.currentFontChanged.connect(self._on_widget_changed)
        self.title_size = self._spin(4, 72, 0.5, " pt", _("Title font size in points."))
        self.body_size = self._spin(3, 48, 0.5, " pt", _("Information font size in points (reduced automatically if the text does not fit)."))
        self.bold_title = QCheckBox(_("Bold title"))
        self.bold_title.toggled.connect(self._on_widget_changed)
        self.alignment = QComboBox()
        for text, value in ((_("Left"), "left"), (_("Centre"), "center"), (_("Right"), "right")):
            self.alignment.addItem(text, value)
        self.alignment.setToolTip(_("Horizontal text alignment."))
        self.alignment.currentIndexChanged.connect(self._on_widget_changed)
        self.layout_combo = QComboBox()
        for value, text in zip(LABEL_LAYOUTS, (_("Stacked lines"), _("Two columns"), _("Banner title"))):
            self.layout_combo.addItem(text, value)
        self.layout_combo.setToolTip(_("Arrangement of the information on the label."))
        self.layout_combo.currentIndexChanged.connect(self._on_widget_changed)
        self.title_field = QComboBox()
        self.title_field.addItem(_("(no title)"), "")
        for name in LABEL_FIELDS:
            self.title_field.addItem(_(LABEL_FIELD_CAPTIONS[name]), name)
        self.title_field.setToolTip(_("Information printed as the large title."))
        self.title_field.currentIndexChanged.connect(self._on_widget_changed)
        self.show_captions = QCheckBox(_("Show captions (e.g. 'Total impulse:')"))
        self.show_captions.toggled.connect(self._on_widget_changed)
        form.addRow(_("Font"), self.font_combo)
        form.addRow(_("Title size"), self.title_size)
        form.addRow(_("Text size"), self.body_size)
        form.addRow("", self.bold_title)
        form.addRow(_("Alignment"), self.alignment)
        form.addRow(_("Layout"), self.layout_combo)
        form.addRow(_("Title"), self.title_field)
        form.addRow("", self.show_captions)
        return group

    def _fields_group(self) -> QGroupBox:
        group = QGroupBox(_("Information to display"))
        layout = QVBoxLayout(group)
        self.fields_list = QListWidget()
        self.fields_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.fields_list.setToolTip(_("Tick the information to print. Drag items to change their order."))
        self.fields_list.itemChanged.connect(self._on_widget_changed)
        self.fields_list.model().rowsMoved.connect(self._on_widget_changed)
        self.fields_list.setMinimumHeight(220)
        self.custom_text = QPlainTextEdit()
        self.custom_text.setPlaceholderText(_("Additional free text (one line per row)"))
        self.custom_text.setToolTip(_("Free text zone printed after the information lines."))
        self.custom_text.setFixedHeight(54)
        self.custom_text.textChanged.connect(self._on_widget_changed)
        layout.addWidget(self.fields_list)
        layout.addWidget(self.custom_text)
        return group

    def _logo_group(self) -> QGroupBox:
        group = QGroupBox(_("Logo"))
        form = QFormLayout(group)
        row = QHBoxLayout()
        load = QPushButton(icon("image"), _("Import logo..."))
        load.setToolTip(_("Import a PNG or JPG logo."))
        load.clicked.connect(self._choose_logo)
        clear = QPushButton(_("Remove"))
        clear.setToolTip(_("Remove the logo."))
        clear.clicked.connect(self._clear_logo)
        row.addWidget(load)
        row.addWidget(clear)
        self.logo_label = QLabel()
        self.logo_label.setWordWrap(True)
        self.logo_x = self._spin(0, 300, 0.5, " mm", _("Horizontal position of the logo from the left edge."))
        self.logo_y = self._spin(0, 300, 0.5, " mm", _("Vertical position of the logo from the top edge."))
        self.logo_w = self._spin(1, 300, 0.5, " mm", _("Logo box width (aspect ratio is kept)."))
        self.logo_h = self._spin(1, 300, 0.5, " mm", _("Logo box height (aspect ratio is kept)."))
        form.addRow(row)
        form.addRow(self.logo_label)
        form.addRow(_("X"), self.logo_x)
        form.addRow(_("Y"), self.logo_y)
        form.addRow(_("Width"), self.logo_w)
        form.addRow(_("Height"), self.logo_h)
        return group

    # ------------------------------------------------------------------
    # Widgets <-> template
    # ------------------------------------------------------------------
    def _load_template_widgets(self) -> None:
        self._loading = True
        t = self.template
        for spin, value in ((self.width_mm, t.width_mm), (self.height_mm, t.height_mm),
                            (self.inner_margin, t.inner_margin_mm), (self.border_width, t.border_width_mm),
                            (self.border_radius, t.border_radius_mm), (self.page_margin, t.page_margin_mm),
                            (self.spacing, t.label_spacing_mm), (self.title_size, t.title_font_size),
                            (self.body_size, t.body_font_size), (self.logo_x, t.logo_x_mm), (self.logo_y, t.logo_y_mm),
                            (self.logo_w, t.logo_width_mm), (self.logo_h, t.logo_height_mm)):
            spin.setValue(value)
        self.paper.setCurrentText(t.paper_format)
        self.copies.setValue(t.copies)
        self.fill_page.setChecked(t.fill_page)
        for attribute, button in self.colors.items():
            button.set_color(getattr(t, attribute))
        self.font_combo.setCurrentFont(QFont(t.font_family))
        self.bold_title.setChecked(t.bold_title)
        self.alignment.setCurrentIndex(max(0, self.alignment.findData(t.alignment)))
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(t.layout)))
        self.title_field.setCurrentIndex(max(0, self.title_field.findData(t.title_field)))
        self.show_captions.setChecked(t.show_captions)
        self.fields_list.clear()
        ordered = list(t.fields) + [name for name in LABEL_FIELDS if name not in t.fields]
        for name in ordered:
            item = QListWidgetItem(_(LABEL_FIELD_CAPTIONS[name]))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if name in t.fields else Qt.CheckState.Unchecked)
            self.fields_list.addItem(item)
        self.custom_text.setPlainText(t.custom_text)
        self.logo_label.setText(Path(t.logo_path).name if t.logo_path else _("No logo"))
        self._loading = False

    def _on_widget_changed(self, *_args) -> None:
        if self._loading:
            return
        t = self.template
        t.width_mm, t.height_mm = self.width_mm.value(), self.height_mm.value()
        t.inner_margin_mm, t.border_width_mm = self.inner_margin.value(), self.border_width.value()
        t.border_radius_mm = self.border_radius.value()
        t.paper_format = self.paper.currentText()
        t.page_margin_mm, t.label_spacing_mm = self.page_margin.value(), self.spacing.value()
        t.copies, t.fill_page = self.copies.value(), self.fill_page.isChecked()
        for attribute, button in self.colors.items():
            setattr(t, attribute, button.color())
        t.font_family = self.font_combo.currentFont().family()
        t.title_font_size, t.body_font_size = self.title_size.value(), self.body_size.value()
        t.bold_title = self.bold_title.isChecked()
        t.alignment = self.alignment.currentData()
        t.layout = self.layout_combo.currentData()
        t.title_field = self.title_field.currentData()
        t.show_captions = self.show_captions.isChecked()
        t.fields = [self.fields_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.fields_list.count())
                    if self.fields_list.item(i).checkState() == Qt.CheckState.Checked]
        t.custom_text = self.custom_text.toPlainText()
        t.logo_x_mm, t.logo_y_mm = self.logo_x.value(), self.logo_y.value()
        t.logo_width_mm, t.logo_height_mm = self.logo_w.value(), self.logo_h.value()
        self._refresh_preview()

    def _choose_logo(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(self, _("Import logo"), "", _("Images (*.png *.jpg *.jpeg)"))
        if not path:
            return
        self.template.logo_path = path
        if self.template.logo_x_mm + self.template.logo_width_mm > self.template.width_mm:
            self.template.logo_width_mm = self.template.logo_height_mm = min(17.0, self.template.height_mm - 4)
            self.template.logo_x_mm = self.template.width_mm - self.template.logo_width_mm - 3
            self.template.logo_y_mm = (self.template.height_mm - self.template.logo_height_mm) / 2
        self._load_template_widgets()
        self._refresh_preview()

    def _clear_logo(self) -> None:
        self.template.logo_path = ""
        self._load_template_widgets()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _values(self) -> dict[str, str]:
        return label_values(self._document.motor, self._document.characteristics(), self._unit_system())

    def _refresh_preview(self) -> None:
        self.preview.set_content(self.template, self._values())
        self.preview.set_zoom(self.zoom.currentData())
        try:
            layout = self._service.sheet_layout(self.template)
            pages = -(-self._service.label_count(self.template) // layout.per_page)
            self.sheet_info.setText(_("{per_page} per {paper} page · {pages} page(s)").format(per_page=str(layout.per_page), paper=self.template.paper_format, pages=str(pages)))
            self.sheet_info.setStyleSheet("")
        except RocketMotorError as exc:
            self.sheet_info.setText(str(exc))
            self.sheet_info.setStyleSheet("color: #C0392B;")

    def _on_document_changed(self, kind: str) -> None:
        if kind == CHANGE_LABEL and self._document.motor.label is not None:
            if self._document.motor.label != self.template:
                self.template = copy.deepcopy(self._document.motor.label)
                self._load_template_widgets()
        self._refresh_preview()

    def _store(self) -> None:
        self.template_stored.emit(copy.deepcopy(self.template))
        self.statusBar().showMessage(_("Label stored in the project. Save the project to keep it."), 5000)

    def current_template(self) -> LabelTemplate:
        """A copy of the template being edited."""
        return copy.deepcopy(self.template)
