"""Internationalisation with GNU gettext (``.po`` / ``.mo`` files).

Every user-visible string of the application is written in English and
marked with one of these functions:

* ``_("text")`` – translate now;
* ``ngettext("{n} point", "{n} points", n)`` – plural forms;
* ``N_("text")`` – mark a string stored in a constant (translated later
  with ``_()`` when it is displayed).

Placeholders use ``str.format`` names (``{name}``) so translators can
reorder them freely.

Catalogues: ``resources/locale/<lang>/LC_MESSAGES/rocketmotormanager.po``
(compiled to ``.mo`` by ``tools/build_translations.py``). The template
``resources/locale/rocketmotormanager.pot`` is extracted from the sources
with Babel. This module only uses the standard library, so the business
layer (``models``, ``services``) can use it without depending on Qt.
"""

from __future__ import annotations

import gettext as _gettext
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DOMAIN = "rocketmotormanager"
DEFAULT_LANGUAGE = "en"

#: Supported languages: code -> native name.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Português",
    "ru": "Русский",
}

_translation: _gettext.NullTranslations = _gettext.NullTranslations()
_language = DEFAULT_LANGUAGE


def locale_dir() -> Path:
    """Folder containing ``<lang>/LC_MESSAGES/rocketmotormanager.mo``: next
    to the executable, in the PyInstaller bundle or in the source tree (see
    :mod:`application.paths`, which only uses the standard library)."""
    from application.paths import resource_path

    return resource_path("resources", "locale")


def available_languages() -> dict[str, str]:
    """English plus every language whose compiled catalogue exists."""
    result = {DEFAULT_LANGUAGE: LANGUAGES[DEFAULT_LANGUAGE]}
    for code, name in LANGUAGES.items():
        if (locale_dir() / code / "LC_MESSAGES" / f"{DOMAIN}.mo").exists():
            result[code] = name
    return result


def install(language: str, directory: Optional[Path] = None) -> bool:
    """Activate a language. Returns False (English kept) when no catalogue
    is found. Must be called before the user interface is created."""
    global _translation, _language  # the active catalogue is process-wide by design
    _language = language or DEFAULT_LANGUAGE
    if _language == DEFAULT_LANGUAGE:
        _translation = _gettext.NullTranslations()
        return True
    try:
        _translation = _gettext.translation(DOMAIN, str(directory or locale_dir()), languages=[_language])
    except OSError:
        logger.warning("No translation catalogue for language '%s'", _language)
        _translation = _gettext.NullTranslations()
        _language = DEFAULT_LANGUAGE
        return False
    logger.info("Language '%s' installed", _language)
    return True


def current_language() -> str:
    """Code of the active language."""
    return _language


def _(message: str) -> str:
    """Translate a message."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Translate a message with plural forms (``count`` selects the form).
    The result usually contains ``{n}``: call ``.format(n=count)``."""
    return _translation.ngettext(singular, plural, count)


def pgettext(context: str, message: str) -> str:
    """Translate a message with a disambiguation context."""
    return _translation.pgettext(context, message)


def N_(message: str) -> str:  # noqa: N802 - gettext convention
    """Mark a string for extraction without translating it now."""
    return message
