"""Generate the PDF user manuals (documentation/user_manual_<lang>.pdf) with ReportLab.

Run from the project root::

    python tools/generate_manual.py            # every language
    python tools/generate_manual.py fr de      # selected languages

The manual texts are marked with ``_()`` and translated with the gettext
catalogue ``documentation/locale/<lang>/LC_MESSAGES/manual.mo`` (managed by
``tools/build_translations.py``). Interface references written
``[[&File|&New Motor]]`` are replaced by the captions of the application
catalogue, so the manual always uses the exact words of the translated
interface ("Fichier > Nouveau moteur" in French).

Screenshots are taken from ``documentation/screenshots/<lang>/`` (run
``python tools/capture_screenshots.py --lang all`` first), with the English
ones as fallback. The DejaVu Sans fonts of ``documentation/fonts`` cover
Latin, Polish and Cyrillic characters.
"""

from __future__ import annotations

import argparse
import gettext
import re
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.fonts import addMapping  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

import localization  # noqa: E402
from application.version import APP_AUTHOR, APP_COPYRIGHT, APP_NAME, APP_VERSION  # noqa: E402

DOCUMENTATION = ROOT / "documentation"
SHOTS = DOCUMENTATION / "screenshots"
FONTS = DOCUMENTATION / "fonts"
MANUAL_LOCALE = DOCUMENTATION / "locale"
MANUAL_DOMAIN = "manual"
ACCENT = colors.HexColor("#1F4E79")
UI_REFERENCE = re.compile(r"\[\[(.+?)\]\]")


def manual_path(language: str) -> Path:
    """Path of the PDF manual of a language."""
    return DOCUMENTATION / f"user_manual_{language}.pdf"


# --------------------------------------------------------------- translation
_translation: gettext.NullTranslations = gettext.NullTranslations()
_language = "en"


def _(message: str) -> str:
    """Translate a manual text into the language being generated."""
    return _translation.gettext(message)


def set_language(language: str) -> None:
    """Select the manual catalogue and the application catalogue of a language."""
    global _translation, _language
    _language = language
    _translation = gettext.translation(MANUAL_DOMAIN, str(MANUAL_LOCALE), languages=[language], fallback=True)
    localization.install(language)


def ui_caption(msgid: str) -> str:
    """Caption of an interface element as displayed by the application:
    translated with the application catalogue, without the '&' mnemonic and
    the trailing ellipsis."""
    text = localization._(msgid).replace("&&", "\0").replace("&", "").replace("\0", "&")
    return text[:-3] if text.endswith("...") else text.rstrip("…")


def resolve_ui_references(text: str) -> str:
    """Replace ``[[a|b]]`` by the translated captions 'a > b'."""
    return UI_REFERENCE.sub(lambda m: " &gt; ".join(escape(ui_caption(part)) for part in m.group(1).split("|")), text)


# --------------------------------------------------------------------- fonts
def register_fonts() -> tuple[str, str]:
    """Register DejaVu Sans (regular/bold/italic) and DejaVu Sans Mono.
    Return the (body, mono) font names; Helvetica/Courier if unavailable."""
    files = {"DejaVuSans": "DejaVuSans.ttf", "DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
             "DejaVuSans-Oblique": "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique": "DejaVuSans-BoldOblique.ttf",
             "DejaVuSansMono": "DejaVuSansMono.ttf"}
    if not all((FONTS / f).exists() for f in files.values()):
        print("warning: DejaVu fonts not found in", FONTS, "- Cyrillic and Polish characters will be missing")
        return "Helvetica", "Courier"
    for name, filename in files.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONTS / filename)))
    for bold, italic, name in ((0, 0, "DejaVuSans"), (1, 0, "DejaVuSans-Bold"), (0, 1, "DejaVuSans-Oblique"),
                               (1, 1, "DejaVuSans-BoldOblique")):
        addMapping("DejaVuSans", bold, italic, name)
    for bold in (0, 1):
        for italic in (0, 1):
            addMapping("DejaVuSansMono", bold, italic, "DejaVuSansMono")
    return "DejaVuSans", "DejaVuSansMono"


FONT, MONO = register_fonts()
BOLD = "DejaVuSans-Bold" if FONT == "DejaVuSans" else "Helvetica-Bold"

