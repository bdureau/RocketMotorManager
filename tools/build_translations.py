"""Manage the gettext catalogues of Rocket Motor Manager.

Two catalogues (gettext *domains*) are managed:

* ``rocketmotormanager`` – the application texts, extracted from the
  sources (``resources/locale``, loaded by the application at run time);
* ``manual`` – the user manual texts, extracted from
  ``tools/generate_manual.py`` (``documentation/locale``, used only to
  generate the PDF manuals).

Run from the project root (requires Babel: ``pip install babel``)::

    python tools/build_translations.py                    # extract + update + check + compile (both domains)
    python tools/build_translations.py extract [domain]   # sources -> .pot template
    python tools/build_translations.py update [domain]    # .pot -> every <lang>/LC_MESSAGES/<domain>.po
    python tools/build_translations.py check [domain] [--strict]
    python tools/build_translations.py compile [domain]   # .po -> .mo
    python tools/build_translations.py init xx            # start a new language (both domains)

Translators edit the ``.po`` files with any PO editor (Poedit, Lokalize,
a text editor...). Placeholders such as ``{path}`` and interface
references such as ``[[&File]]`` (manual only) must be kept unchanged;
their order may change.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from babel import Locale
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir, extract_from_file
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from application.version import APP_AUTHOR, APP_NAME, APP_VERSION  # noqa: E402
from localization import DOMAIN, LANGUAGES  # noqa: E402

KEYWORDS = {"_": None, "N_": None, "ngettext": (1, 2), "pgettext": ((1, "c"), 2)}
PLACEHOLDER = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")
UI_REFERENCE = re.compile(r"\[\[(.+?)\]\]")


@dataclass(frozen=True)
class Domain:
    """A gettext catalogue: where its sources and its files are."""

    name: str
    locale_dir: Path
    sources: tuple[str, ...]  # folders or single .py files, relative to ROOT

    @property
    def pot_file(self) -> Path:
        return self.locale_dir / f"{self.name}.pot"

    def po_path(self, language: str) -> Path:
        return self.locale_dir / language / "LC_MESSAGES" / f"{self.name}.po"


APP_DOMAIN = Domain(DOMAIN, ROOT / "resources" / "locale", ("application", "models", "services", "ui", "widgets"))
MANUAL_DOMAIN = Domain("manual", ROOT / "documentation" / "locale", ("tools/generate_manual.py",))
DOMAINS = {APP_DOMAIN.name: APP_DOMAIN, MANUAL_DOMAIN.name: MANUAL_DOMAIN}

# Backward-compatible helpers for the application catalogue.
LOCALE_DIR = APP_DOMAIN.locale_dir
POT_FILE = APP_DOMAIN.pot_file
SOURCE_DIRS = APP_DOMAIN.sources


def po_path(language: str, domain: Domain = APP_DOMAIN) -> Path:
    """Path of the .po file of a language."""
    return domain.po_path(language)


def _new_catalog(domain: Domain, locale: str | None = None) -> Catalog:
    return Catalog(locale=locale, domain=domain.name, project=APP_NAME, version=APP_VERSION,
                   copyright_holder=APP_AUTHOR, msgid_bugs_address="", charset="utf-8",
                   creation_date=datetime.now(timezone.utc), fuzzy=False)


def _first(message) -> str:
    return message if isinstance(message, str) else message[0]


def _extracted(domain: Domain):
    """Yield (location, lineno, message, comments, context) for a domain."""
    for source in domain.sources:
        path = ROOT / source
        if path.is_dir():
            for filename, lineno, message, comments, context in extract_from_dir(
                path, method_map=[("**.py", "python")], keywords=KEYWORDS, comment_tags=("Translators:",),
                strip_comment_tags=True,
            ):
                yield f"{source}/{filename}", lineno, message, comments, context
        else:
            for lineno, message, comments, context in extract_from_file(
                "python", path, keywords=KEYWORDS, comment_tags=("Translators:",), strip_comment_tags=True,
            ):
                yield source, lineno, message, comments, context


def source_messages(domain: Domain = APP_DOMAIN) -> set[str]:
    """Every message currently marked in the sources of a domain."""
    return {_first(message) for _loc, _line, message, _comments, _context in _extracted(domain)}


def extract(domain: Domain = APP_DOMAIN) -> Catalog:
    """Extract every marked string of the sources into the .pot template."""
    catalog = _new_catalog(domain)
    for location, lineno, message, comments, context in _extracted(domain):
        flags = ("python-brace-format",) if _placeholders(_first(message)) else ()
        catalog.add(message, None, [(location, lineno)], auto_comments=comments, context=context, flags=flags)
    domain.locale_dir.mkdir(parents=True, exist_ok=True)
    with domain.pot_file.open("wb") as handle:
        write_po(handle, catalog, width=100, sort_by_file=True)
    print(f"{len(catalog)} messages extracted to {domain.pot_file.relative_to(ROOT)}")
    return catalog


def _read(path: Path, domain: Domain, locale: str | None = None) -> Catalog:
    with path.open("rb") as handle:
        return read_po(handle, locale=locale, domain=domain.name)


def _write(path: Path, catalog: Catalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        write_po(handle, catalog, width=100, sort_by_file=True, include_previous=True)


def init(language: str, domain: Domain = APP_DOMAIN) -> None:
    """Create the .po file of a new language from the template."""
    template = _read(domain.pot_file, domain)
    catalog = _new_catalog(domain, language)
    catalog.update(template)
    catalog.language_team = Locale.parse(language).english_name
    catalog.last_translator = APP_AUTHOR
    _write(domain.po_path(language), catalog)
    print(f"Created {domain.po_path(language).relative_to(ROOT)}")


def update(domain: Domain = APP_DOMAIN) -> None:
    """Merge the template into every existing .po (translations are kept,
    changed messages become fuzzy, removed ones obsolete)."""
    template = _read(domain.pot_file, domain)
    for language in LANGUAGES:
        if language == "en":
            continue
        path = domain.po_path(language)
        if not path.exists():
            init(language, domain)
            continue
        catalog = _read(path, domain, language)
        catalog.update(template, no_fuzzy_matching=False)
        _write(path, catalog)
    print(f"Catalogues '{domain.name}' updated")


def _placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text or ""))


def ui_references(text: str) -> list[str]:
    """Interface references ``[[...]]`` of a manual text (sorted)."""
    return sorted(UI_REFERENCE.findall(text or ""))


def check(domain: Domain = APP_DOMAIN, strict: bool = False) -> int:
    """Report untranslated and fuzzy messages and placeholder / interface
    reference mismatches. Returns the number of blocking problems."""
    problems = 0
    for language in LANGUAGES:
        if language == "en" or not domain.po_path(language).exists():
            continue
        catalog = _read(domain.po_path(language), domain, language)
        missing = fuzzy = 0
        for message in catalog:
            if not message.id:
                continue
            ids = message.id if isinstance(message.id, (tuple, list)) else (message.id,)
            strings = message.string if isinstance(message.string, (tuple, list)) else (message.string,)
            if message.fuzzy:
                fuzzy += 1
            if not all(strings):
                missing += 1
                continue
            expected = set().union(*(_placeholders(i) for i in ids))
            for text in strings:
                if _placeholders(text) != expected:
                    problems += 1
                    print(f"  [{domain.name}/{language}] placeholder mismatch: {ids[0]!r} -> {text!r}")
                if ui_references(text) != ui_references(ids[0]):
                    problems += 1
                    print(f"  [{domain.name}/{language}] interface reference mismatch: {ids[0]!r} -> {text!r}")
        total = sum(1 for m in catalog if m.id)
        print(f"{domain.name}/{language}: {total - missing}/{total} translated, {fuzzy} fuzzy")
        if strict:
            problems += missing + fuzzy
    return problems


def compile_all(domain: Domain = APP_DOMAIN) -> None:
    """Compile every .po into its .mo."""
    for language in LANGUAGES:
        path = domain.po_path(language)
        if language == "en" or not path.exists():
            continue
        catalog = _read(path, domain, language)
        with path.with_suffix(".mo").open("wb") as handle:
            write_mo(handle, catalog, use_fuzzy=False)
    print(f"Catalogues '{domain.name}' compiled")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    command = args[0] if args else "all"
    if command == "init" and len(args) > 1:
        for domain in DOMAINS.values():
            init(args[1], domain)
        return 0
    selected = [DOMAINS[args[1]]] if len(args) > 1 and args[1] in DOMAINS else list(DOMAINS.values())
    status = 0
    for domain in selected:
        if command == "extract":
            extract(domain)
        elif command == "update":
            update(domain)
        elif command == "check":
            status |= 1 if check(domain, strict="--strict" in argv) else 0
        elif command == "compile":
            compile_all(domain)
        elif command == "all":
            extract(domain)
            update(domain)
            if check(domain):
                return 1
            compile_all(domain)
        else:
            print(__doc__)
            return 2
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
