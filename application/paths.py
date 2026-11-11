"""Filesystem locations (user folders and bundled resources).

On Windows:

* preferences and user templates: ``%APPDATA%\\RocketMotorManager``
* logs: ``%LOCALAPPDATA%\\RocketMotorManager\\logs``

On other systems the XDG equivalents are used.

Resources (``resources/...``, ``documentation/...``) are looked up, file by
file, in this order:

1. next to the executable, for a PyInstaller build whose ``resources`` and
   ``documentation`` folders are delivered beside the ``.exe``;
2. inside the PyInstaller bundle (``sys._MEIPASS``: the ``_internal`` folder
   of a one-folder build, or the temporary folder of a ``--onefile`` build);
3. in the source tree.

The same executable therefore works whether the resources are embedded or
external, and an external file overrides an embedded one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from application.version import APP_ID


def source_root() -> Path:
    """Root folder of the source tree."""
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """Root folder of the embedded application files (bundle or source tree)."""
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else source_root()


def resource_roots() -> list[Path]:
    """Folders searched for resources, by priority (see the module docstring)."""
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.append(Path(bundle))
    roots.append(source_root())
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def resource_path(*parts: str) -> Path:
    """Absolute path of a resource, e.g. ``resource_path("resources", "icons", "new.svg")``:
    the first existing candidate of :func:`resource_roots`, else the path in
    the first root (so error messages show where the file was expected)."""
    roots = resource_roots()
    for root in roots:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return roots[0].joinpath(*parts)


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
