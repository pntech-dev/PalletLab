"""Crash-recovery snapshots stored outside the user's project folders."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from uuid import uuid4

from .persistence import save_project
from .project_state import ProjectState


AUTOSAVE_LIMIT = 3


def default_autosave_directory() -> Path:
    """Return the local Windows data directory without roaming user snapshots."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "PalletLab" / "autosave"


class AutosaveStore:
    """Maintain a small, isolated rolling set of project recovery snapshots."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else default_autosave_directory()
        self._unsaved_session = uuid4().hex
        self._project_key = f"unsaved-{self._unsaved_session}"

    def set_project(self, path: str | Path | None) -> None:
        """Associate subsequent snapshots with a manually saved project path."""
        if path is None:
            self._project_key = f"unsaved-{self._unsaved_session}"
            return
        resolved = str(Path(path).resolve()).casefold()
        fingerprint = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
        self._project_key = f"project-{fingerprint}"

    def clear(self) -> None:
        """Remove all recovery snapshots after an explicit user save."""
        if not self.directory.exists():
            return
        for snapshot in self.directory.glob("*.autosave.palletlab.json"):
            snapshot.unlink(missing_ok=True)

    def save(self, state: ProjectState) -> Path:
        """Write a snapshot, retaining only the three newest successful saves."""
        self.directory.mkdir(parents=True, exist_ok=True)
        snapshot = self.directory / f"{self._project_key}-{time.time_ns()}.autosave.palletlab.json"
        save_project(snapshot, state)
        snapshots = self._snapshots_for_current_project()
        for obsolete in snapshots[:-AUTOSAVE_LIMIT]:
            obsolete.unlink(missing_ok=True)
        return snapshot

    def _snapshots_for_current_project(self) -> list[Path]:
        pattern = f"{self._project_key}-*.autosave.palletlab.json"
        return sorted(
            self.directory.glob(pattern),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
