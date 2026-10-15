import os
import zipfile

import pytest

import updater_main
from updater_main import _install_application_files, _running, _safe_extract_update


def test_running_recognizes_current_process():
    assert _running(os.getpid())


def test_install_application_files_overlays_build_without_renaming_root(tmp_path):
    current = tmp_path / "App"
    current.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    incoming = tmp_path / "PalletLab"
    (incoming / "nested").mkdir(parents=True)
    (incoming / "old.txt").write_text("new", encoding="utf-8")
    (incoming / "nested" / "new.txt").write_text("content", encoding="utf-8")

    _install_application_files(current, incoming)

    assert (current / "old.txt").read_text(encoding="utf-8") == "new"
    assert (current / "nested" / "new.txt").read_text(encoding="utf-8") == "content"


def test_safe_extract_rejects_path_escape_and_preserves_destination(tmp_path):
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("PalletLab/../../outside.exe", b"unsafe")

    with zipfile.ZipFile(package) as archive, pytest.raises(RuntimeError, match="недопустимый"):
        _safe_extract_update(archive, tmp_path / "staging")

    assert not (tmp_path / "outside.exe").exists()


def test_install_restores_replaced_files_if_a_later_copy_fails(tmp_path, monkeypatch):
    current = tmp_path / "App"
    current.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    incoming = tmp_path / "PalletLab"
    incoming.mkdir()
    (incoming / "old.txt").write_text("new", encoding="utf-8")
    (incoming / "later.txt").write_text("later", encoding="utf-8")
    original = updater_main._replace_file

    def fail_on_later(source, destination):
        if source.name == "later.txt":
            raise OSError("simulated copy failure")
        original(source, destination)

    monkeypatch.setattr(updater_main, "_replace_file", fail_on_later)

    with pytest.raises(OSError, match="simulated"):
        _install_application_files(current, incoming)

    assert (current / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (current / "later.txt").exists()
