"""User preferences persisted as JSON between sessions."""

from __future__ import annotations


import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

from application.paths import config_dir, documents_dir
from services.file_utils import atomic_write_text

logger = logging.getLogger(__name__)

PREFERENCES_FILE = "preferences.json"
MAX_RECENT_FILES = 10


@dataclass
class Preferences:
    """Every user-configurable setting with its default value."""

    language: str = "en"
    theme: str = "light"  # light | dark
    unit_system: str = "metric"  # metric | imperial
    decimal_separator: str = "."
    burn_time_method: str = "curve"
    plot_line_color: str = "#1F77B4"
    plot_marker_color: str = "#D62728"
    plot_fill_under_curve: bool = True
    plot_show_markers: bool = True
    show_grid: bool = True
    default_save_dir: str = field(default_factory=lambda: str(documents_dir()))
    import_dir: str = field(default_factory=lambda: str(documents_dir()))
    print_paper_format: str = "A4"
    print_dpi: int = 300
    label_default_template: str = "Classic"
    recent_files: list[str] = field(default_factory=list)
    window_geometry: str = ""
    window_state: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preferences":
        """Create preferences from a dict, keeping defaults for missing or
        mistyped entries (a damaged file never prevents start-up)."""
        prefs = cls()
        for spec in fields(cls):
            if spec.name not in data:
                continue
            value, default = data[spec.name], getattr(prefs, spec.name)
            if isinstance(default, bool) and not isinstance(value, bool):
                continue
            if isinstance(default, int) and not isinstance(default, bool):
                if not isinstance(value, int) or isinstance(value, bool):
                    continue
            if isinstance(default, str) and not isinstance(value, str):
                continue
            if isinstance(default, list):
                if not isinstance(value, list):
                    continue
                value = [str(item) for item in value]
            setattr(prefs, spec.name, value)
        return prefs


class ConfigurationManager:
    """Load, save and reset :class:`Preferences`."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or config_dir() / PREFERENCES_FILE
        self.preferences = Preferences()

    def load(self) -> Preferences:
        """Load preferences from disk (defaults when absent or invalid)."""
        if not self.path.exists():
            logger.info("No preferences file, using defaults")
            self.preferences = Preferences()
            return self.preferences
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root is not an object")
            self.preferences = Preferences.from_dict(data)
        except (OSError, ValueError) as exc:
            logger.warning("Invalid preferences file %s (%s); defaults restored", self.path, exc)
            self.preferences = Preferences()
        return self.preferences

    def save(self) -> None:
        """Write preferences to disk (errors are logged, never raised)."""
        try:
            atomic_write_text(self.path, json.dumps(asdict(self.preferences), indent=2))
        except Exception as exc:  # preferences must never crash the app
            logger.error("Cannot save preferences: %s", exc)

    def reset(self) -> Preferences:
        """Restore defaults (recent files and window layout are kept)."""
        recent = self.preferences.recent_files
        geometry, state = self.preferences.window_geometry, self.preferences.window_state
        self.preferences = Preferences(recent_files=recent, window_geometry=geometry, window_state=state)
        return self.preferences

    def add_recent_file(self, path: str) -> None:
        """Move ``path`` to the top of the recent files list."""
        normalized = str(Path(path))
        recent = [p for p in self.preferences.recent_files if Path(p) != Path(normalized)]
        self.preferences.recent_files = [normalized] + recent[: MAX_RECENT_FILES - 1]

    def remove_recent_file(self, path: str) -> None:
        """Remove a path from the recent files list."""
        self.preferences.recent_files = [p for p in self.preferences.recent_files if Path(p) != Path(path)]
