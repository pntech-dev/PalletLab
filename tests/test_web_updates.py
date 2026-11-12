from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from palletlab.application import update_manager
from palletlab.update_service import Release


def test_only_installed_frozen_application_enables_updates(tmp_path):
    app = tmp_path / "App"
    app.mkdir()
    executable = app / "PalletLab.exe"
    executable.touch()
    assert not update_manager.installed_application(executable, frozen=True)
    (app / ".palletlab-installed").touch()
    assert update_manager.installed_application(executable, frozen=True)
    assert not update_manager.installed_application(executable, frozen=False)


def test_existing_installer_is_detected_without_marker(tmp_path):
    app = tmp_path / "App"
    app.mkdir()
    updater = tmp_path / "Updater"
    updater.mkdir()
    (updater / "PalletLabUpdater.exe").touch()
    (tmp_path / "unins000.exe").touch()
    assert update_manager.installed_application(app / "PalletLab.exe", frozen=True)
    assert not update_manager.installed_application(tmp_path / "Portable" / "PalletLab.exe", frozen=True)


def test_update_extract_rejects_unsafe_paths(tmp_path):
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("PalletLabUpdater/../../outside.exe", b"unsafe")
    with pytest.raises(RuntimeError, match="недопустимый"):
        update_manager.extract_updater(package)
    assert not (tmp_path.parent / "outside.exe").exists()


def test_check_download_and_launch_verified_update(tmp_path, monkeypatch):
    release = Release("9.9.9", "https://example.test/update", "https://example.test/hash", "")
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("PalletLabUpdater/PalletLabUpdater.exe", b"updater")
    calls = []

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    def download(selected, progress):
        assert selected == release
        progress(5, 10)
        return package

    monkeypatch.setattr(update_manager, "installed_application", lambda: True)
    monkeypatch.setattr(update_manager, "Thread", ImmediateThread)
    monkeypatch.setattr(update_manager, "fetch_newer_release", lambda _version: release)
    monkeypatch.setattr(update_manager, "download_verified", download)
    monkeypatch.setattr(update_manager.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(update_manager.sys, "executable", str(tmp_path / "App" / "PalletLab.exe"))

    manager = update_manager.UpdateManager()
    assert manager.check() == {"state": "available", "version": "9.9.9"}
    assert manager.download() == {"state": "ready", "version": "9.9.9"}
    assert manager.install() == {"state": "installing"}
    assert Path(calls[0][0][0]).read_bytes() == b"updater"
    assert calls[0][0][1:5] == ["--package", str(package), "--app-dir", str(tmp_path / "App")]


def test_download_failure_does_not_launch_updater(monkeypatch):
    manager = update_manager.UpdateManager()
    release = Release("9.9.9", "https://example.test/update", "https://example.test/hash", "")
    monkeypatch.setattr(update_manager, "download_verified", lambda *_args: (_ for _ in ()).throw(RuntimeError("bad checksum")))
    manager._download(release)
    assert manager.status()["state"] == "failed"
    assert manager.status()["error"] == "bad checksum"


def test_web_bridge_closes_window_only_after_successful_handoff():
    from palletlab.desktop.web_host import WebApplicationApi

    api = WebApplicationApi()
    closed = []
    api.attach_window(SimpleNamespace(destroy=lambda: closed.append(True)))
    api._updates = SimpleNamespace(install=lambda: {"state": "ready", "error": "failed"})
    api.install_update()
    assert not closed
    api._updates = SimpleNamespace(install=lambda: {"state": "installing"})
    api.install_update()
    assert closed == [True]


def test_manual_check_works_for_portable_but_cannot_install(monkeypatch):
    release = Release("9.9.9", "https://example.test/update", "https://example.test/hash", "")
    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(update_manager, "installed_application", lambda: False)
    monkeypatch.setattr(update_manager, "Thread", ImmediateThread)
    monkeypatch.setattr(update_manager, "fetch_newer_release", lambda _version: release)
    manager = update_manager.UpdateManager()
    assert manager.check() == {"state": "unavailable"}
    assert manager.last_check_at is None
    assert manager.check(manual=True) == {"state": "available", "version": "9.9.9", "manualOnly": True}
    assert manager.last_check_at is not None
    assert manager.download()["state"] == "failed"


def test_check_time_changes_only_when_a_check_starts(monkeypatch):
    class DelayedThread:
        def __init__(self, *, target, args=(), daemon):
            pass
        def start(self):
            pass
    monkeypatch.setattr(update_manager, "installed_application", lambda: True)
    monkeypatch.setattr(update_manager, "Thread", DelayedThread)
    manager = update_manager.UpdateManager()
    assert manager.check()["state"] == "checking"
    timestamp = manager.last_check_at
    assert timestamp is not None
    assert manager.check(manual=True)["state"] == "checking"
    assert manager.last_check_at == timestamp


def test_web_bridge_persists_actual_last_check_and_preserves_settings(tmp_path, monkeypatch):
    from palletlab.desktop.web_host import WebApplicationApi, _WebSettings
    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(update_manager, "installed_application", lambda: True)
    monkeypatch.setattr(update_manager, "Thread", ImmediateThread)
    monkeypatch.setattr(update_manager, "fetch_newer_release", lambda _version: None)
    api = WebApplicationApi()
    api._settings = _WebSettings(tmp_path / "settings.json")
    assert api._settings.save_drawing_template("kompas", "drawing.cdt")
    response = api.check_update()
    assert response["state"] == "current"
    assert response["lastCheckedAt"]
    assert api.update_status()["lastCheckedAt"] == response["lastCheckedAt"]
    api._updates = update_manager.UpdateManager()
    assert api.update_status()["lastCheckedAt"] == response["lastCheckedAt"]
    assert api._settings.drawing_templates() == {"kompas": "drawing.cdt"}


def test_failed_check_records_attempt(monkeypatch):
    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(update_manager, "installed_application", lambda: True)
    monkeypatch.setattr(update_manager, "Thread", ImmediateThread)
    def fail(_version):
        raise OSError("offline")
    monkeypatch.setattr(update_manager, "fetch_newer_release", fail)
    manager = update_manager.UpdateManager()
    assert manager.check()["state"] == "check_failed"
    assert manager.last_check_at is not None
