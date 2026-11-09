"""Test-only PyInstaller hook; never included in the production spec."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import webview

from palletlab import update_service
from palletlab.application import update_manager
from palletlab.desktop.web_host import WebApplicationApi


root = Path(os.environ["PALLETLAB_E2E_ROOT"]).resolve()
if Path(sys.executable).resolve().parent != root / "PalletLab":
    raise RuntimeError("Update test may only run from its isolated application copy")
port = int(os.environ["PALLETLAB_E2E_PORT"])


def record(event: str, **details: object) -> None:
    with (root / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": event, **details}, ensure_ascii=False) + "\n")


def local_request(request, *, timeout: int, attempts: int = 3):
    del attempts
    source = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    path = urllib.parse.urlsplit(source).path
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout)  # noqa: S310 - isolated test server only.


update_service._request = local_request
update_service.RELEASES_URL = "https://test.invalid/releases"
original_popen = subprocess.Popen


def recorded_popen(args, **kwargs):
    if str(args[0]).endswith("PalletLabUpdater.exe"):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs["startupinfo"] = startup
        process = original_popen(args, **kwargs)
        (root / "updater.pid").write_text(str(process.pid), encoding="ascii")
        return process
    return original_popen(args, **kwargs)


update_manager.subprocess.Popen = recorded_popen
original_create = webview.create_window


def hidden_window(*args, **kwargs):
    kwargs["hidden"] = True
    return original_create(*args, **kwargs)


webview.create_window = hidden_window
original_attach = WebApplicationApi.attach_window
original_choose = WebApplicationApi._choose_file


def choose_file(self, mode):
    if mode == "save":
        return str(root / "test-project.palletlab.json")
    return original_choose(self, mode)


def attach(self, window):
    original_attach(self, window)

    def exercise():
        try:
            def wait_for(script: str, timeout: float = 90):
                deadline = time.monotonic() + timeout
                last_error = ""
                while time.monotonic() < deadline:
                    try:
                        result = window.evaluate_js(script)
                        if result:
                            return result
                    except Exception as error:
                        last_error = str(error)
                    time.sleep(0.25)
                raise RuntimeError(f"Timed out waiting for {script}: {last_error}")

            wait_for("document.readyState === 'complete'")
            time.sleep(8)
            record("page_state", value=window.evaluate_js("JSON.stringify({text: document.body.innerText.slice(0, 1200), bridge: !!window.pywebview?.api})"))
            record("update_state", value=self.update_status())
            wait_for("!!document.querySelector('#update-title')", timeout=25)
            record("update_offered")
            wait_for("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Скачать')?.click() || true")
            record("download_clicked")
            wait_for("document.body.innerText.includes('готова к установке')")
            record("download_verified")
            blocked = wait_for("!![...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Установить' && b.disabled)")
            record("unsaved_blocked", value=blocked)
            wait_for("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Сохранить проект')?.click() || true")
            wait_for("!![...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Установить' && !b.disabled)")
            record("project_saved")
            record("install_clicked")
            window.evaluate_js("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Установить').click()")
        except Exception as error:
            record("error", message=str(error))
            window.destroy()

    threading.Thread(target=exercise, daemon=True).start()


WebApplicationApi._choose_file = choose_file
WebApplicationApi.attach_window = attach
