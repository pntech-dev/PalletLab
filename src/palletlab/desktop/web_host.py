"""pywebview host for the compiled React application."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from palletlab.application.service import ApplicationService
from palletlab.application.step_import_service import StepImportService
from palletlab.application.update_manager import UpdateManager
from palletlab.application.snapshots import SNAPSHOT_VERSION
from palletlab.exporters.solidworks import SolidWorksMaterialLibraryError, available_materials
from palletlab.version import __version__


class WebApplicationApi:
    """Minimal bridge exposed to JavaScript while application commands migrate."""

    def __init__(self) -> None:
        self._window: Any | None = None
        self._step_imports = StepImportService()
        self._updates = UpdateManager()
        self._assets = _StepAssetServer()
        self._settings = _WebSettings()
        self._project_path: str | None = None

    def attach_window(self, window: Any) -> None:
        self._window = window

    def frontend_url(self, root: Path) -> str:
        """Serve the bundled frontend from the same origin as STEP buffers."""
        return self._assets.set_frontend_root(root)

    def status(self) -> dict[str, Any]:
        """Return a dependency-free handshake for the frontend shell."""
        return {"application": "PalletLab", "version": __version__, "snapshotVersion": SNAPSHOT_VERSION}

    def check_update(self) -> dict[str, object]:
        return self._updates.check()

    def update_status(self) -> dict[str, object]:
        return self._updates.status()

    def download_update(self) -> dict[str, object]:
        return self._updates.download()

    def install_update(self) -> dict[str, object]:
        if self._window is None:
            return {"state": "failed", "error": "Окно приложения недоступно."}
        result = self._updates.install()
        if result.get("state") == "installing":
            self._window.destroy()
        return result

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

    def save_project(self, project: object, save_as: bool = False) -> dict[str, Any]:
        path = self._choose_file("save") if save_as or self._project_path is None else self._project_path
        if path is None:
            return {"ok": False, "cancelled": True}
        response = ApplicationService().save(project, path)
        if response.get("ok"):
            self._project_path = path
        return response

    def open_project(self) -> dict[str, Any]:
        path = self._choose_file("open")
        if path is None:
            return {"ok": False, "cancelled": True}
        response = ApplicationService().load(path)
        if response.get("ok"):
            self._project_path = path
        return response

    def export_kompas(self, project: object) -> dict[str, Any]:
        directory = self._choose_directory("Выберите папку для экспорта КОМПАС-3D")
        return {"ok": False, "cancelled": True} if directory is None else ApplicationService().export_kompas(project, directory)

    def select_solidworks_template(self, kind: object) -> dict[str, Any]:
        """Select exactly one template for the settings modal."""
        if kind not in {"part", "assembly"}:
            return {"ok": False, "error": "Некорректный тип шаблона SolidWorks."}
        path = self._choose_file(f"solidworks_{kind}")
        return {"ok": False, "cancelled": True} if path is None else {"ok": True, "path": path}

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

    def select_drawing_template(self, cad: object) -> dict[str, Any]:
        if cad not in {"solidworks", "kompas"}:
            return {"ok": False, "error": "Некорректная CAD-система."}
        path = self._choose_file(f"{cad}_drawing")
        return {"ok": False, "cancelled": True} if path is None else {"ok": True, "path": path}

    def drawing_settings(self) -> dict[str, Any]:
        return {"ok": True, "templates": self._settings.drawing_templates()}

    def save_drawing_template(self, cad: object, template: object) -> dict[str, Any]:
        if cad not in {"solidworks", "kompas"} or not isinstance(template, str) or not template:
            return {"ok": False, "error": "Некорректные настройки шаблона чертежа."}
        return {"ok": True} if self._settings.save_drawing_template(cad, template) else {
            "ok": False,
            "error": "Не удалось сохранить шаблон чертежа.",
        }

    def create_drawings(self, project: object, cad: object, scope: object, template: object) -> dict[str, Any]:
        directory = self._choose_directory("Выберите папку экспорта с CAD-моделями")
        if directory is None:
            return {"ok": False, "cancelled": True}
        service = ApplicationService()
        response = service.create_drawings(project, cad, scope, directory, template)
        if not response.get("needsTemplate"):
            return response

        selected = self._choose_file(f"{cad}_drawing")
        if selected is None:
            if cad == "kompas":
                # KOMPAS can deliberately use its own configured default.
                return service.create_drawings(project, cad, scope, directory, None)
            return {"ok": False, "error": "Создание чертежей SolidWorks отменено: не выбран шаблон."}
        if not self._settings.save_drawing_template(str(cad), selected):
            return {"ok": False, "error": "Не удалось сохранить шаблон чертежа."}
        return service.create_drawings(project, cad, scope, directory, selected)

    def solidworks_export_settings(self) -> dict[str, Any]:
        """Load web CAD preferences independently of the temporary web origin."""
        return {"ok": True, "options": self._settings.solidworks_options()}

    def save_solidworks_export_settings(self, options: object) -> dict[str, Any]:
        if not self._settings.save_solidworks_options(options):
            return {"ok": False, "error": "Не удалось сохранить настройки экспорта SolidWorks."}
        return {"ok": True}

    def import_step_model(self) -> dict[str, Any]:
        """Choose a source model and start its isolated cached import."""
        path = self._choose_file("step")
        return {"ok": False, "cancelled": True} if path is None else self._step_imports.start(path)

    def restore_step_model(self, path: object) -> dict[str, Any]:
        """Restore a model referenced by a project using the regular import/cache path."""
        if not isinstance(path, str) or not path.strip():
            return {"ok": False, "error": "В проекте не указан путь к STEP-модели."}
        return self._step_imports.start(path)

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
                else ("SolidWorks drawing template (*.drwdot)",)
                if mode == "solidworks_drawing"
                else ("КОМПАС-3D drawing template (*.cdt)",)
                if mode == "kompas_drawing"
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


class _WebSettings:
    """Small persistent store for preferences that must survive a new webview URL."""

    _KEYS = ("partTemplate", "assemblyTemplate", "materialLibrary", "materialName")

    def __init__(self, path: Path | None = None) -> None:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "PalletLab"
        self._path = path or root / "web_settings.json"
        self._lock = Lock()

    def solidworks_options(self) -> dict[str, str] | None:
        with self._lock:
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        options = payload.get("solidworks") if isinstance(payload, dict) else None
        if not isinstance(options, dict) or any(not isinstance(options.get(key), str) for key in self._KEYS):
            return None
        return {key: options[key] for key in self._KEYS}

    def save_solidworks_options(self, options: object) -> bool:
        if not isinstance(options, dict) or any(not isinstance(options.get(key), str) or not options[key] for key in self._KEYS):
            return False
        normalized = {key: options[key] for key in self._KEYS}
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                payload = {}
                try:
                    payload = json.loads(self._path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                if not isinstance(payload, dict):
                    payload = {}
                payload["solidworks"] = normalized
                serialized = json.dumps(payload, ensure_ascii=False, indent=2)
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self._path.parent, delete=False) as stream:
                    stream.write(serialized)
                    temporary = Path(stream.name)
                try:
                    temporary.replace(self._path)
                except OSError:
                    # Some sandboxed Windows hosts deny atomic replacement in
                    # their temporary directory.  Preferences are noncritical,
                    # so a direct replacement is an acceptable fallback.
                    self._path.write_text(serialized, encoding="utf-8")
                    temporary.unlink(missing_ok=True)
            except OSError:
                return False
        return True

    def drawing_templates(self) -> dict[str, str]:
        with self._lock:
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        templates = payload.get("drawingTemplates") if isinstance(payload, dict) else None
        if not isinstance(templates, dict):
            return {}
        return {cad: value for cad, value in templates.items() if cad in {"solidworks", "kompas"} and isinstance(value, str)}

    def save_drawing_template(self, cad: str, template: str) -> bool:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    payload = json.loads(self._path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                templates = payload.setdefault("drawingTemplates", {})
                if not isinstance(templates, dict):
                    templates = payload["drawingTemplates"] = {}
                templates[cad] = template
                self._write(payload)
            except OSError:
                return False
        return True

    def _write(self, payload: dict[str, object]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self._path.parent, delete=False) as stream:
            stream.write(serialized)
            temporary = Path(stream.name)
        try:
            temporary.replace(self._path)
        except OSError:
            self._path.write_text(serialized, encoding="utf-8")
            temporary.unlink(missing_ok=True)


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
