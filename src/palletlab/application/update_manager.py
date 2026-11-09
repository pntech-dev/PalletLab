"""Background update workflow for the installed web desktop application."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
from threading import Lock, Thread
import zipfile

from palletlab.update_service import Release, download_verified, fetch_newer_release
from palletlab.version import __version__


def installed_application(executable: Path | None = None, *, frozen: bool | None = None) -> bool:
    """Recognize Setup installations, including installations predating the marker."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return False
    app_dir = (executable or Path(sys.executable)).resolve().parent
    if (app_dir / ".palletlab-installed").is_file():
        return True
    install_dir = app_dir.parent
    return (app_dir.name.casefold() == "app"
            and (install_dir / "Updater" / "PalletLabUpdater.exe").is_file()
            and any(install_dir.glob("unins*.exe")))


def extract_updater(package: Path) -> Path:
    """Extract the updater from a verified archive without permitting traversal."""
    root = package.parent.resolve()
    destination = root / "PalletLabUpdater" / "PalletLabUpdater.exe"
    with zipfile.ZipFile(package) as archive:
        members = [item for item in archive.infolist() if item.filename.startswith("PalletLabUpdater/")]
        for item in members:
            relative = Path(item.filename)
            target = (root / relative).resolve()
            if (relative.is_absolute() or ".." in relative.parts or root not in target.parents
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise RuntimeError("Пакет обновления содержит недопустимый путь или ссылку.")
        if not members:
            raise RuntimeError("Пакет обновления не содержит апдейтер. Установите новую версию через Setup.")
        for item in members:
            archive.extract(item, root)
    if not destination.is_file():
        raise RuntimeError("Пакет обновления не содержит апдейтер. Установите новую версию через Setup.")
    return destination


class UpdateManager:
    """Keep release details on the Python side and expose pollable status."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._status: dict[str, object] = {"state": "idle"}
        self._release: Release | None = None
        self._package: Path | None = None

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._status)

    def check(self) -> dict[str, object]:
        with self._lock:
            if not installed_application():
                self._status = {"state": "unavailable"}
                return dict(self._status)
            if self._status["state"] in {"checking", "downloading", "ready", "installing"}:
                return dict(self._status)
            self._status = {"state": "checking"}
        Thread(target=self._check, daemon=True).start()
        return self.status()

    def _check(self) -> None:
        try:
            release = fetch_newer_release(__version__)
            with self._lock:
                self._release = release
                self._status = {"state": "available", "version": release.version} if release else {"state": "current"}
        except Exception:
            with self._lock:
                self._status = {"state": "check_failed"}

    def download(self) -> dict[str, object]:
        with self._lock:
            if not installed_application() or self._release is None or self._status["state"] not in {"available", "failed"}:
                return {"state": "failed", "error": "Обновление недоступно."}
            self._status = {"state": "downloading", "version": self._release.version, "received": 0, "total": 0}
            release = self._release
        Thread(target=self._download, args=(release,), daemon=True).start()
        return self.status()

    def _download(self, release: Release) -> None:
        def progress(received: int, total: int) -> None:
            with self._lock:
                self._status.update(received=received, total=total)

        try:
            package = download_verified(release, progress)
            with self._lock:
                self._package = package
                self._status = {"state": "ready", "version": release.version}
        except Exception as exc:
            with self._lock:
                self._status = {"state": "failed", "version": release.version, "error": str(exc)}

    def install(self) -> dict[str, object]:
        with self._lock:
            if not installed_application() or self._status["state"] != "ready" or self._package is None:
                return {"state": "failed", "error": "Обновление ещё не готово к установке."}
            package = self._package
            self._status = {"state": "installing"}
        try:
            updater = extract_updater(package)
            subprocess.Popen(  # noqa: S603 - updater comes from the verified package and arguments are not shell-expanded.
                [str(updater), "--package", str(package), "--app-dir", str(Path(sys.executable).parent), "--pid", str(os.getpid())],
                cwd=str(updater.parent),
            )
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            with self._lock:
                self._status = {"state": "ready", "version": self._release.version if self._release else "", "error": str(exc)}
                return dict(self._status)
        return {"state": "installing"}
