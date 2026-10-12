# -*- mode: python ; coding: utf-8 -*-
a = Analysis(["src/updater_main.py"], pathex=["src"], binaries=[], datas=[], hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PalletLabUpdater", console=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="PalletLabUpdater")