H1 = ParagraphStyle("H1", fontName=BOLD, textColor=ACCENT, fontSize=18, leading=22, spaceBefore=6, spaceAfter=10)
H2 = ParagraphStyle("H2", fontName=BOLD, textColor=ACCENT, fontSize=13, leading=16, spaceBefore=10, spaceAfter=6)
BODY = ParagraphStyle("Body", fontName=FONT, fontSize=9.5, leading=13.5, spaceAfter=6)
NOTE = ParagraphStyle("Note", parent=BODY, backColor=colors.HexColor("#EAF2FB"), borderColor=ACCENT, borderWidth=0.5,
                      borderPadding=6, spaceBefore=6, spaceAfter=10)
CAPTION = ParagraphStyle("Caption", parent=BODY, fontSize=8.5, textColor=colors.grey, alignment=TA_CENTER)
CODE = ParagraphStyle("Code", parent=BODY, fontName=MONO, fontSize=8.5, leading=11, backColor=colors.HexColor("#F4F4F4"),
                      borderPadding=5, spaceBefore=4, spaceAfter=8)
TABLE_HEADER = ParagraphStyle("th", parent=BODY, textColor=colors.white, fontName=BOLD)


# ------------------------------------------------------------ building blocks
class ManualTemplate(SimpleDocTemplate):
    """Document template registering H1/H2 headings in the table of contents."""

    def afterFlowable(self, flowable) -> None:  # noqa: N802 - ReportLab hook
        if isinstance(flowable, Paragraph) and flowable.style.name in ("H1", "H2"):
            level = 0 if flowable.style.name == "H1" else 1
            text = flowable.getPlainText()
            key = f"h{id(flowable)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
            self.notify("TOCEntry", (level, text, self.page, key))


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    """Paragraph with the interface references resolved."""
    return Paragraph(resolve_ui_references(text), style)


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(p(item), leftIndent=12) for item in items], bulletType="bullet", start="•",
                        leftIndent=14, bulletFontName=FONT)


def steps(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(p(item), leftIndent=12) for item in items], bulletType="1", leftIndent=16,
                        bulletFontName=FONT)


def table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[p(cell, TABLE_HEADER) for cell in rows[0]]] + [[p(cell) for cell in row] for row in rows[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B7C3")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")]),
    ]))
    return t


def screenshot_path(name: str, language: str) -> Path | None:
    """Screenshot of the language, else the English one, else None."""
    for candidate in (SHOTS / language / f"{name}.png", SHOTS / "en" / f"{name}.png"):
        if candidate.exists():
            return candidate
    return None


def screenshot(name: str, caption: str, width: float = 16 * cm) -> list:
    path = screenshot_path(name, _language)
    if path is None:
        return [p(f"<i>[{escape(name)}.png - tools/capture_screenshots.py]</i>", CAPTION)]
    image = Image(str(path))
    ratio = image.imageHeight / image.imageWidth
    height = width * ratio
    if height > 15 * cm:
        height, width = 15 * cm, 15 * cm / ratio
    image.drawWidth, image.drawHeight = width, height
    return [KeepTogether([image, p(caption, CAPTION)]), Spacer(1, 6)]


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2 * cm, 1.2 * cm, f"{APP_NAME} {APP_VERSION} - {_('User manual')}")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, _("Page {number}").format(number=doc.page))
    canvas.setStrokeColor(ACCENT)
    canvas.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
    canvas.restoreState()


def month_year(day: date, language: str) -> str:
    """'November 2026' in the language (stand-alone month name)."""
    try:
        from babel.dates import format_date

        text = format_date(day, "LLLL yyyy", locale=language)
        return text[:1].upper() + text[1:]
    except ImportError:  # Babel is a development dependency
        return f"{day:%m/%Y}"


# ------------------------------------------------------------------- content
def cover() -> list:
    story = [Spacer(1, 4 * cm)]
    icon = ROOT / "resources" / "icons" / "app.png"
    if icon.exists():
        story.append(Image(str(icon), 4.5 * cm, 4.5 * cm))
    story += [
        Spacer(1, 1 * cm),
        p(f"<para alignment='center'><font size=28 color='#1F4E79'><b>{APP_NAME}</b></font></para>", BODY),
        Spacer(1, 0.8 * cm),
        p(f"<para alignment='center'><font size=14>{_('User manual')}</font></para>"),
        Spacer(1, 0.4 * cm),
        p("<para alignment='center'>{}</para>".format(
            _("Version {version} - {date}").format(version=APP_VERSION, date=month_year(date.today(), _language)))),
        Spacer(1, 6 * cm),
        p(f"<para alignment='center'>{APP_AUTHOR}<br/>{APP_COPYRIGHT}</para>"),
        PageBreak(),
    ]
    return story


