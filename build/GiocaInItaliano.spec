# -*- mode: python ; coding: utf-8 -*-
"""Ricetta PyInstaller per GiocaInItaliano.exe.

Si costruisce con build.ps1, che esegue PyInstaller da questa cartella.
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # L'interfaccia viene estratta accanto all'eseguibile in memoria: e' il
    # percorso che paths.resource_path("web", ...) si aspetta quando e'
    # compilato.
    datas=[(str(ROOT / "hub" / "web"), "web")],
    hiddenimports=[
        # pywebview carica il backend a runtime, PyInstaller da solo non lo vede.
        "webview.platforms.edgechromium",
        "clr_loader",
    ]
    # config.py lo importa dentro un try/except: se c'e', va incluso, ed e'
    # cosi' che le credenziali OAuth entrano nell'eseguibile senza passare dal
    # repository. Se non c'e', l'exe esce senza accesso in-app e funziona lo
    # stesso, con le azioni social che passano dal browser.
    + (["hub.credenziali"] if (ROOT / "hub" / "credenziali.py").exists() else []),
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Gli altri motori di pywebview. L'hub usa solo WebView2 di Edge, ma
        # PyInstaller impacchetta qualunque motore trovi installato nel Python
        # che compila: il 26 settembre 2026 qualcosa ha installato PyQt5 sul
        # PC di sviluppo e l'exe e' passato da 25 a 55 MB da un giro all'altro.
        # E non era solo peso: PyQt5 e' sotto GPL v3, e distribuirlo dentro
        # l'eseguibile obbligherebbe a pubblicare l'hub sotto la stessa
        # licenza. La build non deve dipendere da cosa c'e' installato accanto.
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "qtpy",
        "gi",
        "webview.platforms.qt",
        "webview.platforms.gtk",
        "webview.platforms.cocoa",
        "webview.platforms.android",
        "webview.platforms.cef",
        # Roba pesante che non usiamo e che PyInstaller tirerebbe dentro.
        "tkinter",
        "PIL.ImageQt",
        "PIL.ImageTk",
        "matplotlib",
        "numpy",
        "pytest",
        "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GiocaInItaliano",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Niente finestra del prompt dietro l'app.
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "build" / "icon.ico") if (ROOT / "build" / "icon.ico").exists() else None,
    version=str(ROOT / "build" / "version_info.txt")
    if (ROOT / "build" / "version_info.txt").exists()
    else None,
)
