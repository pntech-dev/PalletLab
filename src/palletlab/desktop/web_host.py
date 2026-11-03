"""pywebview host for the compiled React application."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from palletlab.application.snapshots import SNAPSHOT_VERSION
from palletlab.version import __version__


class WebApplicationApi:
    """Minimal bridge exposed to JavaScript while application commands migrate."""

    def status(self) -> dict[str, Any]:
        """Return a dependency-free handshake for the frontend shell."""
        return {"application": "PalletLab", "version": __version__, "snapshotVersion": SNAPSHOT_VERSION}


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

    webview.create_window(
        f"PalletLab {__version__}",
        url=str(frontend_entrypoint()),
        js_api=WebApplicationApi(),
        width=1400,
        height=900,
        min_size=(900, 650),
    )
    webview.start()
