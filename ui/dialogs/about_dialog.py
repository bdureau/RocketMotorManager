"""About dialog."""

from __future__ import annotations

from localization import _

import platform
import sys
from typing import Optional

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from application.paths import log_dir
from application.version import APP_COPYRIGHT, APP_DESCRIPTION, APP_NAME, APP_VERSION
from ui.common import icon


class AboutDialog(QDialog):
    """Application name, version, copyright and environment."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("About {app}").format(app=APP_NAME))
        logo = QLabel()
        logo.setPixmap(icon("app").pixmap(96, 96))
        logo.setAlignment(Qt.AlignmentFlag.AlignTop)
        text = QLabel(
            f"<h2>{APP_NAME}</h2><p><b>{_('Version {version}').format(version=APP_VERSION)}</b></p><p>{_(APP_DESCRIPTION)}</p>"
            f"<p>{APP_COPYRIGHT}</p>"
            f"<p style='color:gray;font-size:8pt'>Python {platform.python_version()} · Qt {QT_VERSION_STR} · "
            f"PyQt {PYQT_VERSION_STR} · {platform.system()} {platform.release()}<br>"
            f"{_('Log folder: {path}').format(path=log_dir())}<br>{_('Executable: {path}').format(path=sys.executable)}</p>"
        )
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setMinimumWidth(380)
        row = QHBoxLayout()
        row.addWidget(logo)
        row.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(buttons)
