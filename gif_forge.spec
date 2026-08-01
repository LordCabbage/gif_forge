# -*- mode: python ; coding: utf-8 -*-


import sys
from pathlib import Path

ROOT = Path(SPECPATH)
BIN = ROOT / "bin"

if not BIN.is_dir() or not any(BIN.iterdir()):
    raise SystemExit(
        "catalog is emoty. Do: python scripts/fetch_binaries.py"
    )


tool_payload = [(str(p), "bin") for p in BIN.iterdir() if p.is_file()]

a = Analysis(
    ["gif_forge.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=tool_payload,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "PyQt5", "PySide2", "PySide6",
        "numpy", "matplotlib", "PIL", "scipy", "pandas",
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.Qt3DCore",
        "PyQt6.QtBluetooth", "PyQt6.QtNetworkAuth", "PyQt6.QtPositioning",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GifForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          
    console=False,     
    icon=None,         
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GifForge",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GifForge.app",
        icon=None,
        bundle_identifier="io.github.LordCabbage.gifforge",
        info_plist={
            "CFBundleName": "GIF Forge",
            "CFBundleDisplayName": "GIF Forge",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
