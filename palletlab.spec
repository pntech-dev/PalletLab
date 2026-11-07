# -*- mode: python ; coding: utf-8 -*-
"""Windows build configuration for the React/pywebview PalletLab desktop app.

Build manually with ``pyinstaller palletlab.spec``. The ``onedir`` layout is
intentional: the React bundle and desktop integration resources stay beside
the executable instead of being unpacked into a temporary directory at every
application start.
"""

APP_NAME = "PalletLab"

# The web host imports pywebview lazily so that command and bridge tests can
# run without creating a desktop window.  PyInstaller cannot see that import
# through the entry point and therefore needs the Windows backend explicitly.
HIDDEN_IMPORTS = [
    "webview",
    "webview.platforms.winforms",
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "clr",
    "Python.Runtime",
]

# The legacy PyQt/PyVista client remains in the repository while migration is
# in progress, but the released executable starts the React/pywebview client.
EXCLUDES = [
    "IPython",
    "PIL.ImageQt",
    "pytest",
    # ``mypy`` is a development-only dependency.  Recent Windows wheels use
    # a hash-named mypyc bootstrap module, which PyInstaller cannot infer from
    # the extension modules.  The application never uses it at runtime.
    "mypy",
    "mypyc",
    "mypy_extensions",
    "PyQt5",
    "pyvista",
    "pyvistaqt",
    "vtkmodules",
]

a = Analysis(
    ["src/web_main.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("VERSION", "."),
        ("icon.ico", "."),
        ("frontend/dist", "frontend/dist"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon="icon.ico",
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
