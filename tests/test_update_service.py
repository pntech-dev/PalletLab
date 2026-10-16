import hashlib

from palletlab.update_service import _sha256_file, find_newer_release, version_key


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
