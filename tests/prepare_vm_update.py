"""Build a self-contained, isolated installer for manual VM update testing."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "build" / "vm-update-test"
    output.mkdir(parents=True, exist_ok=True)
    production = root / "build" / "update-check" / "PalletLab"
    updater = root / "build" / "update-check" / "PalletLabUpdater"
    for required in (production / "PalletLab.exe", updater / "PalletLabUpdater.exe"):
        if not required.is_file():
            raise RuntimeError(f"Missing prerequisite: {required}")

    spec = (root / "palletlab.spec").read_text(encoding="utf-8")
    if "runtime_hooks=[]" not in spec:
        raise RuntimeError("Cannot insert the test hook into the app spec")
    spec = spec.replace('("frontend/dist", "frontend/dist")', f'({str(root / "frontend/dist")!r}, "frontend/dist")')
    for relative in ("src/web_main.py", "VERSION", "icon.ico", "src"):
        spec = spec.replace(f'"{relative}"', repr(str(root / relative)))
    spec = spec.replace('HELPER_DIR = Path("build/SolidWorksDrawingHelper")',
                        f'HELPER_DIR = Path({str(root / "build/SolidWorksDrawingHelper")!r})')
    spec = spec.replace("runtime_hooks=[]", f"runtime_hooks=[{str(root / 'tests/vm_update_hook.py')!r}]")
    spec_path = output / "vm-app.spec"
    spec_path.write_text(spec, encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(output),  # noqa: S603
                    "--workpath", str(output / "work"), str(spec_path)], cwd=root, check=True)

    package = output / "PalletLab-9.9.9-update.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for base, prefix in ((production, "PalletLab"), (updater, "PalletLabUpdater")):
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(base).as_posix()
                if prefix == "PalletLab" and relative == "_internal/VERSION":
                    continue
                archive.write(path, f"{prefix}/{relative}")
        archive.writestr("PalletLab/_internal/VERSION", "9.9.9\n")

    installer = output / "vm-test.iss"
    installer.write_text(f'''[Setup]
AppId={{{{3BE21DAA-CF7D-48FB-AB42-011212DC8D18}}
AppName=PalletLab VM Update Test
AppVersion=0.5.0-beta
DefaultDirName={{localappdata}}\\Programs\\PalletLab-VM-Update-Test
DisableDirPage=yes
DefaultGroupName=PalletLab VM Update Test
OutputDir={output}
OutputBaseFilename=PalletLab-VM-Update-Test-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName=PalletLab VM Update Test
[Files]
Source: "{output / 'PalletLab'}\\*"; DestDir: "{{app}}\\App"; Flags: recursesubdirs ignoreversion
Source: "{root / 'installer/installed.marker'}"; DestDir: "{{app}}\\App"; DestName: ".palletlab-installed"; Flags: ignoreversion
Source: "{updater}\\*"; DestDir: "{{app}}\\Updater"; Flags: recursesubdirs ignoreversion
Source: "{package}"; DestDir: "{{app}}\\TestRelease"; Flags: ignoreversion
[Icons]
Name: "{{autodesktop}}\\PalletLab VM Update Test"; Filename: "{{app}}\\App\\PalletLab.exe"
Name: "{{autoprograms}}\\PalletLab VM Update Test"; Filename: "{{app}}\\App\\PalletLab.exe"
''', encoding="utf-8-sig")
    compiler = root / "build/package-tools/InnoSetup/ISCC.exe"
    subprocess.run([str(compiler), str(installer)], cwd=root, check=True)  # noqa: S603
    setup = output / "PalletLab-VM-Update-Test-Setup.exe"
    with setup.open("rb") as stream:
        print(f"Setup: {setup}\nSHA-256: {hashlib.file_digest(stream, 'sha256').hexdigest()}")


if __name__ == "__main__":
    main()
