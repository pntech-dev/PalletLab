"""Local update fixture, included only in the isolated VM test build."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread
import urllib.parse
import urllib.request

from palletlab import update_service

install_root = Path(os.environ["LOCALAPPDATA"]).resolve() / "Programs" / "PalletLab-VM-Update-Test"
if Path(sys.executable).resolve().parent != install_root / "App":
    raise RuntimeError("This update fixture only runs in the isolated VM test installation.")
package = install_root / "TestRelease" / "PalletLab-9.9.9-update.zip"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/releases":
            assets = [
                {"name": package.name, "browser_download_url": "https://vm-test.invalid/package"},
                {"name": package.name + ".sha256", "browser_download_url": "https://vm-test.invalid/checksum"},
            ]
            payload = json.dumps([{"tag_name": "v9.9.9", "draft": False, "assets": assets}]).encode()
        elif self.path == "/checksum":
            with package.open("rb") as stream:
                payload = (hashlib.file_digest(stream, "sha256").hexdigest() + "\n").encode("ascii")
        elif self.path == "/package":
            self.send_response(200)
            self.send_header("Content-Length", str(package.stat().st_size))
            self.end_headers()
            with package.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    self.wfile.write(chunk)
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
Thread(target=server.serve_forever, daemon=True).start()


def local_request(request, *, timeout: int, attempts: int = 3):
    del attempts
    source = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    parsed = urllib.parse.urlsplit(source)
    if parsed.hostname != "vm-test.invalid" or parsed.path not in {"/releases", "/checksum", "/package"}:
        raise RuntimeError("Unexpected update fixture URL")
    return urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{parsed.path}", timeout=timeout)


update_service.RELEASES_URL = "https://vm-test.invalid/releases"
update_service._request = local_request
