"""Check that a PyInstaller build contains every resource of Rocket Motor Manager.

Run from the project root, after the build::

    python tools/check_bundle.py dist\\RocketMotorManager.exe    # --onefile build
    python tools/check_bundle.py dist\\RocketMotorManager         # one-folder build

A resource may be embedded in the executable or delivered beside it, in the
``resources`` and ``documentation`` folders next to the ``.exe`` (the
application looks there first, see ``application/paths.py``); both are
accepted and the report says where each group of files was found.

The expected files are taken from the source tree (icons, label templates,
images, compiled translations, PDF manuals, technical documentation), so a
resource added later is checked automatically. The modules that PyInstaller
cannot detect by itself (loaded dynamically by pandas, Matplotlib or Qt) are
checked too. Exit code 0 when the build is complete, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Folders copied as they are (destination = same relative path).
RESOURCE_FOLDERS = ("resources/icons", "resources/templates", "resources/images")
#: Modules imported dynamically, which must be passed with --hidden-import.
HIDDEN_IMPORTS = (
    "openpyxl", "xlrd", "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_svg", "scipy.signal",
)
#: Qt modules (binary extensions) used by the application.
QT_MODULES = ("QtSvg", "QtPrintSupport")


def expected_files() -> list[str]:
    """Relative paths (with '/') that the bundle must contain."""
    files: list[Path] = []
    for folder in RESOURCE_FOLDERS:
        files += [p for p in (ROOT / folder).rglob("*") if p.is_file()]
    files += sorted((ROOT / "resources" / "locale").rglob("*.mo"))
    files += sorted((ROOT / "documentation").glob("user_manual_*.pdf"))
    files.append(ROOT / "documentation" / "technical_documentation.html")
    return sorted(p.relative_to(ROOT).as_posix() for p in files if "__pycache__" not in p.parts)


def _normalise(name: str) -> str:
    return name.replace("\\", "/")


def onefile_contents(exe: Path) -> tuple[set[str], set[str]]:
    """(files, python modules) stored in a --onefile executable."""
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    files = {_normalise(name) for name in archive.toc}
    modules: set[str] = set()
    for name in archive.toc:
        if name.endswith(".pyz") or name == "PYZ.pyz" or name.startswith("PYZ"):
            modules |= set(archive.open_embedded_archive(name).toc)
    return files, modules


def onedir_contents(folder: Path) -> tuple[set[str], set[str]]:
    """(files, python modules) of a one-folder build."""
    internal = folder / "_internal" if (folder / "_internal").is_dir() else folder
    files = {p.relative_to(internal).as_posix() for p in internal.rglob("*") if p.is_file()}
    modules: set[str] = set()
    executables = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".exe", "")]
    if executables:
        try:
            modules = onefile_contents(executables[0])[1]
        except Exception:  # noqa: BLE001 - the PYZ may be stored separately
            modules = set()
    for pyz in internal.glob("*.pyz"):
        from PyInstaller.archive.readers import ZlibArchiveReader

        modules |= set(ZlibArchiveReader(str(pyz)).toc)
    return files, modules


def external_files(folder: Path) -> set[str]:
    """Resources delivered beside the executable (``resources``, ``documentation``)."""
    return {p.relative_to(folder).as_posix() for top in ("resources", "documentation")
            for p in (folder / top).rglob("*") if p.is_file()}


def check(target: Path) -> int:
    if target.is_dir():
        embedded, modules = onedir_contents(target)
        beside = external_files(target)
    else:
        embedded, modules = onefile_contents(target)
        beside = external_files(target.parent)
    files = embedded | beside
    problems: list[str] = []
    expected = expected_files()
    missing = [name for name in expected if name not in files]
    in_exe = sum(1 for name in expected if name in embedded)
    outside = sum(1 for name in expected if name in beside and name not in embedded)
    print(f"embedded in the build: {in_exe}, beside the executable only: {outside}")
    problems += [f"missing file:   {name}" for name in missing]
    if modules:
        problems += [f"missing module: {name}  (add --hidden-import {name})"
                     for name in HIDDEN_IMPORTS if name not in modules]
    else:
        print("note: Python modules archive not found, hidden imports not checked")
    for qt in QT_MODULES:
        if not any(qt in Path(name).name for name in files):
            problems.append(f"missing Qt module: PyQt6.{qt}  (add --hidden-import PyQt6.{qt})")
    print(f"{target}: {len(expected) - len(missing)}/{len(expected)} resource files found")
    for problem in problems:
        print("  " + problem)
    if problems:
        print("INCOMPLETE build")
        return 1
    print("OK - every resource is included")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    target = Path(argv[1])
    if not target.exists():
        print(f"{target} does not exist")
        return 2
    return check(target)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
