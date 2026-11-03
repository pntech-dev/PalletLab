"""pywebview host for the compiled React application."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from palletlab.application.service import ApplicationService
from palletlab.application.snapshots import SNAPSHOT_VERSION
from palletlab.version import __version__


class WebApplicationApi:
    """Minimal bridge exposed to JavaScript while application commands migrate."""

    def __init__(self) -> None:
        self._window: Any | None = None

    def attach_window(self, window: Any) -> None:
        self._window = window

    def status(self) -> dict[str, Any]:
        """Return a dependency-free handshake for the frontend shell."""
        return {"application": "PalletLab", "version": __version__, "snapshotVersion": SNAPSHOT_VERSION}

    def calculate(self, project: object) -> dict[str, Any]:
        """Calculate a persisted project payload for the React frontend."""
        return ApplicationService().calculate(project)

    def delete_beams(self, project: object, selection: object) -> dict[str, Any]:
        """Apply a web viewport beam selection through the domain controller."""
        return ApplicationService().delete_beams(project, selection)

    def default_project(self) -> dict[str, Any]:
        """Provide the temporary frontend with a valid starting project."""
        return ApplicationService().default_project()

    def materials(self) -> list[dict[str, str]]:
        return ApplicationService().materials()

    def save_project(self, project: object) -> dict[str, Any]:
        path = self._choose_file("save")
        return {"ok": False, "cancelled": True} if path is None else ApplicationService().save(project, path)

    def open_project(self) -> dict[str, Any]:
        path = self._choose_file("open")
        return {"ok": False, "cancelled": True} if path is None else ApplicationService().load(path)

    def _choose_file(self, mode: str) -> str | None:
        if self._window is None:
            raise RuntimeError("Web window is not ready.")
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE if mode == "save" else webview.FileDialog.OPEN,
            save_filename="project.palletlab.json",
            file_types=("PalletLab project (*.palletlab.json)",),
        )
        return str(selected[0]) if selected else None


def frontend_entrypoint() -> Path:
    """Locate the Vite entrypoint in source and frozen PyInstaller builds."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    entrypoint = bundle_root / "frontend" / "dist" / "index.html"
    if not entrypoint.is_file():
        raise RuntimeError(f"React frontend is not built: {entrypoint}")
    return entrypoint


def run_web_application() -> None:
    """Open the compiled React application in a native Windows webview."""
    import webview

    api = WebApplicationApi()
    window = webview.create_window(
        f"PalletLab {__version__}",
        url=str(frontend_entrypoint()),
        js_api=api,
        width=1400,
        height=900,
        min_size=(900, 650),
        maximized=True,
    )
    api.attach_window(window)
    webview.start()
