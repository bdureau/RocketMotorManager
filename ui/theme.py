"""Light and dark themes (Qt palette + Matplotlib colours)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class PlotColors:
    """Colours used by Matplotlib canvases for a theme."""

    figure: str
    axes: str
    text: str
    grid: str
    annotation_bg: str


LIGHT_PLOT = PlotColors("#FFFFFF", "#FFFFFF", "#222222", "#C8C8C8", "#FFFFE0")
DARK_PLOT = PlotColors("#2B2B2B", "#1E1E1E", "#E0E0E0", "#4A4A4A", "#3A3A3A")

_STYLE_SHEET = """
QGroupBox { font-weight: bold; border: 1px solid palette(mid); border-radius: 4px; margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QToolBar { spacing: 4px; padding: 2px; }
QStatusBar QLabel { padding: 0 6px; }
QTableView { gridline-color: palette(mid); }
"""


def plot_colors(theme: str) -> PlotColors:
    """Return the Matplotlib colours for a theme name."""
    return DARK_PLOT if theme == "dark" else LIGHT_PLOT


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply the Fusion style with a light or dark palette."""
    app.setStyle("Fusion")
    palette = QPalette()
    if theme == "dark":
        colors = {
            QPalette.ColorRole.Window: "#2B2B2B", QPalette.ColorRole.WindowText: "#E0E0E0",
            QPalette.ColorRole.Base: "#1E1E1E", QPalette.ColorRole.AlternateBase: "#262626",
            QPalette.ColorRole.ToolTipBase: "#3A3A3A", QPalette.ColorRole.ToolTipText: "#F0F0F0",
            QPalette.ColorRole.Text: "#E0E0E0", QPalette.ColorRole.Button: "#353535",
            QPalette.ColorRole.ButtonText: "#E0E0E0", QPalette.ColorRole.BrightText: "#FF6B6B",
            QPalette.ColorRole.Highlight: "#2E6DB4", QPalette.ColorRole.HighlightedText: "#FFFFFF",
            QPalette.ColorRole.Link: "#6CB4F5", QPalette.ColorRole.PlaceholderText: "#8A8A8A",
            QPalette.ColorRole.Mid: "#4A4A4A",
        }
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#7A7A7A"))
    else:
        palette = app.style().standardPalette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#2E6DB4"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F3F6FA"))
    app.setPalette(palette)
    app.setStyleSheet(_STYLE_SHEET)
