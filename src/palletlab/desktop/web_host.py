"""pywebview host for the compiled React application."""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from palletlab.application.service import ApplicationService
from palletlab.application.step_import_service import StepImportService
from palletlab.application.snapshots import SNAPSHOT_VERSION
from palletlab.exporters.solidworks import SolidWorksMaterialLibraryError, available_materials
from palletlab.version import __version__


class WebApplicationApi:
    """Minimal bridge exposed to JavaScript while application commands migrate."""

    def __init__(self) -> None:
        self._window: Any | None = None
        self._step_imports = StepImportService()
        self._assets = _StepAssetServer()

    def attach_window(self, window: Any) -> None:
        self._window = window

    def frontend_url(self, root: Path) -> str:
        """Serve the bundled frontend from the same origin as STEP buffers."""
        return self._assets.set_frontend_root(root)

    def status(self) -> dict[str, Any]:
        """Return a dependency-free handshake for the frontend shell."""
        return {"application": "PalletLab", "version": __version__, "snapshotVersion": SNAPSHOT_VERSION}

    def calculate(self, project: object) -> dict[str, Any]:
        """Calculate a persisted project payload for the React frontend."""
        return ApplicationService().calculate(project)

    def delete_beams(self, project: object, selection: object) -> dict[str, Any]:
        """Apply a web viewport beam selection through the domain controller."""
        return ApplicationService().delete_beams(project, selection)

    def change_beam_sections(self, project: object, selection: object, section: object) -> dict[str, Any]:
        """Change selected beam cross-sections through the domain controller."""
        return ApplicationService().change_beam_sections(project, selection, section)

    def change_beam_distance(self, project: object, target: object, face_distance: object) -> dict[str, Any]:
        """Apply an editable viewport dimension through the domain controller."""
        return ApplicationService().change_beam_distance(project, target, face_distance)

    def insert_beam(self, project: object, slot: object, clear_gap: object) -> dict[str, Any]:
        return ApplicationService().insert_beam(project, slot, clear_gap)

    def add_manual_beam(self, project: object, supports: object, options: object) -> dict[str, Any]:
        return ApplicationService().add_manual_beam(project, supports, options)

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

    def export_kompas(self, project: object) -> dict[str, Any]:
        directory = self._choose_directory("Выберите папку для экспорта КОМПАС-3D")
        return {"ok": False, "cancelled": True} if directory is None else ApplicationService().export_kompas(project, directory)

    def select_solidworks_templates(self) -> dict[str, Any]:
        part = self._choose_file("solidworks_part")
        if part is None:
            return {"ok": False, "cancelled": True}
        assembly = self._choose_file("solidworks_assembly")
        if assembly is None:
            return {"ok": False, "cancelled": True}
        return {"ok": True, "partTemplate": part, "assemblyTemplate": assembly}

    def select_solidworks_material_library(self) -> dict[str, Any]:
        library = self._choose_file("solidworks_material")
        if library is None:
            return {"ok": False, "cancelled": True}
        try:
            names = available_materials(library)
        except SolidWorksMaterialLibraryError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "materialLibrary": library, "materials": list(names)}

    def export_solidworks(self, project: object, options: object) -> dict[str, Any]:
        directory = self._choose_directory("Выберите папку для экспорта SolidWorks")
        return {"ok": False, "cancelled": True} if directory is None else ApplicationService().export_solidworks(project, directory, options)

    def import_step_model(self) -> dict[str, Any]:
        """Choose a source model and start its isolated cached import."""
        path = self._choose_file("step")
        return {"ok": False, "cancelled": True} if path is None else self._step_imports.start(path)

    def step_import_status(self, operation_id: object) -> dict[str, Any]:
        return self._step_imports.status(operation_id)

    def cancel_step_import(self, operation_id: object) -> dict[str, Any]:
        return self._step_imports.cancel(operation_id)

    def step_model_snapshot(self, operation_id: object) -> dict[str, Any]:
        response = self._step_imports.model_snapshot(operation_id)
        asset_path = response.pop("assetPath", None)
        if response.get("ok") and isinstance(asset_path, str):
            response["assetUrl"] = self._assets.register(Path(asset_path))
        return response

    def build_step_pallet(self, operation_id: object, project: object, face_index: object) -> dict[str, Any]:
        return self._step_imports.build_pallet(operation_id, project, face_index)

    def _choose_file(self, mode: str) -> str | None:
        if self._window is None:
            raise RuntimeError("Web window is not ready.")
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE if mode == "save" else webview.FileDialog.OPEN,
            save_filename="project.palletlab.json" if mode == "save" else "",
            file_types=(
                ("STEP model (*.step;*.stp)",)
                if mode == "step"
                else ("SolidWorks part template (*.prtdot)",)
                if mode == "solidworks_part"
                else ("SolidWorks assembly template (*.asmdot)",)
                if mode == "solidworks_assembly"
                else ("SolidWorks material library (*.sldmat)",)
                if mode == "solidworks_material"
                else ("PalletLab project (*.palletlab.json)",)
            ),
        )
        return str(selected[0]) if selected else None

    def _choose_directory(self, title: str) -> str | None:
        if self._window is None:
            raise RuntimeError("Web window is not ready.")
        import webview

        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory="", allow_multiple=False)
        return str(selected[0]) if selected else None


class _StepAssetServer:
    """Serve bundled web assets and opaque STEP buffers from one loopback origin."""

    def __init__(self) -> None:
        self._assets: dict[str, Path] = {}
        self._lock = Lock()
        self._frontend_root: Path | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                if self.path.startswith("/step/"):
                    self._serve_step(self.path.removeprefix("/step/"))
                    return
                self._serve_frontend()

            def _serve_step(self, token: str) -> None:
                with owner._lock:
                    path = owner._assets.get(token)
                if path is None or not path.is_file():
                    self.send_error(404)
                    return
                size = path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        self.wfile.write(chunk)

            def _serve_frontend(self) -> None:
                with owner._lock:
                    root = owner._frontend_root
                if root is None:
                    self.send_error(503)
                    return
                relative = "index.html" if self.path in ("/", "/index.html") else self.path.lstrip("/")
                path = (root / relative).resolve()
                if root not in path.parents or not path.is_file():
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        self.wfile.write(chunk)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self._server.serve_forever, daemon=True).start()

    def register(self, path: Path) -> str:
        token = path.stem.rsplit("-", 1)[-1]
        with self._lock:
            self._assets.clear()
            self._assets[token] = path
        return f"http://127.0.0.1:{self._server.server_port}/step/{token}"

    def set_frontend_root(self, root: Path) -> str:
        with self._lock:
            self._frontend_root = root.resolve()
        return f"http://127.0.0.1:{self._server.server_port}/"


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
    frontend = frontend_entrypoint()
    window = webview.create_window(
        f"PalletLab {__version__}",
        url=api.frontend_url(frontend.parent),
        js_api=api,
        width=1400,
        height=900,
        min_size=(900, 650),
        maximized=True,
    )
    api.attach_window(window)
    webview.start()
