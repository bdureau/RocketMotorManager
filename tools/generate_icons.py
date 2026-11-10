"""Generate the application icon set (SVG) and the Windows .ico file.

Run from the project root:  ``python tools/generate_icons.py``

The SVG icons are simple line pictograms drawn on a 24x24 grid. The
application icon (rocket) is rendered to PNG with Qt and converted to a
multi-resolution .ico with Pillow.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "resources" / "icons"

BLUE = "#2E6DB4"
RED = "#C0392B"
GREEN = "#2E8B57"
ORANGE = "#E67E22"
GREY = "#5D6D7E"


def svg(body: str, color: str = BLUE) -> str:
    """Wrap pictogram paths in a 24x24 SVG with a common stroke style."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>\n"
    )


ICONS: dict[str, str] = {
    "new": svg('<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>'
               f'<path d="M12 11v6M9 14h6" stroke="{GREEN}"/>'),
    "open": svg('<path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>'
                '<path d="M3 11h18"/>'),
    "save": svg('<path d="M5 3h11l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>'
                '<path d="M8 3v5h7V3"/><rect x="7" y="13" width="10" height="6" rx="1"/>'),
    "save_as": svg('<path d="M5 3h11l4 4v6M11 21H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8 3v5h7V3"/>'
                   f'<path d="M14 21l1-3 5-5 2 2-5 5z" stroke="{ORANGE}"/>'),
    "import": svg('<path d="M12 3v11M8 10l4 4 4-4"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>'),
    "export": svg('<path d="M12 14V3M8 7l4-4 4 4"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>'),
    "add_point": svg('<path d="M3 20h18M4 20V4"/><path d="M5 17l4-7 3 4 4-8"/>'
                     f'<path d="M18 13v6M15 16h6" stroke="{GREEN}"/>'),
    "delete_point": svg('<path d="M3 20h18M4 20V4"/><path d="M5 17l4-7 3 4 4-8"/>'
                        f'<path d="M16 14l5 5M21 14l-5 5" stroke="{RED}"/>'),
    "duplicate": svg('<rect x="8" y="8" width="12" height="12" rx="1"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>'),
    "sort": svg('<path d="M7 4v16M4 17l3 3 3-3"/><path d="M13 6h7M13 11h5M13 16h3"/>'),
    "analyze": svg('<path d="M3 20h18M4 20V4"/><path d="M5 18c2-10 4-12 6-12s3 8 5 8 3-3 4-3"/>'
                   f'<circle cx="17" cy="7" r="3" stroke="{ORANGE}"/><path d="M19.2 9.2L21 11" stroke="{ORANGE}"/>'),
    "digitize": svg('<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M6 16l4-6 3 3 5-6"/>'
                    f'<circle cx="10" cy="10" r="1.3" stroke="{RED}"/><circle cx="13" cy="13" r="1.3" stroke="{RED}"/>'
                    f'<circle cx="18" cy="7" r="1.3" stroke="{RED}"/>'),
    "label": svg('<path d="M3 7a2 2 0 0 1 2-2h10l6 7-6 7H5a2 2 0 0 1-2-2z"/><path d="M7 10h6M7 14h4"/>'),
    "undo": svg('<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>'),
    "redo": svg('<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>'),
    "zoom_reset": svg('<circle cx="10" cy="10" r="6"/><path d="M15 15l5 5"/><path d="M7 10h6"/>'),
    "grid": svg('<rect x="3" y="3" width="18" height="18" rx="1"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/>', GREY),
    "print": svg('<path d="M7 8V3h10v5"/><rect x="3" y="8" width="18" height="9" rx="1.5"/><path d="M7 14h10v7H7z"/>'),
    "pdf": svg('<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>'
               f'<path d="M8 17v-4h1.5a1.2 1.2 0 0 1 0 2.4H8M13 13v4M13 13h2M13 15h1.5" stroke="{RED}"/>'),
    "image": svg('<rect x="3" y="4" width="18" height="16" rx="1.5"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M21 16l-5-5-9 9"/>'),
    "settings": svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>', GREY),
    "validate": svg(f'<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5" stroke="{GREEN}"/>'),
    "help": svg('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 1-1 1.7v.5"/><path d="M12 17h.01"/>'),
    "manual": svg('<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H20v16H5.5A1.5 1.5 0 0 0 4 20.5z"/><path d="M4 20.5A1.5 1.5 0 0 0 5.5 22H20v-3"/><path d="M8 7h8M8 11h6"/>'),
    "info": svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>'),
    "exit": svg('<path d="M14 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/>'),
    "csv": svg('<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>'
               f'<path d="M8 12h8M8 15h8M8 18h8M11 12v6" stroke="{GREEN}"/>'),
    "eng": svg('<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>'
               f'<path d="M7.5 18l2.5-6 2 3.5 2-2 2 4.5" stroke="{ORANGE}"/>'),
    "crop": svg('<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>'),
    "rotate": svg('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
    "perspective": svg('<path d="M6 5l12 2 2 12-16 1z"/><circle cx="6" cy="5" r="1.2"/><circle cx="18" cy="7" r="1.2"/><circle cx="20" cy="19" r="1.2"/><circle cx="4" cy="20" r="1.2"/>'),
    "target": svg(f'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2" stroke="{RED}"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>'),
    "pipette": svg('<path d="M14 6l4 4M17 3a2.1 2.1 0 0 1 3 3l-2 2-3-3z"/><path d="M15 9L6 18l-3 3 3-3 9-9"/>'),
    "transfer": svg(f'<path d="M4 12h13M13 7l5 5-5 5" stroke="{GREEN}"/><path d="M20 4v16"/>'),
    "app": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1F4E79"/>'
        '<stop offset="1" stop-color="#0B2540"/></linearGradient>'
        '<linearGradient id="flame" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFD166"/>'
        '<stop offset="1" stop-color="#E63946"/></linearGradient></defs>'
        '<rect x="8" y="8" width="240" height="240" rx="52" fill="url(#bg)"/>'
        '<path d="M40 206 C70 190 82 120 104 112 S140 170 162 160 S196 120 216 118" fill="none" '
        'stroke="#4FC3F7" stroke-width="9" stroke-linecap="round" opacity="0.85"/>'
        '<g transform="rotate(35 128 120)">'
        '<path d="M128 30 C150 52 156 84 156 120 L156 168 L100 168 L100 120 C100 84 106 52 128 30 Z" fill="#F1F5F9"/>'
        '<circle cx="128" cy="96" r="12" fill="#1F4E79" stroke="#4FC3F7" stroke-width="4"/>'
        '<path d="M100 132 L78 170 L100 166 Z M156 132 L178 170 L156 166 Z" fill="#E63946"/>'
        '<path d="M108 170 L148 170 L140 186 L116 186 Z" fill="#94A3B8"/>'
        '<path d="M114 188 C114 210 128 228 128 232 C128 228 142 210 142 188 Z" fill="url(#flame)"/>'
        "</g></svg>\n"
    ),
}


def write_svgs() -> None:
    """Write every SVG icon to resources/icons."""
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in ICONS.items():
        (ICON_DIR / f"{name}.svg").write_text(content, encoding="utf-8")
    print(f"{len(ICONS)} SVG icons written to {ICON_DIR}")


def write_app_icon() -> None:
    """Render the application SVG to PNG and ICO (needs PyQt6 + Pillow)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 - must stay alive
    renderer = QSvgRenderer(str(ICON_DIR / "app.svg"))
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    png_path = ICON_DIR / "app.png"
    image.save(str(png_path))
    Image.open(png_path).save(
        ICON_DIR / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print("app.png and app.ico written")


if __name__ == "__main__":
    write_svgs()
    write_app_icon()
