"""Tests of the resource lookup (source tree, PyInstaller bundle, beside the executable)."""

from __future__ import annotations

import sys

from application import paths


def _make(root, *parts):
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return path


def test_source_tree_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert paths.resource_roots() == [paths.source_root()]
    assert paths.resource_path("resources", "icons", "app.ico").exists()


def test_external_resources_beside_executable(monkeypatch, tmp_path):
    exe_dir, bundle = tmp_path / "dist", tmp_path / "meipass"
    beside = _make(exe_dir, "resources", "icons", "new.svg")
    _make(bundle, "resources", "icons", "new.svg")
    embedded_only = _make(bundle, "documentation", "user_manual_en.pdf")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "RocketMotorManager.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert paths.resource_roots()[:2] == [exe_dir.resolve(), bundle]
    # the external file wins, an embedded-only file is still found
    assert paths.resource_path("resources", "icons", "new.svg") == beside.resolve()
    assert paths.resource_path("documentation", "user_manual_en.pdf") == embedded_only
    # a missing file is reported where it was expected first (beside the .exe)
    assert paths.resource_path("resources", "missing.png") == exe_dir.resolve() / "resources" / "missing.png"


def test_locale_dir_follows_resource_lookup(monkeypatch, tmp_path):
    import localization

    exe_dir = tmp_path / "dist"
    (exe_dir / "resources" / "locale").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "RocketMotorManager.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert localization.locale_dir() == (exe_dir / "resources" / "locale").resolve()
