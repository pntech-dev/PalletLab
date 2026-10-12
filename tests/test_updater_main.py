import os

from updater_main import _install_application_files, _running


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
