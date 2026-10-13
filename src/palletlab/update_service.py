"""Public GitHub Release discovery and verified update downloads."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

RELEASES_URL = "https://api.github.com/repos/pntech-dev/PalletLab/releases"
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-beta)?$")


@dataclass(frozen=True)
class Release:
    version: str
    package_url: str
    checksum_url: str
    notes: str


def version_key(value: str) -> tuple[int, int, int, int]:
    match = VERSION_PATTERN.fullmatch(value.removeprefix("v"))
    if match is None:
        raise ValueError(f"Неподдерживаемая версия: {value}")
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), 0 if beta else 1


def find_newer_release(raw: object, current_version: str) -> Release | None:
    if not isinstance(raw, list):
        return None
    candidates: list[Release] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name", "")).removeprefix("v")
        try:
            version_key(tag)
        except ValueError:
            continue
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        package = next((asset for asset in assets if str(asset.get("name", "")).endswith("-update.zip")), None)
        checksum = next((asset for asset in assets if str(asset.get("name", "")).endswith("-update.zip.sha256")), None)
        if package and checksum:
            candidates.append(Release(tag, str(package["browser_download_url"]), str(checksum["browser_download_url"]), str(item.get("body", ""))))
    newer = [release for release in candidates if version_key(release.version) > version_key(current_version)]
    return max(newer, key=lambda release: version_key(release.version), default=None)


def fetch_newer_release(current_version: str) -> Release | None:
    request = urllib.request.Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "PalletLab"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return find_newer_release(json.load(response), current_version)


def download_verified(release: Release, progress) -> Path:
    with urllib.request.urlopen(release.checksum_url, timeout=15) as response:
        expected = response.read().decode("utf-8").split()[0].lower()
    target = Path(tempfile.mkdtemp(prefix="palletlab-update-")) / f"PalletLab-{release.version}-update.zip"
    request = urllib.request.Request(release.package_url, headers={"User-Agent": "PalletLab"})
    with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as stream:
        total = int(response.headers.get("Content-Length", 0))
        received = 0
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
            received += len(chunk)
            progress(received, total)
    actual = _sha256_file(target)
    if actual.lower() != expected:
        target.unlink(missing_ok=True)
        raise RuntimeError("Проверка целостности обновления не пройдена.")
    return target


def _sha256_file(path: Path) -> str:
    """Hash update archives in chunks so large builds do not fill RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
