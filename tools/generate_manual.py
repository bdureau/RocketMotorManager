"""Generate the PDF user manual (documentation/user_manual.pdf) with ReportLab.

Run from the project root:  ``python tools/generate_manual.py``
(run ``python tools/capture_screenshots.py`` first to refresh the
screenshots used as illustrations).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

from application.version import APP_AUTHOR, APP_COPYRIGHT, APP_NAME, APP_VERSION  # noqa: E402

SHOTS = ROOT / "documentation" / "screenshots"
OUTPUT = ROOT / "documentation" / "user_manual.pdf"
ACCENT = colors.HexColor("#1F4E79")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=ACCENT, fontSize=18, spaceBefore=6, spaceAfter=10)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=ACCENT, fontSize=13, spaceBefore=10, spaceAfter=6)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
NOTE = ParagraphStyle("Note", parent=BODY, backColor=colors.HexColor("#EAF2FB"), borderColor=ACCENT, borderWidth=0.5,
                      borderPadding=6, spaceBefore=6, spaceAfter=10)
CAPTION = ParagraphStyle("Caption", parent=BODY, fontSize=8.5, textColor=colors.grey, alignment=TA_CENTER)
CODE = ParagraphStyle("Code", parent=BODY, fontName="Courier", fontSize=8.5, leading=11, backColor=colors.HexColor("#F4F4F4"),
                      borderPadding=5, spaceBefore=4, spaceAfter=8)


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
    return Paragraph(text, style)


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(p(item), leftIndent=12) for item in items], bulletType="bullet", start="•", leftIndent=14)


def steps(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(p(item), leftIndent=12) for item in items], bulletType="1", leftIndent=16)


def table(rows: list[list[str]], widths: list[float]) -> Table:
    header = ParagraphStyle("th", parent=BODY, textColor=colors.white, fontName="Helvetica-Bold")
    data = [[p(cell, header) for cell in rows[0]]] + [[p(cell) for cell in row] for row in rows[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B7C3")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")]),
    ]))
    return t


def screenshot(name: str, caption: str, width: float = 16 * cm) -> list:
    path = SHOTS / f"{name}.png"
    if not path.exists():
        return [p(f"<i>[Screenshot '{name}' not available - run tools/capture_screenshots.py]</i>", CAPTION)]
    image = Image(str(path))
    ratio = image.imageHeight / image.imageWidth
    height = width * ratio
    if height > 15 * cm:
        height, width = 15 * cm, 15 * cm / ratio
    image.drawWidth, image.drawHeight = width, height
    return [KeepTogether([image, p(caption, CAPTION)]), Spacer(1, 6)]


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2 * cm, 1.2 * cm, f"{APP_NAME} {APP_VERSION} - User manual")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(ACCENT)
    canvas.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
    canvas.restoreState()


def cover() -> list:
    story = [Spacer(1, 4 * cm)]
    icon = ROOT / "resources" / "icons" / "app.png"
    if icon.exists():
        image = Image(str(icon), 4.5 * cm, 4.5 * cm)
        story.append(image)
    story += [
        Spacer(1, 1 * cm),
        p(f"<para alignment='center'><font size=28 color='#1F4E79'><b>{APP_NAME}</b></font></para>"),
        Spacer(1, 0.8 * cm),
        p("<para alignment='center'><font size=14>User manual</font></para>"),
        Spacer(1, 0.4 * cm),
        p(f"<para alignment='center'>Version {APP_VERSION} - {date.today():%B %Y}</para>"),
        Spacer(1, 6 * cm),
        p(f"<para alignment='center'>{APP_AUTHOR}<br/>{APP_COPYRIGHT}</para>"),
        PageBreak(),
    ]
    return story


def contents() -> list:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc1", fontName="Helvetica-Bold", fontSize=11, leftIndent=10, firstLineIndent=-10, spaceBefore=4),
        ParagraphStyle("toc2", fontName="Helvetica", fontSize=9.5, leftIndent=28, firstLineIndent=-10),
    ]
    return [p("Contents", ParagraphStyle("TOCTitle", parent=H1)), toc, PageBreak()]


def chapters() -> list:
    s: list = []
    # 1 -----------------------------------------------------------------
    s += [p("1. General presentation", H1),
          p(f"{APP_NAME} is a desktop application to create, import, edit, convert, analyse, visualise and archive "
            "rocket motor thrust data. It reads and writes the standard RASP <b>.eng</b> format used by OpenRocket and "
            "RockSim, imports CSV and Excel files, digitizes thrust curves from photographs or scans, computes the motor "
            "characteristics and prints custom motor labels."),
          p("Main features", H2),
          bullets(["Motor properties editor (identity, dimensions, masses with automatic total mass).",
                   "Interactive thrust curve: zoom, pan, cursor read-out, graphical point editing, PNG/SVG/PDF export.",
                   "Synchronised data table: add, edit, duplicate, delete, sort, paste from Excel, unlimited undo/redo.",
                   "Import ENG (several motors per file), CSV (automatic separator/decimal/encoding detection) and Excel (.xlsx, .xls).",
                   "Curve digitizer: image corrections, multi-point axis calibration, colour extraction, outlier removal, manual correction.",
                   "Analysis: total impulse, average/maximum thrust, burn time, specific impulse, impulse class.",
                   "Strict ENG export with validation; native versioned XML project keeping every piece of information.",
                   "Label designer with templates, logo, print preview, PDF, PNG and JPEG export at physical size."]),
          p("Data principles", H2),
          bullets(["Internal units are fixed and explicit: seconds, Newtons, Newton-seconds, grams and millimetres.",
                   "Original data is never altered silently: sorting, resampling or replacing points are explicit and undoable.",
                   "Information that the ENG format cannot hold (component masses, descriptions, label...) is kept in the XML project.",
                   "Every save is atomic: an interrupted save never corrupts an existing file."])]
    # 2 -----------------------------------------------------------------
    s += [p("2. Installation", H1),
          p("Standalone executable (recommended)", H2),
          p("Copy the <b>RocketMotorManager</b> folder produced by the build (or the installer output) anywhere on the "
            "computer and run <b>RocketMotorManager.exe</b>. No Python installation is required."),
          p("From the source code", H2),
          steps(["Install Python 3.10 or later (64-bit) from python.org, ticking <i>Add Python to PATH</i>.",
                 "Double-click <b>install.bat</b>: it creates a virtual environment (<i>.venv</i>) and installs the dependencies.",
                 "Double-click <b>run.bat</b> to start the application.",
                 "Optional: run <b>build_exe.bat</b> to produce the standalone executable in <i>dist\\RocketMotorManager</i>."]),
          p("Files and folders used by the application", H2),
          table([["Item", "Location (Windows)"],
                 ["Preferences", "%APPDATA%\\RocketMotorManager\\preferences.json"],
                 ["User label templates", "%APPDATA%\\RocketMotorManager\\label_templates\\"],
                 ["Technical log", "%LOCALAPPDATA%\\RocketMotorManager\\logs\\rocket_motor_manager.log"]],
                [5 * cm, 11 * cm])]
    # 3 -----------------------------------------------------------------
    s += [p("3. The user interface", H1),
          *screenshot("main_window", "Figure 1 - Main window: motor properties (left), thrust curve (centre), data table (right)."),
          p("The main window is divided into three zones:"),
          bullets(["<b>Motor properties</b> (left dock): identification, dimensions, masses, description and a summary of "
                   "the computed characteristics. The dock can be moved, floated or hidden (View menu).",
                   "<b>Thrust curve</b> (centre): Time (s) on X, Thrust (N) on Y. The dotted green line shows the average "
                   "thrust over the burn window; the box in the corner summarises impulse, average thrust and burn time.",
                   "<b>Thrust data table</b> (right): the points of the curve. Rows in red contain errors, rows in yellow warnings."]),
          p("The toolbar gives access to New, Open, Save, Import, Export, Undo/Redo, Add/Delete Point, Analyze, Digitize "
            "and Label. The status bar shows the file path, the number of points, the total impulse with its class and "
            "the cursor coordinates. Every field and button has a tooltip explaining its meaning, unit and constraints."),
          p("Keyboard shortcuts", H2),
          table([["Action", "Shortcut"], ["New / Open / Save / Save As", "Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S"],
                 ["Undo / Redo", "Ctrl+Z / Ctrl+Y"], ["Import ENG / Export ENG", "Ctrl+E / Ctrl+Shift+E"],
                 ["Add point / Delete point(s)", "Ctrl+Ins / Del (table) or Ctrl+Del"], ["Duplicate point", "Ctrl+D (table)"],
                 ["Copy / Paste points", "Ctrl+C / Ctrl+V (table)"], ["Reset zoom / Toggle grid", "Ctrl+0 / Ctrl+G"],
                 ["Analysis / Digitizer / Labels / Validation", "F5 / F6 / F7 / F8"], ["Print labels to PDF", "Ctrl+P"],
                 ["Manual", "F1"]], [8 * cm, 8 * cm]),
          p("Files can also be dropped on the main window: .rmm.xml and .eng files are opened, CSV/Excel files are "
            "imported and images open the digitizer.", NOTE)]
    # 4 -----------------------------------------------------------------
    s += [p("4. Creating a motor", H1),
          steps(["Choose <b>File &gt; New Motor</b> (Ctrl+N).",
                 "Fill in the <b>Motor name</b> (short code written in ENG files, e.g. <i>C6</i>), the <b>Manufacturer</b> "
                 "and the <b>Motor designation</b> (e.g. <i>C6-5</i>).",
                 "Enter the <b>ejection delays</b> separated by dashes (e.g. <i>3-5-7</i>); use <i>P</i> for a plugged motor and <i>0</i> for none.",
                 "Enter the diameter and length in millimetres and the masses in grams. Decimal point or comma are both accepted.",
                 "Enter the thrust points in the table (see chapter 8), import them or digitize a graph.",
                 "Save the project with <b>File &gt; Save Motor</b>."]),
          p("Total motor mass", H2),
          p("When the casing mass or the nozzle and closure mass is entered, the total motor mass is computed "
            "automatically (propellant + casing + nozzle/closure) and the field becomes read-only. Otherwise the total "
            "mass can be entered directly (this is the case after an ENG import, which only provides the total and "
            "propellant masses)."),
          p("Every change can be undone with Ctrl+Z. The window title shows an asterisk when changes are not saved; the "
            "application always asks before closing or opening another motor.", NOTE)]
    # 5 -----------------------------------------------------------------
    s += [p("5. Importing an ENG file", H1),
          p("Choose <b>File &gt; Import ENG</b> (Ctrl+E). The header (name, diameter, length, delays, propellant mass, "
            "total mass, manufacturer), the comments and every thrust point are read. If the file contains several "
            "motors, a list lets you choose one. The motor opens as a new unsaved document."),
          p("Example of ENG file", H2),
          p("; comment lines start with a semicolon<br/>C6 18 70 0-3-5-7 0.0108 0.0231 Estes<br/>"
            "&nbsp;&nbsp;&nbsp;0.031 0.946<br/>&nbsp;&nbsp;&nbsp;0.092 4.826<br/>&nbsp;&nbsp;&nbsp;...<br/>"
            "&nbsp;&nbsp;&nbsp;1.860 0.000", CODE),
          p("When a file is invalid the message gives the exact line number and content (for example "
            "<i>Line 5: Non-numeric thrust data -&gt; \"0.089 abc\"</i>). Non-blocking problems (curve not ending at "
            "zero, non-chronological points) are reported as warnings after the import.")]
    # 6 -----------------------------------------------------------------
    s += [p("6. Importing CSV and Excel files", H1),
          *screenshot("csv_import", "Figure 2 - CSV import preview with column mapping, units and invalid row highlighting.", 15 * cm),
          p("<b>File &gt; Import CSV</b> opens a preview. The encoding, column separator, decimal separator and header row "
            "are detected automatically and can be changed. <b>File &gt; Import Excel</b> works the same way for .xlsx and "
            ".xls workbooks, with a choice of worksheet."),
          steps(["Select the <b>Time column</b> and its unit (s or ms).",
                 "Select the <b>Thrust column</b> and its unit (N, lbf or kgf). Values are converted to seconds and Newtons.",
                 "Check the preview graph. Invalid rows (missing or non-numeric values, negative times) are highlighted in red; "
                 "their tooltip gives the reason.",
                 "Keep <b>Remove invalid rows</b> ticked to import only the valid points, then click <b>Import</b>."]),
          p("The imported points replace the thrust curve of the current motor after confirmation; the operation can be "
            "undone with Ctrl+Z."),
          p("Richard Nakka SRM workbooks", H2),
          *screenshot("srm_import", "Figure 3 - Import of an SRM workbook with curve choice and cross-check.", 15 * cm),
          p("The SRM design spreadsheets of Richard Nakka (SRM 1.x and SRM 2023, .xls or .xlsx) are not plain tables: "
            "<b>File &gt; Import SRM Workbook (Nakka)</b> reads each piece of information in its own sheet. Opening such a "
            "workbook with Import Excel or by drag and drop is detected automatically and the SRM import is proposed."),
          table([["Sheet", "Information imported"],
                 ["Data and Kn", "Title, propellant (KNDX, KNSB, KNSU, KNER...), chamber inside diameter and length, grain "
                                 "geometry and mass, Kn, throat diameter"],
                 ["Output", "SRM results (total impulse, average thrust, thrust time, Isp, class) and the 23-point table"],
                 ["Performance", "Full resolution thrust curve (about 880 points) and maximum thrust"],
                 ["Pressure / Nozzle Design", "Maximum chamber pressure, burn time, nozzle length (informative)"]],
                [4 * cm, 12 * cm]),
          bullets(["The motor name is proposed from the class and the average thrust (e.g. <i>L1729</i>), delays default to "
                   "<i>P</i> (plugged).",
                   "The workbook only gives the chamber <b>inside</b> dimensions: enter the casing outside diameter, the overall "
                   "length (pre-filled with chamber + nozzle length), the hardware masses and the manufacturer.",
                   "Curve source: <b>Performance, simplified</b> (recommended, about 30 points within 0.5 % of the maximum "
                   "thrust), full resolution, resampled, or the Output table (coarser: its impulse is 1 to 2 % lower).",
                   "The cross-check table compares the SRM results with the values recomputed from the imported curve.",
                   "The design data (grain, Kn, throat, pressure...) is kept in the project file and the SRM results in the "
                   "Comments field."])]
    # 7 -----------------------------------------------------------------
    s += [p("7. Digitizing a thrust curve", H1),
          *screenshot("digitizer", "Figure 4 - Curve digitizer: calibrated image with extracted points and reconstructed curve."),
          p("Open <b>Tools &gt; Curve Digitizer</b> (F6) or <b>File &gt; Import Thrust Curve Image</b>. PNG, JPEG, TIFF and "
            "BMP photographs, screenshots and scans are supported. The mouse wheel zooms, the middle button pans."),
          p("Step 1 - Image corrections", H2),
          bullets(["<b>Rotate</b> by an angle to straighten a slightly tilted graph.",
                   "<b>Crop</b>: drag a rectangle around the useful area.",
                   "<b>Perspective</b>: click the four corners of the graph frame of a photograph to make it rectangular.",
                   "Contrast, brightness, grey levels and noise filters (median, gaussian, bilateral, non-local means) are applied live.",
                   "<b>Undo correction</b> and <b>Reset all corrections</b> restore the previous or original image."]),
          p("Geometric corrections clear the calibration, so straighten the image before calibrating.", NOTE),
          p("Step 2 - Axis calibration", H2),
          steps(["<b>Set origin</b>: click the intersection of the axes and enter its time and thrust (usually 0 s, 0 N).",
                 "<b>Set time-axis point</b>: click a known graduation of the time axis (e.g. 2.0 s) and enter its value.",
                 "<b>Set thrust-axis point</b>: click a known graduation of the thrust axis (e.g. 16 N) and enter its value.",
                 "Optionally <b>Add extra points</b> with known coordinates: a least-squares fit then improves the precision "
                 "and the residual (in pixels) is displayed."]),
          p("The calibration is an affine transformation, which also compensates a small rotation or skew of the graph. "
            "The status bar converts the cursor position to time and thrust in real time."),
          p("Step 3 - Curve extraction", H2),
          bullets(["<b>Auto-detect</b> finds the dominant curve colour; <b>Pick</b> lets you click on the curve.",
                   "<b>Tolerance</b> sets how close a pixel colour must be (tick <i>Show detected pixels</i> to check).",
                   "<b>Extract curve</b> keeps one point per pixel column inside the calibrated area, removes outliers and "
                   "resamples to the chosen <b>Number of points</b>.",
                   "<b>Edit points</b>: drag a point, click to add, right-click to delete, Shift+drag to erase an area.",
                   "<b>End the curve with zero thrust</b> appends the burnout point required by the ENG format."]),
          p("Check the reconstructed curve and its total impulse, then click <b>Transfer to motor editor</b>.")]
    # 8 -----------------------------------------------------------------
    s += [p("8. Editing thrust points", H1),
          p("The table and the graph are always synchronised: every change in one is immediately visible in the other."),
          table([["Operation", "In the table", "On the graph"],
                 ["Edit a value", "Double-click a cell (or type)", "Drag a point (kept between its neighbours)"],
                 ["Add a point", "Add button / Ctrl+Ins (mid-point after the selection)", "Double-click an empty area"],
                 ["Delete", "Select rows, Del key (multiple selection allowed)", "Right-click a point > Delete"],
                 ["Duplicate", "Ctrl+D", "Right-click a point > Duplicate"],
                 ["Sort", "Sort button (chronological)", "-"],
                 ["Paste from Excel", "Copy two columns in Excel, select the start row, Ctrl+V", "-"]],
                [3.2 * cm, 6.6 * cm, 6.2 * cm]),
          p("Pasted rows replace the points from the current row onwards (appended at the end without selection). Tab, "
            "semicolon or space separated data and decimal commas are accepted; header lines are ignored."),
          p("The graph scale follows the data automatically: entering or dragging a point above the current maximum "
            "enlarges the axes so that it stays visible. After a manual zoom or pan the view is kept (and only enlarged "
            "if a point leaves it); <b>View &gt; Reset Graph Zoom</b> (Ctrl+0) or the Home button returns to automatic scaling."),
          p("The curve implicitly starts at (0 s, 0 N), as in the ENG format, so the first point does not need to be at "
            "time zero. The last point should have zero thrust.", NOTE)]
    # 9 -----------------------------------------------------------------
    s += [p("9. Analysing the characteristics", H1),
          *screenshot("analysis", "Figure 5 - Thrust analysis dialog.", 11 * cm),
          p("<b>Tools &gt; Thrust Analysis</b> (F5) lists every characteristic with its unit. A value that cannot be "
            "computed is greyed out and its tooltip explains which data is missing."),
          table([["Characteristic", "Definition"],
                 ["Total impulse (N.s)", "Trapezoidal integral of thrust over time, from the implicit origin (0, 0)."],
                 ["Maximum thrust (N)", "Highest thrust sample; Time to maximum thrust is its time."],
                 ["Burn time (s)", "Full powered curve (ignition to burnout) or NAR convention: between the instants "
                                   "when thrust crosses 5 % of the maximum (linear interpolation)."],
                 ["Average thrust (N)", "Total impulse / burn time."],
                 ["Initial / final thrust (N)", "Thrust of the first and last data points."],
                 ["Initial motor mass (g)", "Total loaded mass."],
                 ["Propellant mass fraction", "Propellant mass / total motor mass."],
                 ["Specific impulse (s)", "Total impulse / (propellant mass in kg × 9.80665 m/s²)."],
                 ["Impulse class", "NAR letter (A = 1.26-2.5 N.s, each letter doubles) with the percentage within the class."]],
                [4.5 * cm, 11.5 * cm]),
          p("The analysis report can be copied to the clipboard or saved as a text file. The burn time definition and the "
            "display unit system (metric or imperial) are set in the Preferences.")]
    # 10 ----------------------------------------------------------------
    s += [p("10. Exporting to ENG", H1),
          p("<b>File &gt; Export as ENG</b> (Ctrl+Shift+E) first validates the motor. Blocking errors (missing name, "
            "manufacturer, diameter, length or masses, invalid delays, negative or non-chronological data) prevent the "
            "export and are listed; double-click an item to select the faulty point. Warnings (for example a curve that "
            "does not end at zero thrust) require an explicit confirmation."),
          bullets(["Header: name, diameter (mm), length (mm), delays, propellant mass (kg), total mass (kg), manufacturer.",
                   "Spaces in the name or manufacturer are replaced by underscores; non-ASCII characters are transliterated.",
                   "Numbers are written in plain decimal notation (never scientific), with up to 6 decimals.",
                   "A leading (0, 0) point is not written because it is implicit. Lines end with CR+LF.",
                   "Original ENG comments are preserved; no non-standard data is added to the file."]),
          p("Exported files can be re-imported by the application and loaded in OpenRocket (Preferences &gt; "
            "Motors &gt; user thrust curve folder) and RockSim.")]
    # 11 ----------------------------------------------------------------
    s += [p("11. Saving the XML project", H1),
          p("<b>File &gt; Save Motor</b> writes a native project file (<i>.rmm.xml</i>) containing everything visible in the "
            "application: properties, masses, dimensions, thrust points (exact values), computed characteristics (for "
            "information), graph settings, ENG comments, metadata (creation and modification dates, source file) and the "
            "label design."),
          bullets(["The file is versioned (<i>formatVersion</i>); older versions are upgraded automatically on opening.",
                   "The structure is validated on opening; a corrupted file is reported precisely and never half-loaded.",
                   "The save dialog asks before replacing an existing file; saves are atomic.",
                   "Recent files are listed in <b>File &gt; Recent Files</b>."]),
          p("CSV export", H2),
          p("<b>File &gt; Export CSV</b> lets you choose the column separator, decimal separator, encoding (utf-8-sig is "
            "best for Excel), time and thrust units, number of decimals and whether the motor properties are written as "
            "'#' comment lines.")]
    # 12 ----------------------------------------------------------------
    s += [p("12. Creating labels", H1),
          *screenshot("label_designer", "Figure 6 - Label designer with live preview."),
          p("<b>Tools &gt; Label Designer</b> (F7) opens an independent window. The preview uses exactly the same renderer "
            "as the printer, so what you see is what is printed, at the physical dimensions entered."),
          bullets(["<b>Template</b>: choose a predefined template (Classic, Minimal, Banner, Dark, 18 mm wrap, Data sheet) or "
                   "your own; save the current design as a reusable template.",
                   "<b>Dimensions</b>: width, height, inner margin, border width and corner radius in millimetres.",
                   "<b>Colours and text</b>: background, text, accent and border colours, font, sizes, alignment, layout "
                   "(stacked, two columns, banner) and the field used as title.",
                   "<b>Information to display</b>: tick the fields and drag them to reorder; add free text lines.",
                   "<b>Logo</b>: import a PNG or JPG logo and set its position and size (aspect ratio kept).",
                   "<b>Store in project</b> saves the design in the motor project."]),
          p("Values are taken from the current motor and its analysis and are updated automatically. Text that does not "
            "fit is reduced automatically.", NOTE)]
    # 13 ----------------------------------------------------------------
    s += [p("13. Printing", H1),
          p("The <b>Print</b> menu (and the label designer toolbar) offers:"),
          bullets(["<b>Print Preview</b>: the label sheet on the selected paper format (A4, A5, A6, Letter, Legal).",
                   "<b>Print PDF</b>: a vector PDF sheet; labels are laid out in a grid using the page margin and spacing. "
                   "Use <i>Copies</i> or <i>Fill the whole page</i>; extra pages are added automatically.",
                   "<b>Export Label as PNG / JPEG</b>: one label at the chosen resolution (72-2400 dpi). The image resolution "
                   "is embedded so it prints at the right size.",
                   "<b>Print...</b> in the label designer sends the sheet to a printer."]),
          p("When printing, set the printer scaling to 100 % (\"actual size\") so that the physical dimensions are respected.", NOTE)]
    # 14 ----------------------------------------------------------------
    s += [p("14. Preferences", H1),
          *screenshot("preferences", "Figure 7 - Preferences dialog.", 9 * cm),
          table([["Tab", "Settings"],
                 ["General", "Language (other languages appear when their translation file is installed; restart required) and light/dark theme."],
                 ["Units", "Display unit system (metric N, N.s, g, mm or imperial lbf, lbf.s, oz, in), default decimal separator, burn time definition."],
                 ["Graph", "Curve and marker colours, grid, markers, area fill."],
                 ["Folders", "Default save folder and import folder."],
                 ["Printing", "Default paper format and image resolution."]],
                [3 * cm, 13 * cm]),
          p("Preferences are saved between sessions. <b>Restore Defaults</b> resets every setting (recent files and window "
            "layout are kept).")]
    # 15 ----------------------------------------------------------------
    s += [p("15. Troubleshooting", H1),
          table([["Problem", "Solution"],
                 ["\"Line N: ...\" when importing an ENG file", "Open the file in a text editor and fix the indicated line: each data line must contain exactly two numbers with a decimal point."],
                 ["ENG export refused", "Run Tools > Data Validation (F8). Fill in the required properties and fix red rows (sort the points if they are not chronological)."],
                 ["CSV columns not separated correctly", "Change the column separator and decimal separator in the import preview."],
                 ["Excel file cannot be opened", "Close the workbook in Excel (it locks the file) and check the extension (.xlsx or .xls)."],
                 ["Digitizer finds no pixel", "Pick the curve colour on the curve itself, increase the tolerance, untick 'Only inside the calibrated area' if the curve touches the axes."],
                 ["Digitized values are shifted", "Check the calibration values, add extra calibration points and straighten the image (rotation/perspective) before calibrating."],
                 ["SRM workbook: values missing or curve not found", "Open the workbook in Excel, click the Solve buttons, save it, then import again (the importer reads the values computed by the workbook)."],
                 ["Printed label has the wrong size", "Print at 100 % scale (no 'fit to page')."],
                 ["The motor does not appear in OpenRocket", "Put the .eng file in the user thrust curve folder declared in OpenRocket preferences and restart OpenRocket."],
                 ["Unexpected error", "The message is also written to the log file (see chapter 2); send it with the data file to the author."]],
                [5.5 * cm, 10.5 * cm])]
    return s


def build() -> Path:
    """Build the manual and return its path."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = ManualTemplate(str(OUTPUT), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
                         bottomMargin=2 * cm, title=f"{APP_NAME} - User manual", author=APP_AUTHOR,
                         subject="User manual", creator=APP_NAME)
    story = cover() + contents() + chapters()
    doc.multiBuild(story, onLaterPages=on_page)
    return OUTPUT


if __name__ == "__main__":
    print("Manual written to", build())