def contents() -> list:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc1", fontName=BOLD, fontSize=11, leading=14, leftIndent=10, firstLineIndent=-10, spaceBefore=4),
        ParagraphStyle("toc2", fontName=FONT, fontSize=9.5, leading=12, leftIndent=28, firstLineIndent=-10),
    ]
    return [p(_("Contents"), ParagraphStyle("TOCTitle", parent=H1)), toc, PageBreak()]


def chapters() -> list:
    s: list = []
    # 1 -----------------------------------------------------------------
    s += [p(_("1. General presentation"), H1),
          p(_("{app} is a desktop application to create, import, edit, convert, analyse, visualise and archive "
              "rocket motor thrust data. It reads and writes the standard RASP <b>.eng</b> format used by OpenRocket and "
              "RockSim, imports CSV and Excel files, digitizes thrust curves from photographs or scans, computes the motor "
              "characteristics and prints custom motor labels.").format(app=APP_NAME)),
          p(_("Main features"), H2),
          bullets([_("Motor properties editor (identity, dimensions, masses with automatic total mass)."),
                   _("Interactive thrust curve: zoom, pan, cursor read-out, graphical point editing, PNG/SVG/PDF export."),
                   _("Synchronised data table: add, edit, duplicate, delete, sort, paste from Excel, unlimited undo/redo."),
                   _("Import ENG (several motors per file), CSV (automatic separator/decimal/encoding detection), Excel "
                     "(.xlsx, .xls) and Richard Nakka SRM workbooks."),
                   _("Curve digitizer: image corrections, multi-point axis calibration, colour extraction, outlier removal, "
                     "manual correction."),
                   _("Analysis: total impulse, average/maximum thrust, burn time, specific impulse, impulse class."),
                   _("Strict ENG export with validation; native versioned XML project keeping every piece of information."),
                   _("Label designer with templates, logo, print preview, PDF, PNG and JPEG export at physical size."),
                   _("Interface and manual in English, French, German, Spanish, Italian, Dutch, Polish, Portuguese and Russian.")]),
          p(_("Data principles"), H2),
          bullets([_("Internal units are fixed and explicit: seconds, Newtons, Newton-seconds, grams and millimetres."),
                   _("Original data is never altered silently: sorting, resampling or replacing points are explicit and undoable."),
                   _("Information that the ENG format cannot hold (component masses, descriptions, label...) is kept in the XML project."),
                   _("Every save is atomic: an interrupted save never corrupts an existing file.")])]
    # 2 -----------------------------------------------------------------
    s += [p(_("2. Installation"), H1),
          p(_("Standalone executable (recommended)"), H2),
          p(_("Copy the <b>RocketMotorManager</b> folder produced by the build (or the installer output) anywhere on the "
              "computer and run <b>RocketMotorManager.exe</b>. No Python installation is required.")),
          p(_("From the source code"), H2),
          steps([_("Install Python 3.10 or later (64-bit) from python.org, ticking <i>Add Python to PATH</i>."),
                 _("Double-click <b>install.bat</b>: it creates a virtual environment (<i>.venv</i>) and installs the dependencies."),
                 _("Double-click <b>run.bat</b> to start the application."),
                 _("Optional: run <b>build_exe.bat</b> to produce the standalone executable in <i>dist\\RocketMotorManager</i>.")]),
          p(_("Files and folders used by the application"), H2),
          table([[_("Item"), _("Location (Windows)")],
                 [_("Preferences"), "%APPDATA%\\RocketMotorManager\\preferences.json"],
                 [_("User label templates"), "%APPDATA%\\RocketMotorManager\\label_templates\\"],
                 [_("Technical log"), "%LOCALAPPDATA%\\RocketMotorManager\\logs\\rocket_motor_manager.log"]],
                [5 * cm, 11 * cm])]
    # 3 -----------------------------------------------------------------
    s += [p(_("3. The user interface"), H1),
          *screenshot("main_window", _("Figure 1 - Main window: motor properties (left), thrust curve (centre), data table (right).")),
          p(_("The main window is divided into three zones:")),
          bullets([_("<b>[[Motor properties]]</b> (left dock): identification, dimensions, masses, description and a summary "
                     "of the computed characteristics. The dock can be moved, floated or hidden (menu <b>[[&View]]</b>)."),
                   _("<b>[[Thrust curve]]</b> (centre): time (s) on X, thrust (N) on Y. The dotted green line shows the "
                     "average thrust over the burn window; the box in the corner summarises impulse, average thrust and burn time."),
                   _("<b>Data table</b> (right): the points of the curve. Rows in red contain errors, rows in yellow warnings.")]),
          p(_("The toolbar gives access to the most used commands (new, open, save, import, export, undo/redo, add and "
              "delete points, analysis, digitizer, labels). The status bar shows the file path, the number of points, the "
              "total impulse with its class and the cursor coordinates. Every field and button has a tooltip explaining "
              "its meaning, unit and constraints.")),
          p(_("Keyboard shortcuts"), H2),
          table([[_("Action"), _("Shortcut")],
                 [_("New / Open / Save / Save As"), "Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S"],
                 [_("Undo / Redo"), "Ctrl+Z / Ctrl+Y"],
                 [_("Import ENG / Export ENG"), "Ctrl+E / Ctrl+Shift+E"],
                 [_("Add point / Delete point(s)"), _("Ctrl+Ins / Del (table) or Ctrl+Del")],
                 [_("Duplicate point"), _("Ctrl+D (table)")],
                 [_("Copy / Paste points"), _("Ctrl+C / Ctrl+V (table)")],
                 [_("Reset zoom / Toggle grid"), "Ctrl+0 / Ctrl+G"],
                 [_("Analysis / Digitizer / Labels / Validation"), "F5 / F6 / F7 / F8"],
                 [_("Print labels to PDF"), "Ctrl+P"],
                 [_("Manual"), "F1"]], [8 * cm, 8 * cm]),
          p(_("Files can also be dropped on the main window: .rmm.xml and .eng files are opened, CSV/Excel files are "
              "imported and images open the digitizer."), NOTE)]
    # 4 -----------------------------------------------------------------
    s += [p(_("4. Creating a motor"), H1),
          steps([_("Choose <b>[[&File|&New Motor]]</b> (Ctrl+N)."),
                 _("Fill in the <b>[[Motor name]]</b> (short code written in ENG files, e.g. <i>C6</i>), the "
                   "<b>[[Manufacturer]]</b> and the <b>[[Motor designation]]</b> (e.g. <i>C6-5</i>)."),
                 _("Enter the <b>[[Ejection delays]]</b> separated by dashes (e.g. <i>3-5-7</i>); use <i>P</i> for a "
                   "plugged motor and <i>0</i> for none."),
                 _("Enter the diameter and length in millimetres and the masses in grams. Decimal point or comma are both accepted."),
                 _("Enter the thrust points in the table (see chapter 8), import them or digitize a graph."),
                 _("Save the project with <b>[[&File|&Save Motor]]</b>.")]),
          p(_("Total motor mass"), H2),
          p(_("When the casing mass or the nozzle and closure mass is entered, the total motor mass is computed "
              "automatically (propellant + casing + nozzle/closure) and the field becomes read-only. Otherwise the total "
              "mass can be entered directly (this is the case after an ENG import, which only provides the total and "
              "propellant masses).")),
          p(_("Every change can be undone with Ctrl+Z. The window title shows an asterisk when changes are not saved; the "
              "application always asks before closing or opening another motor."), NOTE)]
    # 5 -----------------------------------------------------------------
    s += [p(_("5. Importing an ENG file"), H1),
          p(_("Choose <b>[[&File|Import &ENG...]]</b> (Ctrl+E). The header (name, diameter, length, delays, propellant "
              "mass, total mass, manufacturer), the comments and every thrust point are read. If the file contains several "
              "motors, a list lets you choose one. The motor opens as a new unsaved document.")),
          p(_("Example of ENG file"), H2),
          p(_("; comment lines start with a semicolon") + "<br/>C6 18 70 0-3-5-7 0.0108 0.0231 Estes<br/>"
            "&nbsp;&nbsp;&nbsp;0.031 0.946<br/>&nbsp;&nbsp;&nbsp;0.092 4.826<br/>&nbsp;&nbsp;&nbsp;...<br/>"
            "&nbsp;&nbsp;&nbsp;1.860 0.000", CODE),
          p(_("When a file is invalid the message gives the exact line number and content (for example "
              "<i>Line 5: Non-numeric thrust data -&gt; \"0.089 abc\"</i>). Non-blocking problems (curve not ending at "
              "zero, non-chronological points) are reported as warnings after the import."))]
    # 6 -----------------------------------------------------------------
    s += [p(_("6. Importing CSV and Excel files"), H1),
          *screenshot("csv_import", _("Figure 2 - CSV import preview with column mapping, units and invalid row highlighting."), 15 * cm),
          p(_("<b>[[&File|Import &CSV...]]</b> opens a preview. The encoding, column separator, decimal separator and "
              "header row are detected automatically and can be changed. <b>[[&File|Import Exce&l...]]</b> works the same "
              "way for .xlsx and .xls workbooks, with a choice of worksheet.")),
          steps([_("Select the <b>[[Time column]]</b> and its unit (s or ms)."),
                 _("Select the <b>[[Thrust column]]</b> and its unit (N, lbf or kgf). Values are converted to seconds and Newtons."),
                 _("Check the preview graph. Invalid rows (missing or non-numeric values, negative times) are highlighted "
                   "in red; their tooltip gives the reason."),
                 _("Keep <b>[[Remove invalid rows]]</b> ticked to import only the valid points, then click <b>[[Import]]</b>.")]),
          p(_("The imported points replace the thrust curve of the current motor after confirmation; the operation can be "
              "undone with Ctrl+Z.")),
          p(_("Richard Nakka SRM workbooks"), H2),
          *screenshot("srm_import", _("Figure 3 - Import of an SRM workbook with curve choice and cross-check."), 15 * cm),
          p(_("The SRM design spreadsheets of Richard Nakka (SRM 1.x and SRM 2023, .xls or .xlsx) are not plain tables: "
              "<b>[[&File|Import &SRM Workbook (Nakka)...]]</b> reads each piece of information in its own sheet. Opening "
              "such a workbook with the Excel import or by drag and drop is detected automatically and the SRM import is "
              "proposed.")),
          table([[_("Sheet"), _("Information imported")],
                 ["Data and Kn", _("Title, propellant (KNDX, KNSB, KNSU, KNER...), chamber inside diameter and length, "
                                   "grain geometry and mass, Kn, throat diameter")],
                 ["Output", _("SRM results (total impulse, average thrust, thrust time, Isp, class) and the 23-point table")],
                 ["Performance", _("Full resolution thrust curve (about 880 points) and maximum thrust")],
                 ["Pressure / Nozzle Design", _("Maximum chamber pressure, burn time, nozzle length (informative)")]],
                [4 * cm, 12 * cm]),
          bullets([_("The motor name is proposed from the class and the average thrust (e.g. <i>L1729</i>), delays "
                     "default to <i>P</i> (plugged)."),
                   _("The workbook only gives the chamber <b>inside</b> dimensions: enter the casing outside diameter, the "
                     "overall length (pre-filled with chamber + nozzle length), the hardware masses and the manufacturer."),
                   _("Curve source: <b>[[Performance sheet, simplified (recommended)]]</b> (about 30 points within 0.5 % "
                     "of the maximum thrust), full resolution, resampled, or the Output table (coarser: its impulse is 1 to "
                     "2 % lower)."),
                   _("The cross-check table compares the SRM results with the values recomputed from the imported curve."),
                   _("The design data (grain, Kn, throat, pressure...) is kept in the project file and the SRM results in "
                     "the <b>[[Comments]]</b> field.")])]
    # 7 -----------------------------------------------------------------
    s += [p(_("7. Digitizing a thrust curve"), H1),
          *screenshot("digitizer", _("Figure 4 - Curve digitizer: calibrated image with extracted points and reconstructed curve.")),
          p(_("Open <b>[[&Tools|Curve &Digitizer...]]</b> (F6) or <b>[[&File|Import Thrust Curve &Image...]]</b>. PNG, "
              "JPEG, TIFF and BMP photographs, screenshots and scans are supported. The mouse wheel zooms, the middle "
              "button pans.")),
          p(_("Step 1 - Image corrections"), H2),
          bullets([_("<b>[[Rotate]]</b> by an angle to straighten a slightly tilted graph."),
                   _("<b>[[Crop]]</b>: drag a rectangle around the useful area."),
                   _("<b>[[Perspective]]</b>: click the four corners of the graph frame of a photograph to make it rectangular."),
                   _("Contrast, brightness, grey levels and noise filters (median, gaussian, bilateral, non-local means) "
                     "are applied live."),
                   _("<b>[[Undo correction]]</b> and <b>[[Reset all corrections]]</b> restore the previous or original image.")]),
          p(_("Geometric corrections clear the calibration, so straighten the image before calibrating."), NOTE),
          p(_("Step 2 - Axis calibration"), H2),
          steps([_("<b>[[Set origin]]</b>: click the intersection of the axes and enter its time and thrust (usually 0 s, 0 N)."),
                 _("<b>[[Set time-axis point]]</b>: click a known graduation of the time axis (e.g. 2.0 s) and enter its value."),
                 _("<b>[[Set thrust-axis point]]</b>: click a known graduation of the thrust axis (e.g. 16 N) and enter its value."),
                 _("Optionally <b>[[Add extra point]]</b> with known coordinates: a least-squares fit then improves the "
                   "precision and the residual (in pixels) is displayed.")]),
          p(_("The calibration is an affine transformation, which also compensates a small rotation or skew of the graph. "
              "The status bar converts the cursor position to time and thrust in real time.")),
          p(_("Step 3 - Curve extraction"), H2),
          bullets([_("<b>[[Auto-detect]]</b> finds the dominant curve colour; <b>[[Pick]]</b> lets you click on the curve."),
                   _("<b>[[Tolerance]]</b> sets how close a pixel colour must be (tick <i>[[Show detected pixels]]</i> to check)."),
                   _("<b>[[Extract curve]]</b> keeps one point per pixel column inside the calibrated area, removes outliers "
                     "and resamples to the chosen <b>[[Number of points]]</b>."),
                   _("<b>[[Edit points]]</b>: drag a point, click to add, right-click to delete, Shift+drag to erase an area."),
                   _("<b>[[End the curve with zero thrust]]</b> appends the burnout point required by the ENG format.")]),
          p(_("Check the reconstructed curve and its total impulse, then click <b>[[Transfer to motor editor]]</b>."))]
    # 8 -----------------------------------------------------------------
    s += [p(_("8. Editing thrust points"), H1),
          p(_("The table and the graph are always synchronised: every change in one is immediately visible in the other.")),
          table([[_("Operation"), _("In the table"), _("On the graph")],
                 [_("Edit a value"), _("Double-click a cell (or type)"), _("Drag a point (kept between its neighbours)")],
                 [_("Add a point"), _("[[Add point]] button / Ctrl+Ins (mid-point after the selection)"),
                  _("Double-click an empty area")],
                 [_("Delete"), _("Select rows, Del key (multiple selection allowed)"),
                  _("Right-click a point &gt; [[Delete point]]")],
                 [_("Duplicate"), "Ctrl+D", _("Right-click a point &gt; [[Duplicate point]]")],
                 [_("Sort"), _("[[Sort chronologically]] button"), "-"],
                 [_("Paste from Excel"), _("Copy two columns in Excel, select the start row, Ctrl+V"), "-"]],
                [3.2 * cm, 6.6 * cm, 6.2 * cm]),
          p(_("Pasted rows replace the points from the current row onwards (appended at the end without selection). Tab, "
              "semicolon or space separated data and decimal commas are accepted; header lines are ignored.")),
          p(_("The graph scale follows the data automatically: entering or dragging a point above the current maximum "
              "enlarges the axes so that it stays visible. After a manual zoom or pan the view is kept (and only enlarged "
              "if a point leaves it); <b>[[&View|&Reset Graph Zoom]]</b> (Ctrl+0) or the Home button returns to automatic "
              "scaling.")),
          p(_("The curve implicitly starts at (0 s, 0 N), as in the ENG format, so the first point does not need to be at "
              "time zero. The last point should have zero thrust."), NOTE)]
    # 9 -----------------------------------------------------------------
    s += [p(_("9. Analysing the characteristics"), H1),
          *screenshot("analysis", _("Figure 5 - Thrust analysis dialog."), 11 * cm),
          p(_("<b>[[&Tools|Thrust &Analysis...]]</b> (F5) lists every characteristic with its unit. A value that cannot "
              "be computed is greyed out and its tooltip explains which data is missing.")),
          table([[_("Characteristic"), _("Definition")],
                 ["[[Total impulse]] (N.s)", _("Trapezoidal integral of thrust over time, from the implicit origin (0, 0).")],
                 ["[[Maximum thrust]] (N)", _("Highest thrust sample; [[Time to maximum thrust]] is its time.")],
                 ["[[Burn time]] (s)", _("[[Full powered curve]] (ignition to burnout) or NAR convention: between the "
                                         "instants when thrust crosses 5 % of the maximum (linear interpolation).")],
                 ["[[Average thrust]] (N)", _("Total impulse / burn time.")],
                 ["[[Initial thrust]] / [[Final thrust]] (N)", _("Thrust of the first and last data points.")],
                 ["[[Initial motor mass]] (g)", _("Total loaded mass.")],
                 ["[[Propellant mass fraction]]", _("Propellant mass / total motor mass.")],
                 ["[[Specific impulse]] (s)", _("Total impulse / (propellant mass in kg × 9.80665 m/s²).")],
                 ["[[Impulse class]]", _("NAR letter (A = 1.26-2.5 N.s, each letter doubles) with the percentage within the class.")]],
                [4.5 * cm, 11.5 * cm]),
          p(_("The analysis report can be copied to the clipboard or saved as a text file. The burn time definition and the "
              "display unit system (metric or imperial) are set in the preferences."))]
    # 10 ----------------------------------------------------------------
    s += [p(_("10. Exporting to ENG"), H1),
          p(_("<b>[[&File|E&xport as ENG...]]</b> (Ctrl+Shift+E) first validates the motor. Blocking errors (missing "
              "name, manufacturer, diameter, length or masses, invalid delays, negative or non-chronological data) prevent "
              "the export and are listed; double-click an item to select the faulty point. Warnings (for example a curve "
              "that does not end at zero thrust) require an explicit confirmation.")),
          bullets([_("Header: name, diameter (mm), length (mm), delays, propellant mass (kg), total mass (kg), manufacturer."),
                   _("Spaces in the name or manufacturer are replaced by underscores; non-ASCII characters are transliterated."),
                   _("Numbers are written in plain decimal notation (never scientific), with up to 6 decimals."),
                   _("A leading (0, 0) point is not written because it is implicit. Lines end with CR+LF."),
                   _("Original ENG comments are preserved; no non-standard data is added to the file.")]),
          p(_("Exported files can be re-imported by the application and loaded in OpenRocket (Preferences &gt; "
              "Motors &gt; user thrust curve folder) and RockSim."))]
    # 11 ----------------------------------------------------------------
    s += [p(_("11. Saving the XML project"), H1),
          p(_("<b>[[&File|&Save Motor]]</b> writes a native project file (<i>.rmm.xml</i>) containing everything visible "
              "in the application: properties, masses, dimensions, thrust points (exact values), computed characteristics "
              "(for information), graph settings, ENG comments, metadata (creation and modification dates, source file) "
              "and the label design.")),
          bullets([_("The file is versioned (<i>formatVersion</i>); older versions are upgraded automatically on opening."),
                   _("The structure is validated on opening; a corrupted file is reported precisely and never half-loaded."),
                   _("The save dialog asks before replacing an existing file; saves are atomic."),
                   _("Recent files are listed in <b>[[&File|Recent &Files]]</b>.")]),
          p(_("CSV export"), H2),
          p(_("<b>[[&File|Export CS&V...]]</b> lets you choose the column separator, decimal separator, encoding "
              "(utf-8-sig is best for Excel), time and thrust units, number of decimals and whether the motor properties "
              "are written as '#' comment lines."))]
    # 12 ----------------------------------------------------------------
    s += [p(_("12. Creating labels"), H1),
          *screenshot("label_designer", _("Figure 6 - Label designer with live preview.")),
          p(_("<b>[[&Tools|&Label Designer...]]</b> (F7) opens an independent window. The preview uses exactly the same "
              "renderer as the printer, so what you see is what is printed, at the physical dimensions entered.")),
          bullets([_("<b>[[Template]]</b>: choose a predefined template (Classic, Minimal, Banner, Dark, 18 mm wrap, Data "
                     "sheet) or your own; save the current design as a reusable template."),
                   _("<b>[[Dimensions]]</b>: width, height, inner margin, border width and corner radius in millimetres."),
                   _("<b>[[Colours and text]]</b>: background, text, accent and border colours, font, sizes, alignment, "
                     "layout (stacked, two columns, banner) and the field used as title."),
                   _("<b>[[Information to display]]</b>: tick the fields and drag them to reorder; add free text lines."),
                   _("<b>[[Logo]]</b>: import a PNG or JPG logo and set its position and size (aspect ratio kept)."),
                   _("<b>[[Store in project]]</b> saves the design in the motor project.")]),
          p(_("Values are taken from the current motor and its analysis and are updated automatically. Text that does not "
              "fit is reduced automatically."), NOTE)]
    # 13 ----------------------------------------------------------------
    s += [p(_("13. Printing"), H1),
          p(_("The <b>[[&Print]]</b> menu (and the label designer toolbar) offers:")),
          bullets([_("<b>[[Print Preview]]</b>: the label sheet on the selected paper format (A4, A5, A6, Letter, Legal)."),
                   _("<b>[[Print PDF]]</b>: a vector PDF sheet; labels are laid out in a grid using the page margin and "
                     "spacing. Use <i>[[Copies]]</i> or <i>[[Fill the whole page]]</i>; extra pages are added automatically."),
                   _("<b>[[Export Label as P&NG...]]</b> / <b>[[Export Label as &JPEG...]]</b>: one label at the chosen "
                     "resolution (72-2400 dpi). The image resolution is embedded so it prints at the right size."),
                   _("<b>[[Print...]]</b> in the label designer sends the sheet to a printer.")]),
          p(_("When printing, set the printer scaling to 100 % (\"actual size\") so that the physical dimensions are "
              "respected."), NOTE)]
    # 14 ----------------------------------------------------------------
    s += [p(_("14. Preferences"), H1),
          *screenshot("preferences", _("Figure 7 - Preferences dialog."), 9 * cm),
          p(_("Open <b>[[&Edit|&Preferences...]]</b>.")),
          table([[_("Tab"), _("Settings")],
                 ["[[General]]", _("[[Language]]: English, Français, Deutsch, Español, Italiano, Nederlands, Polski, "
                                   "Português or Русский (restart required), and light/dark theme. The manual opened by "
                                   "[[&Help|&Manual]] (F1) is the one of the selected language.")],
                 ["[[Units]]", _("Display unit system (metric N, N.s, g, mm or imperial lbf, lbf.s, oz, in), default "
                                 "decimal separator, burn time definition.")],
                 ["[[Graph]]", _("Curve and marker colours, grid, markers, area fill.")],
                 ["[[Folders]]", _("Default save folder and import folder.")],
                 ["[[Printing]]", _("Default paper format and image resolution.")]],
                [3 * cm, 13 * cm]),
          p(_("Preferences are saved between sessions. <b>Restore Defaults</b> resets every setting (recent files and "
              "window layout are kept)."))]
    # 15 ----------------------------------------------------------------
    s += [p(_("15. Troubleshooting"), H1),
          table([[_("Problem"), _("Solution")],
                 [_("\"Line N: ...\" when importing an ENG file"),
                  _("Open the file in a text editor and fix the indicated line: each data line must contain exactly two "
                    "numbers with a decimal point.")],
                 [_("ENG export refused"),
                  _("Run [[&Tools|Data &Validation...]] (F8). Fill in the required properties and fix red rows (sort the "
                    "points if they are not chronological).")],
                 [_("CSV columns not separated correctly"),
                  _("Change the column separator and decimal separator in the import preview.")],
                 [_("Excel file cannot be opened"),
                  _("Close the workbook in Excel (it locks the file) and check the extension (.xlsx or .xls).")],
                 [_("Digitizer finds no pixel"),
                  _("Pick the curve colour on the curve itself, increase the tolerance, untick '[[Only inside the "
                    "calibrated area (axes excluded)]]' if the curve touches the axes.")],
                 [_("Digitized values are shifted"),
                  _("Check the calibration values, add extra calibration points and straighten the image "
                    "(rotation/perspective) before calibrating.")],
                 [_("SRM workbook: values missing or curve not found"),
                  _("Open the workbook in Excel, click the Solve buttons, save it, then import again (the importer reads "
                    "the values computed by the workbook).")],
                 [_("Printed label has the wrong size"), _("Print at 100 % scale (no 'fit to page').")],
                 [_("The motor does not appear in OpenRocket"),
                  _("Put the .eng file in the user thrust curve folder declared in OpenRocket preferences and restart "
                    "OpenRocket.")],
                 [_("Unexpected error"),
                  _("The message is also written to the log file (see chapter 2); send it with the data file to the author.")]],
                [5.5 * cm, 10.5 * cm])]
    return s


# --------------------------------------------------------------------- build
def build(language: str = "en") -> Path:
    """Build the manual of a language and return its path."""
    set_language(language)
    output = manual_path(language)
    output.parent.mkdir(parents=True, exist_ok=True)
    title = f"{APP_NAME} - {_('User manual')}"
    doc = ManualTemplate(str(output), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
                         bottomMargin=2 * cm, title=title, author=APP_AUTHOR, subject=_("User manual"),
                         creator=APP_NAME, lang=language)
    story = cover() + contents() + chapters()
    doc.multiBuild(story, onLaterPages=on_page)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the PDF user manuals.")
    parser.add_argument("languages", nargs="*", help="language codes (default: all)")
    args = parser.parse_args(argv)
    languages = args.languages or list(localization.LANGUAGES)
    unknown = [code for code in languages if code not in localization.LANGUAGES]
    if unknown:
        parser.error(f"unknown language(s): {', '.join(unknown)}")
    for language in languages:
        print("Manual written to", build(language))
    localization.install("en")
    return 0


if __name__ == "__main__":
    sys.exit(main())
