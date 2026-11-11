"""Tests of the gettext catalogues (.po / .mo) and of the translated UI."""

from __future__ import annotations

import gettext
from pathlib import Path

import pytest

import localization
from localization import DOMAIN, LANGUAGES, locale_dir

babel = pytest.importorskip("babel")
from babel.messages.pofile import read_po  # noqa: E402

from tools.build_translations import KEYWORDS, SOURCE_DIRS, _placeholders, po_path  # noqa: E402

TRANSLATED = [code for code in LANGUAGES if code != "en"]
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def english_afterwards():
    """Every test leaves the application in English."""
    yield
    localization.install("en")


def _catalog(language):
    with po_path(language).open("rb") as handle:
        return read_po(handle, locale=language)


def _source_messages() -> set[str]:
    from babel.messages.extract import extract_from_dir

    messages = set()
    for folder in SOURCE_DIRS:
        for _filename, _lineno, message, _comments, _context in extract_from_dir(
            ROOT / folder, method_map=[("**.py", "python")], keywords=KEYWORDS
        ):
            messages.add(message if isinstance(message, str) else message[0])
    return messages


def test_all_languages_available():
    assert set(localization.available_languages()) == set(LANGUAGES)


@pytest.mark.parametrize("language", TRANSLATED)
def test_catalogue_complete_and_placeholders_kept(language):
    catalog = _catalog(language)
    assert catalog.num_plurals == (3 if language in ("pl", "ru") else 2)
    for message in catalog:
        if not message.id:
            continue
        assert not message.fuzzy, message.id
        ids = message.id if isinstance(message.id, (tuple, list)) else (message.id,)
        strings = message.string if isinstance(message.string, (tuple, list)) else (message.string,)
        assert all(strings), f"untranslated: {ids[0]!r}"
        expected = set().union(*(_placeholders(i) for i in ids))
        for text in strings:
            assert _placeholders(text) == expected, (ids[0], text)
            assert text.count("&") == ids[0].count("&") or "&" not in ids[0], (ids[0], text)
            text.format(**{name: "x" for name in expected | {"n"}})  # every placeholder is formattable


@pytest.mark.parametrize("language", TRANSLATED)
def test_catalogue_up_to_date_with_sources(language):
    catalog_ids = {m.id if isinstance(m.id, str) else m.id[0] for m in _catalog(language) if m.id}
    missing = _source_messages() - catalog_ids
    assert not missing, f"run tools/build_translations.py: {sorted(missing)[:5]}"


@pytest.mark.parametrize("language", TRANSLATED)
def test_compiled_mo_matches_po(language):
    mo_file = locale_dir() / language / "LC_MESSAGES" / f"{DOMAIN}.mo"
    translation = gettext.GNUTranslations(mo_file.open("rb"))
    for message in _catalog(language):
        if message.id and isinstance(message.id, str):
            assert translation.gettext(message.id) == message.string, "recompile the .mo files"


def test_plural_forms():
    localization.install("pl")
    forms = [localization.ngettext("{n} point", "{n} points", n).format(n=n) for n in (1, 2, 5, 22, 25)]
    assert forms == ["1 punkt", "2 punkty", "5 punktów", "22 punkty", "25 punktów"]
    localization.install("ru")
    assert localization.ngettext("{n} point", "{n} points", 21).format(n=21) == "21 точка"


def test_unknown_language_falls_back_to_english():
    assert not localization.install("xx")
    assert localization.current_language() == "en"
    assert localization._("&File") == "&File"


def test_business_messages_are_translated(triangle_motor):
    from models.validation import validate_metadata

    localization.install("fr")
    triangle_motor.metadata.name = ""
    report = validate_metadata(triangle_motor)
    assert "Le nom du moteur est obligatoire." in report.summary()
    assert "[ERREUR]" in report.summary()


@pytest.mark.parametrize("language", TRANSLATED)
def test_main_window_in_every_language(qapp, tmp_path, language, data_dir):
    from application.application_controller import ApplicationController
    from application.configuration import ConfigurationManager

    localization.install(language)
    from ui.main_window import MainWindow

    controller = ApplicationController(ConfigurationManager(tmp_path / "prefs.json"))
    window = MainWindow(controller)
    titles = [action.text() for action in window.menuBar().actions()]
    assert titles[0] == localization._("&File")
    assert titles[1] == localization._("&Edit") and titles[1] != "&Edit"
    controller.load_imported_motor(controller.read_eng(str(data_dir / "sample_C6.eng")).motors[0])
    assert window.thrust_editor.plot.axes.get_xlabel() == localization._("Time (s)")
    from PyQt6.QtCore import Qt

    assert window.thrust_editor.table.model.headerData(1, Qt.Orientation.Horizontal) == localization._("Thrust (N)")
    controller.document.mark_saved("")
    window.close()
