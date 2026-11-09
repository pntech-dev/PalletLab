"""Run the real web update and updater against an isolated loopback release.

Build prerequisites: `npm run build`, the normal app and updater in
`build/update-check`, and the CAD helper in `build/SolidWorksDrawingHelper`.
No release or installed application is touched.
"""

from __future__ import annotations

import hashlib
import ctypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
import zipfile


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    root = (workspace / "build" / "update-e2e").resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = root / "PalletLab"
    production = workspace / "build" / "update-check" / "PalletLab"
    updater = workspace / "build" / "update-check" / "PalletLabUpdater"
    for required in (production / "PalletLab.exe", updater / "PalletLabUpdater.exe"):
        if not required.is_file():
            raise RuntimeError(f"Build prerequisite missing: {required}")

    hook = (workspace / "tests" / "update_e2e_hook.py").resolve()
    spec = (workspace / "palletlab.spec").read_text(encoding="utf-8")
    if "runtime_hooks=[]" not in spec:
        raise RuntimeError("Production spec changed; test hook was not inserted")
    spec = spec.replace('("frontend/dist", "frontend/dist")',
                        f'({str(workspace / "frontend/dist")!r}, "frontend/dist")')
    for relative in ("src/web_main.py", "VERSION", "icon.ico", "src"):
        spec = spec.replace(f'"{relative}"', repr(str(workspace / relative)))
    spec = spec.replace('HELPER_DIR = Path("build/SolidWorksDrawingHelper")',
                        f'HELPER_DIR = Path({str(workspace / "build/SolidWorksDrawingHelper")!r})')
    test_spec = root / "update-e2e.spec"
    test_spec.write_text(spec.replace("runtime_hooks=[]", f"runtime_hooks=[{str(hook)!r}]"), encoding="utf-8")
    if "--reuse-build" not in sys.argv:
        subprocess.run(  # noqa: S603 - fixed project interpreter and generated test spec.
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(root), str(test_spec)],
            cwd=workspace, check=True,
        )
    elif not (app / "PalletLab.exe").is_file():
        raise RuntimeError("The instrumented test application has not been built")
    (app / ".palletlab-installed").write_text("isolated test", encoding="ascii")
    package = root / "PalletLab-9.9.9-update.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(production / "PalletLab.exe", "PalletLab/PalletLab.exe")
        archive.writestr("PalletLab/_internal/VERSION", "9.9.9")
        archive.writestr("PalletLab/update-e2e-result.txt", "updated isolated copy")
        for path in updater.rglob("*"):
            if path.is_file():
                archive.write(path, Path("PalletLabUpdater") / path.relative_to(updater))
    with package.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (root / "checksum").write_text(digest + "\n", encoding="ascii")
    release = [{"tag_name": "v9.9.9", "draft": False, "assets": [
        {"name": package.name, "browser_download_url": "https://test.invalid/package"},
        {"name": package.name + ".sha256", "browser_download_url": "https://test.invalid/checksum"},
    ]}]
    requests: list[str] = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            with (root / "requests.log").open("a", encoding="utf-8") as stream:
                stream.write(self.path + "\n")
            if self.path == "/releases":
                payload = json.dumps(release).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path in {"/package", "/checksum"}:
                path = package if self.path == "/package" else root / "checksum"
                self.send_response(200)
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        self.wfile.write(chunk)
            else:
                self.send_error(404)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    isolated_temp = root / "temp"
    isolated_temp.mkdir(exist_ok=True)
    env = {**os.environ, "PALLETLAB_E2E_ROOT": str(root), "PALLETLAB_E2E_PORT": str(server.server_port),
           "LOCALAPPDATA": str(root / "profile"), "TEMP": str(isolated_temp), "TMP": str(isolated_temp)}
    events = root / "events.jsonl"
    events.unlink(missing_ok=True)
    (root / "requests.log").unlink(missing_ok=True)
    (root / "updater.pid").unlink(missing_ok=True)
    process = subprocess.Popen(  # noqa: S603 - isolated application built above, no shell.
        [str(app / "PalletLab.exe")], env=env, cwd=app, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    updater_handle = None
    try:
        deadline = time.monotonic() + 120
        result = app / "update-e2e-result.txt"
        while time.monotonic() < deadline and not result.exists():
            if updater_handle is None and (root / "updater.pid").is_file():
                from ctypes import wintypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
                kernel32.OpenProcess.restype = wintypes.HANDLE
                updater_handle = kernel32.OpenProcess(0x0001, False, int((root / "updater.pid").read_text()))
            if events.is_file() and '"event": "error"' in events.read_text(encoding="utf-8"):
                raise RuntimeError(events.read_text(encoding="utf-8"))
            if process.poll() is not None and not (root / "updater.pid").exists():
                raise RuntimeError(f"Test application exited before handoff: {process.returncode}")
            time.sleep(0.25)
        if not result.is_file():
            raise RuntimeError("Timed out waiting for isolated update")
        recorded = [json.loads(line)["event"] for line in events.read_text(encoding="utf-8").splitlines()]
        required_events = {"update_offered", "download_clicked", "download_verified", "unsaved_blocked", "project_saved"}
        if not required_events.issubset(recorded):
            raise RuntimeError(f"Missing UI stages: {required_events - set(recorded)}")
        if (app / "_internal" / "VERSION").read_text().strip() != "9.9.9":
            raise RuntimeError("Updated version file was not installed")
        if not (root / "test-project.palletlab.json").is_file():
            raise RuntimeError("The test project was not saved")
        if not {"/releases", "/package", "/checksum"}.issubset(requests):
            raise RuntimeError(f"Missing release requests: {requests}")
        print("PASS: release discovery, download, checksum, save gate, updater handoff and isolated replacement")
        return 0
    finally:
        server.shutdown()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if updater_handle:
            from ctypes import wintypes
            kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.TerminateProcess(updater_handle, 0)
            kernel32.CloseHandle(updater_handle)


if __name__ == "__main__":
    raise SystemExit(main())
