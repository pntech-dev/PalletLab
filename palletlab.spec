# -*- mode: python ; coding: utf-8 -*-
"""Lean, fast-starting Windows build configuration for PalletLab.

Build manually with ``pyinstaller palletlab.spec``. The ``onedir`` layout is
intentional: VTK's native libraries stay beside the executable instead of
being unpacked into a temporary directory at every application start.
"""

APP_NAME = "PalletLab"

# These modules are imported dynamically by PyVista/VTK's Qt integration and
# cannot always be discovered from the application's direct imports.
HIDDEN_IMPORTS = [
    "pyvista.plotting._vtk",
    "pyvista.plotting._vtk_gl",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
]

# PalletLab does not use example data, test helpers, or alternative GUI
# backends. PyVista's base package imports ``pyvista.jupyter`` and Matplotlib
# even in desktop mode, so those must remain available.
EXCLUDES = [
    "IPython",
    "PIL.ImageQt",
    "pytest",
    "pyvista.examples",
    "pyvista.trame",
    "tkinter",
    "trame",
    "trame_client",
    "trame_server",
    "trame_vtk",
    "vtkmodules.gtk",
    "vtkmodules.test",
    "vtkmodules.tk",
]

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
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
