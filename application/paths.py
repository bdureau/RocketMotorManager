"""Filesystem locations (user folders and bundled resources).

On Windows:

* preferences and user templates: ``%APPDATA%\\RocketMotorManager``
* logs: ``%LOCALAPPDATA%\\RocketMotorManager\\logs``

On other systems the XDG equivalents are used. Bundled resources are found
next to the sources, or inside the PyInstaller bundle (``sys._MEIPASS``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from application.version import APP_ID


def project_root() -> Path:
    """Root folder of the application files (source tree or bundle)."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path of a bundled resource, e.g. ``resource_path("resources", "icons", "new.svg")``."""
    return project_root().joinpath(*parts)


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Folder holding the preferences file and the user templates."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return _ensure(base / APP_ID)


def log_dir() -> Path:
    """Folder holding the technical log files."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return _ensure(base / APP_ID / "logs")
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return _ensure(base / APP_ID / "logs")


def user_templates_dir() -> Path:
    """Folder holding the label templates saved by the user."""
    return _ensure(config_dir() / "label_templates")


def documents_dir() -> Path:
    """Default folder for projects and exports (the user's Documents)."""
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()
