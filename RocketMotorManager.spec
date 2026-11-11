# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for Rocket Motor Manager (Windows, one-folder build).
# Build with:  python -m PyInstaller --noconfirm --clean RocketMotorManager.spec
# Copyright (c) 2026 Boris du Reau

import glob

block_cipher = None

datas = [
    ("resources/icons", "resources/icons"),
    ("resources/templates", "resources/templates"),
    ("resources/locale", "resources/locale"),
    ("resources/images", "resources/images"),
    ("documentation/technical_documentation.html", "documentation"),
]
# One PDF user manual per language (documentation/user_manual_<lang>.pdf).
datas += [(manual, "documentation") for manual in sorted(glob.glob("documentation/user_manual_*.pdf"))]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "openpyxl", "xlrd", "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_pdf",
        "matplotlib.backends.backend_svg", "scipy.signal", "PyQt6.QtSvg", "PyQt6.QtPrintSupport",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "PyQt5", "PySide2", "PySide6"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RocketMotorManager",
    icon="resources/icons/app.ico",
    version="version_info.txt",
    console=False,
    debug=False,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="RocketMotorManager",
)
