import hashlib
from io import BytesIO

import pytest

from palletlab.update_service import Release, _sha256_file, download_verified, find_newer_release, version_key


def _release(version: str):
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "assets": [
            {"name": f"PalletLab-{version}-update.zip", "browser_download_url": "https://example.test/update"},
            {"name": f"PalletLab-{version}-update.zip.sha256", "browser_download_url": "https://example.test/hash"},
        ],
    }


def test_stable_version_is_newer_than_same_beta():
    assert version_key("1.0.0") > version_key("1.0.0-beta")


def test_release_selection_includes_beta_and_ignores_drafts():
    draft = _release("0.9.0-beta")
    draft["draft"] = True
    selected = find_newer_release([draft, _release("0.2.0-beta"), _release("0.3.0-beta")], "0.1.0-beta")
    assert selected is not None
    assert selected.version == "0.3.0-beta"


def test_sha256_file_reads_complete_binary_file(tmp_path):
    payload = b"PalletLab" * 100_000
    package = tmp_path / "update.zip"
    package.write_bytes(payload)

    assert _sha256_file(package) == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("valid", [True, False])
def test_download_checks_checksum_before_returning_package(tmp_path, monkeypatch, valid):
    payload = b"sample update archive"
    expected = hashlib.sha256(payload if valid else b"different content").hexdigest()
    responses = iter([BytesIO(expected.encode("ascii")), BytesIO(payload)])

    class Response:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.data.close()

        def read(self, size=-1):
            return self.data.read(size)

    monkeypatch.setattr("palletlab.update_service._request", lambda *_args, **_kwargs: Response(next(responses)))
    monkeypatch.setattr("palletlab.update_service.tempfile.mkdtemp", lambda **_kwargs: str(tmp_path / "download"))
    (tmp_path / "download").mkdir()
    progress = []
    release = Release("9.9.9", "https://example.test/archive", "https://example.test/hash", "")
    if valid:
        package = download_verified(release, lambda received, total: progress.append((received, total)))
        assert package.read_bytes() == payload
        assert progress == [(len(payload), len(payload))]
    else:
        with pytest.raises(RuntimeError, match="целостности"):
            download_verified(release, lambda *_args: None)
        assert not (tmp_path / "download").exists()
