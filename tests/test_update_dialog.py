import zipfile

import pytest

from palletlab.ui.update_dialog import _extract_updater


def test_extract_updater_uses_updater_from_update_package(tmp_path):
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("PalletLabUpdater/PalletLabUpdater.exe", b"updater")

    updater = _extract_updater(package)

    assert updater.read_bytes() == b"updater"


def test_extract_updater_rejects_path_outside_temporary_folder(tmp_path):
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("PalletLabUpdater/../../outside.exe", b"unsafe")

    with pytest.raises(RuntimeError, match="недопустимый путь"):
        _extract_updater(package)
