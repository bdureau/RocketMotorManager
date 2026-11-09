"""Label designer window (independent window)."""

from __future__ import annotations

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
        self.setWindowTitle(self.tr("Label Designer"))
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
            self.template_combo.addItem(f"{name}  (user)" if is_user else name, name)
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
        name, ok = QInputDialog.getText(self, self.tr("Save template"), self.tr("Template name:"), text=self.template.name)
        if not ok or not name.strip():
            return
        self.template.name = name.strip()
        try:
            path = self._service.save_user_template(self.template)
        except RocketMotorError as exc:
            reporter().error(self, exc)
            return
        self._fill_template_combo(self.template.name)
        self.statusBar().showMessage(self.tr("Template saved: %1").replace("%1", str(path)), 5000)

    def _delete_template(self) -> None:
        name = self.template_combo.currentData()
        if not any(t.name == name for t in self._service.user_templates()):
            reporter().info(self, self.tr("Delete template"), self.tr("Predefined templates cannot be deleted."))
            return
        if QMessageBox.question(self, self.tr("Delete template"), self.tr("Delete the template '%1'?").replace("%1", name)) \
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
        for text, value in ((self.tr("Fit"), 0.0), (self.tr("Real size"), 1.0), ("200 %", 2.0), ("400 %", 4.0)):
            self.zoom.addItem(text, value)
        self.zoom.setToolTip(self.tr("Preview zoom. 'Real size' depends on the screen calibration."))
        self.zoom.currentIndexChanged.connect(lambda _i: self.preview.set_zoom(self.zoom.currentData()))
        self.sheet_info = QLabel()
        top = QHBoxLayout()
        top.addWidget(QLabel(self.tr("Zoom")))
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
        toolbar = QToolBar(self.tr("Label"))
        toolbar.setObjectName("label_toolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(default_dpi)
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip(self.tr("Resolution of PNG and JPEG exports."))
        for text, icon_name, slot, shortcut, tip in (
            (self.tr("Store in project"), "save", self._store, None,
             self.tr("Save this label design in the motor project (XML).")),
            (self.tr("Print Preview"), "print", lambda: label_printing.print_preview(self, self.template, self._values()),
             None, self.tr("Preview the label sheet on the selected paper format.")),
            (self.tr("Print..."), "print", lambda: label_printing.print_labels(self, self.template, self._values()),
             QKeySequence.StandardKey.Print, self.tr("Print the label sheet.")),
            (self.tr("Print PDF"), "pdf", lambda: label_printing.export_pdf(self, self.template, self._values(), self._export_folder),
             None, self.tr("Export the label sheet as a PDF file.")),
            (self.tr("Export PNG"), "image",
             lambda: label_printing.export_image(self, self.template, self._values(), "png", self.dpi.value(), self._export_folder),
             None, self.tr("Export one label as a high-resolution PNG image.")),
            (self.tr("Export JPEG"), "image",
             lambda: label_printing.export_image(self, self.template, self._values(), "jpg", self.dpi.value(), self._export_folder),
             None, self.tr("Export one label as a JPEG image.")),
        ):
            action = QAction(icon(icon_name), text, self)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            if shortcut is not None:
                action.setShortcut(shortcut)
            toolbar.addAction(action)
        toolbar.addWidget(QLabel("  " + self.tr("Resolution") + " "))
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
        group = QGroupBox(self.tr("Template"))
        row = QHBoxLayout(group)
        self.template_combo = QComboBox()
        self.template_combo.setToolTip(self.tr("Predefined and user templates."))
        self.template_combo.activated.connect(self._on_template_selected)
        save = QPushButton(icon("save"), "")
        save.setToolTip(self.tr("Save the current design as a reusable template."))
        save.clicked.connect(self._save_template)
        delete = QPushButton(icon("delete_point"), "")
        delete.setToolTip(self.tr("Delete the selected user template."))
        delete.clicked.connect(self._delete_template)
        row.addWidget(self.template_combo, 1)
        row.addWidget(save)
        row.addWidget(delete)
        self._fill_template_combo()
        return group

    def _dimensions_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Dimensions"))
        form = QFormLayout(group)
        self.width_mm = self._spin(10, 300, 1, " mm", self.tr("Label width in millimetres."))
        self.height_mm = self._spin(5, 300, 1, " mm", self.tr("Label height in millimetres."))
        self.inner_margin = self._spin(0, 20, 0.5, " mm", self.tr("Margin between the border and the text."))
        self.border_width = self._spin(0, 5, 0.1, " mm", self.tr("Border thickness (0 = no border)."), 2)
        self.border_radius = self._spin(0, 20, 0.5, " mm", self.tr("Corner radius of the border."))
        form.addRow(self.tr("Width"), self.width_mm)
        form.addRow(self.tr("Height"), self.height_mm)
        form.addRow(self.tr("Inner margin"), self.inner_margin)
        form.addRow(self.tr("Border width"), self.border_width)
        form.addRow(self.tr("Corner radius"), self.border_radius)
        return group

    def _paper_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Paper and sheet"))
        form = QFormLayout(group)
        self.paper = QComboBox()
        self.paper.addItems(PAPER_FORMATS.keys())
        self.paper.setToolTip(self.tr("Paper format used for printing and PDF export."))
        self.paper.currentIndexChanged.connect(self._on_widget_changed)
        self.page_margin = self._spin(0, 50, 1, " mm", self.tr("Margin around the sheet."))
        self.spacing = self._spin(0, 30, 0.5, " mm", self.tr("Space between labels on the sheet."))
        self.copies = QSpinBox()
        self.copies.setRange(1, 500)
        self.copies.setToolTip(self.tr("Number of labels to print."))
        self.copies.valueChanged.connect(self._on_widget_changed)
        self.fill_page = QCheckBox(self.tr("Fill the whole page"))
        self.fill_page.setToolTip(self.tr("Print as many labels as fit on one page."))
        self.fill_page.toggled.connect(self._on_widget_changed)
        form.addRow(self.tr("Paper format"), self.paper)
        form.addRow(self.tr("Page margin"), self.page_margin)
        form.addRow(self.tr("Spacing"), self.spacing)
        form.addRow(self.tr("Copies"), self.copies)
        form.addRow("", self.fill_page)
        return group

    def _style_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Colours and text"))
        form = QFormLayout(group)
        self.colors: dict[str, ColorButton] = {}
        for attribute, caption, tip in (
            ("background_color", "Background", "Background colour of the label."),
            ("text_color", "Text", "Colour of the information lines."),
            ("accent_color", "Accent / title", "Colour of the title (and of the banner)."),
            ("border_color", "Border", "Colour of the border."),
        ):
            button = ColorButton()
            button.setToolTip(self.tr(tip))
            button.color_changed.connect(self._on_widget_changed)
            self.colors[attribute] = button
            form.addRow(self.tr(caption), button)
        self.font_combo = QFontComboBox()
        self.font_combo.setToolTip(self.tr("Font family."))
        self.font_combo.currentFontChanged.connect(self._on_widget_changed)
        self.title_size = self._spin(4, 72, 0.5, " pt", self.tr("Title font size in points."))
        self.body_size = self._spin(3, 48, 0.5, " pt", self.tr("Information font size in points (reduced automatically if the text does not fit)."))
        self.bold_title = QCheckBox(self.tr("Bold title"))
        self.bold_title.toggled.connect(self._on_widget_changed)
        self.alignment = QComboBox()
        for text, value in ((self.tr("Left"), "left"), (self.tr("Centre"), "center"), (self.tr("Right"), "right")):
            self.alignment.addItem(text, value)
        self.alignment.setToolTip(self.tr("Horizontal text alignment."))
        self.alignment.currentIndexChanged.connect(self._on_widget_changed)
        self.layout_combo = QComboBox()
        for value, text in zip(LABEL_LAYOUTS, (self.tr("Stacked lines"), self.tr("Two columns"), self.tr("Banner title"))):
            self.layout_combo.addItem(text, value)
        self.layout_combo.setToolTip(self.tr("Arrangement of the information on the label."))
        self.layout_combo.currentIndexChanged.connect(self._on_widget_changed)
        self.title_field = QComboBox()
        self.title_field.addItem(self.tr("(no title)"), "")
        for name in LABEL_FIELDS:
            self.title_field.addItem(self.tr(LABEL_FIELD_CAPTIONS[name]), name)
        self.title_field.setToolTip(self.tr("Information printed as the large title."))
        self.title_field.currentIndexChanged.connect(self._on_widget_changed)
        self.show_captions = QCheckBox(self.tr("Show captions (e.g. 'Total impulse:')"))
        self.show_captions.toggled.connect(self._on_widget_changed)
        form.addRow(self.tr("Font"), self.font_combo)
        form.addRow(self.tr("Title size"), self.title_size)
        form.addRow(self.tr("Text size"), self.body_size)
        form.addRow("", self.bold_title)
        form.addRow(self.tr("Alignment"), self.alignment)
        form.addRow(self.tr("Layout"), self.layout_combo)
        form.addRow(self.tr("Title"), self.title_field)
        form.addRow("", self.show_captions)
        return group

    def _fields_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Information to display"))
        layout = QVBoxLayout(group)
        self.fields_list = QListWidget()
        self.fields_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.fields_list.setToolTip(self.tr("Tick the information to print. Drag items to change their order."))
        self.fields_list.itemChanged.connect(self._on_widget_changed)
        self.fields_list.model().rowsMoved.connect(self._on_widget_changed)
        self.fields_list.setMinimumHeight(220)
        self.custom_text = QPlainTextEdit()
        self.custom_text.setPlaceholderText(self.tr("Additional free text (one line per row)"))
        self.custom_text.setToolTip(self.tr("Free text zone printed after the information lines."))
        self.custom_text.setFixedHeight(54)
        self.custom_text.textChanged.connect(self._on_widget_changed)
        layout.addWidget(self.fields_list)
        layout.addWidget(self.custom_text)
        return group

    def _logo_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Logo"))
        form = QFormLayout(group)
        row = QHBoxLayout()
        load = QPushButton(icon("image"), self.tr("Import logo..."))
        load.setToolTip(self.tr("Import a PNG or JPG logo."))
        load.clicked.connect(self._choose_logo)
        clear = QPushButton(self.tr("Remove"))
        clear.setToolTip(self.tr("Remove the logo."))
        clear.clicked.connect(self._clear_logo)
        row.addWidget(load)
        row.addWidget(clear)
        self.logo_label = QLabel()
        self.logo_label.setWordWrap(True)
        self.logo_x = self._spin(0, 300, 0.5, " mm", self.tr("Horizontal position of the logo from the left edge."))
        self.logo_y = self._spin(0, 300, 0.5, " mm", self.tr("Vertical position of the logo from the top edge."))
        self.logo_w = self._spin(1, 300, 0.5, " mm", self.tr("Logo box width (aspect ratio is kept)."))
        self.logo_h = self._spin(1, 300, 0.5, " mm", self.tr("Logo box height (aspect ratio is kept)."))
        form.addRow(row)
        form.addRow(self.logo_label)
        form.addRow(self.tr("X"), self.logo_x)
        form.addRow(self.tr("Y"), self.logo_y)
        form.addRow(self.tr("Width"), self.logo_w)
        form.addRow(self.tr("Height"), self.logo_h)
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
            item = QListWidgetItem(self.tr(LABEL_FIELD_CAPTIONS[name]))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if name in t.fields else Qt.CheckState.Unchecked)
            self.fields_list.addItem(item)
        self.custom_text.setPlainText(t.custom_text)
        self.logo_label.setText(Path(t.logo_path).name if t.logo_path else self.tr("No logo"))
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
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Import logo"), "", self.tr("Images (*.png *.jpg *.jpeg)"))
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
            self.sheet_info.setText(self.tr("%1 per %2 page · %3 page(s)").replace("%1", str(layout.per_page))
                                    .replace("%2", self.template.paper_format).replace("%3", str(pages)))
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
        self.statusBar().showMessage(self.tr("Label stored in the project. Save the project to keep it."), 5000)

    def current_template(self) -> LabelTemplate:
        """A copy of the template being edited."""
        return copy.deepcopy(self.template)
