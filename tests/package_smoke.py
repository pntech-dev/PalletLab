"""Validate release archives and exercise the extracted portable executable."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Expected portable ZIP and update ZIP")
    portable, update = (Path(value).resolve() for value in sys.argv[1:])
    checksum = update.with_name(update.name + ".sha256")
    with update.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum.read_text(encoding="ascii").split()[0] != digest:
        raise RuntimeError("Update checksum does not match the archive")
    required = {
        "PalletLab/PalletLab.exe",
        "PalletLab/_internal/VERSION",
        "PalletLab/_internal/frontend/dist/index.html",
        "PalletLab/_internal/tools/SolidWorksDrawingHelper/SolidWorksDrawingHelper.exe",
    }
    with zipfile.ZipFile(update) as archive:
        names = set(archive.namelist())
        missing = (required | {"PalletLabUpdater/PalletLabUpdater.exe"}) - names
        if missing or archive.testzip():
            raise RuntimeError(f"Invalid update archive; missing: {sorted(missing)}")
        if "PalletLab/.palletlab-installed" in names:
            raise RuntimeError("The update archive must not mark portable copies as installed")
    build = Path("build").resolve()
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="palletlab-portable-", dir=build) as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(portable) as archive:
            names = set(archive.namelist())
            missing = required - names
            if missing or "PalletLab/.palletlab-installed" in names or archive.testzip():
                raise RuntimeError(f"Invalid portable archive; missing: {sorted(missing)}")
            archive.extractall(root)
        executable = root / "PalletLab" / "PalletLab.exe"
        smoke = subprocess.run(  # noqa: S603 - executable extracted from the locally built archive.
            [str(executable), "--smoke-test"], cwd=root, check=False, timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if smoke.returncode:
            log = root / "palletlab-smoke-test-error.log"
            raise RuntimeError(f"Portable smoke test failed: {log.read_text(encoding='utf-8') if log.exists() else smoke.returncode}")
        subprocess.run(  # noqa: S603 - fixed local interpreter and project smoke test.
            [sys.executable, "tests/frozen_step_smoke.py", str(executable)], check=True, timeout=150,
        )
    print("Portable and update archives, checksum and extracted STEP worker: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
