"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Qt tests run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.motor import Motor  # noqa: E402
from models.motor_metadata import MotorMetadata  # noqa: E402
from models.thrust_point import ThrustPoint  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / "data"


@pytest.fixture
def data_dir() -> Path:
    """Folder containing the reference test files."""
    return DATA_DIR


@pytest.fixture
def triangle_motor() -> Motor:
    """A motor whose triangular curve has an exact analytical impulse:
    0 -> 10 N at 1 s -> 0 at 2 s : I = 10 N.s, avg = 5 N."""
    meta = MotorMetadata(
        name="T10", manufacturer="TestCo", designation="T10-3", diameter_mm=18.0, length_mm=70.0,
        delays="3", propellant_mass_g=10.0, casing_mass_g=12.0, nozzle_closure_mass_g=3.0,
        propellant_type="Black powder",
    )
    points = [ThrustPoint(0.0, 0.0), ThrustPoint(1.0, 10.0), ThrustPoint(2.0, 0.0)]
    return Motor(metadata=meta, points=points)


@pytest.fixture(scope="session")
def qapp():
    """A QApplication shared by Qt tests (offscreen)."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


_slot_errors: list[str] = []


def _record_exception(exc_type, exc, tb):
    """PyQt6 aborts on exceptions raised in slots unless a hook exists:
    record them so the test fails cleanly instead."""
    import traceback

    _slot_errors.append("".join(traceback.format_exception(exc_type, exc, tb)))


sys.excepthook = _record_exception


@pytest.fixture(autouse=True)
def no_slot_exceptions():
    """Fail a test when an exception was raised inside a Qt slot."""
    _slot_errors.clear()
    yield
    if _slot_errors:
        errors = "\n".join(_slot_errors)
        _slot_errors.clear()
        pytest.fail(f"Exception raised in a Qt slot:\n{errors}")


@pytest.fixture(autouse=True)
def non_blocking_dialogs(monkeypatch):
    """Answer every modal message box automatically during tests and
    record the messages shown by the error reporter."""
    try:
        from PyQt6.QtWidgets import QMessageBox
    except ImportError:  # pragma: no cover - Qt always installed for these tests
        yield []
        return
    shown: list[str] = []
    yes = QMessageBox.StandardButton.Yes
    for name in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *args, **kwargs: (shown.append(str(args[2:3])), yes)[1]))
    from application import error_handler

    monkeypatch.setattr(error_handler.ErrorReporter, "_message_box",
                        staticmethod(lambda parent, icon, title, message: shown.append(f"{title}: {message}")))
    yield shown
