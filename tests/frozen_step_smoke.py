"""Exercise the packaged STEP worker with a generated, non-sensitive model."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer


def main() -> int:
    executable = Path(sys.argv[1]).resolve()
    work_dir = Path("build").resolve()
    work_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="palletlab-frozen-step-", dir=work_dir) as temporary:
        root = Path(temporary)
        model = root / "smoke.step"
        writer = STEPControl_Writer()
        writer.Transfer(BRepPrimAPI_MakeBox(100, 80, 70).Shape(), STEPControl_AsIs)
        writer.Write(str(model))
        env = {**os.environ, "LOCALAPPDATA": str(root)}
        result = subprocess.run(  # noqa: S603 - explicit locally built application path and generated fixture.
            [str(executable), "--step-import", str(model)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        messages = []
        for line in result.stdout.splitlines():
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if result.returncode or not any(isinstance(message, dict) and message.get("kind") == "done" for message in messages):
            print(f"Frozen STEP worker failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
            return 1
        print("Frozen STEP worker completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
