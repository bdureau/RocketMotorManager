"""Tests of the translated user manuals and of Help > Manual."""

from __future__ import annotations

from pathlib import Path

import pytest

import localization
from localization import LANGUAGES

babel = pytest.importorskip("babel")
from babel.messages.pofile import read_po  # noqa: E402

from tools.build_translations import (  # noqa: E402
    APP_DOMAIN, MANUAL_DOMAIN, _placeholders, source_messages, ui_references,
)

ROOT = Path(__file__).resolve().parent.parent
TRANSLATED = [code for code in LANGUAGES if code != "en"]


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    localization.install("en")


def _read(path: Path, language: str | None = None):
    with path.open("rb") as handle:
        return read_po(handle, locale=language)


def test_manual_ui_references_exist_in_application_catalogue():
    """Every [[a|b]] reference of the manual names a real interface caption."""
    app_ids = {m.id for m in _read(APP_DOMAIN.pot_file) if m.id}
    manual_ids = [m.id for m in _read(MANUAL_DOMAIN.pot_file) if m.id]
    references = {part for msgid in manual_ids for ref in ui_references(msgid) for part in ref.split("|")}
    assert references, "the manual should reference interface elements"
    assert sorted(references - app_ids) == []


def test_manual_template_up_to_date():
    template = {m.id for m in _read(MANUAL_DOMAIN.pot_file) if m.id}
    assert source_messages(MANUAL_DOMAIN) == template


@pytest.mark.parametrize("language", TRANSLATED)
def test_manual_catalogue_complete(language):
    catalog = _read(MANUAL_DOMAIN.po_path(language), language)
    for message in catalog:
        if not message.id:
            continue
        assert message.string, f"{language}: untranslated {message.id!r}"
        assert not message.fuzzy, f"{language}: fuzzy {message.id!r}"
        assert _placeholders(message.string) == _placeholders(message.id), message.id
        assert ui_references(message.string) == ui_references(message.id), message.id
        assert message.string.count("<b>") == message.string.count("</b>"), message.string
        assert message.string.count("<i>") == message.string.count("</i>"), message.string
    assert MANUAL_DOMAIN.po_path(language).with_suffix(".mo").exists()


@pytest.mark.parametrize("language", list(LANGUAGES))
def test_manual_pdf_exists(language):
    pdf = ROOT / "documentation" / f"user_manual_{language}.pdf"
    assert pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-"


def test_ui_references_resolved_with_interface_translation():
    from tools import generate_manual as gm

    gm.set_language("fr")
    assert gm.resolve_ui_references("<b>[[&File|&New Motor]]</b>") == "<b>{} &gt; {}</b>".format(
        localization._("&File").replace("&", ""), localization._("&New Motor").replace("&", ""))
    assert gm.ui_caption("Import &ENG...") == localization._("Import &ENG...").replace("&", "").rstrip(".")
    assert gm._("User manual") == "Manuel utilisateur"
    gm.set_language("en")
    assert gm.resolve_ui_references("[[&File|Import &ENG...]]") == "File &gt; Import ENG"


@pytest.mark.parametrize("language", ["fr", "ru"])
def test_open_manual_uses_interface_language(qapp, monkeypatch, language):
    from PyQt6.QtGui import QDesktopServices

    from application.application_controller import ApplicationController
    from ui import main_window as mw

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))
    localization.install(language)
    window = mw.MainWindow(ApplicationController())
    try:
        window.open_manual()
    finally:
        window.controller.document.mark_saved("")
        window.close()
    assert len(opened) == 1 and Path(opened[0]).name == f"user_manual_{language}.pdf"


def test_manual_falls_back_to_english(monkeypatch, tmp_path):
    from ui import main_window as mw

    (tmp_path / "documentation").mkdir()
    (tmp_path / "documentation" / "user_manual_en.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(mw, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    assert mw.manual_path("pl").name == "user_manual_en.pdf"
    (tmp_path / "documentation" / "user_manual_pl.pdf").write_bytes(b"%PDF-1.4")
    assert mw.manual_path("pl").name == "user_manual_pl.pdf"
