"""Check that the VM-only local release feeds the real update service."""

from __future__ import annotations

import runpy
import sys
import urllib.error
from pathlib import Path

import pytest

from palletlab import update_service


def test_local_fixture_uses_real_release_and_checksum(tmp_path, monkeypatch):
    install = tmp_path / "Programs" / "PalletLab-VM-Update-Test"
    release_dir = install / "TestRelease"
    release_dir.mkdir(parents=True)
    package = release_dir / "PalletLab-9.9.9-update.zip"
    package.write_bytes(b"test package")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(install / "App" / "PalletLab.exe"))
    monkeypatch.setattr(update_service, "_request", update_service._request)
    monkeypatch.setattr(update_service, "RELEASES_URL", update_service.RELEASES_URL)
    namespace = runpy.run_path(str(Path(__file__).with_name("vm_update_hook.py")))
    server = namespace["server"]
    try:
        try:
            release = update_service.fetch_newer_release("0.5.0-beta")
        except urllib.error.URLError as error:
            if isinstance(error.reason, OSError) and getattr(error.reason, "winerror", None) == 10013:
                pytest.skip("The execution sandbox blocks loopback connections")
            raise
        assert release is not None and release.version == "9.9.9"
        downloaded = update_service.download_verified(release, lambda *_: None)
        try:
            assert downloaded.read_bytes() == package.read_bytes()
        finally:
            downloaded.unlink()
            downloaded.parent.rmdir()
        with pytest.raises(RuntimeError, match="Unexpected update fixture URL"):
            update_service._request("https://example.com/package", timeout=1)
    finally:
        server.shutdown()
        server.server_close()
