# -*- mode: python ; coding: utf-8 -*-
"""Maintained Windows build configuration. Run manually: pyinstaller palletlab.spec."""

from PyInstaller.utils.hooks import collect_all


def collected(package):
    datas, binaries, hiddenimports = collect_all(package)
    return datas, binaries, hiddenimports


datas, binaries, hiddenimports = [], [], []
for package_name in ("pyvista", "pyvistaqt", "vtkmodules", "PyQt5"):
    package_datas, package_binaries, package_hiddenimports = collected(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], name="PalletLab", console=False)
