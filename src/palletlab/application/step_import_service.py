"""Background STEP import operations for toolkit-independent frontends."""

from __future__ import annotations

import json
import os
import hashlib
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

import numpy as np

from palletlab.importers.step_import_protocol import consume_messages
from palletlab.core.calculator import calculate_direction
from palletlab.core.models import BeamSection, LayerInput
from palletlab.core.persistence import ProjectPersistenceError, project_from_dict
from palletlab.core.validation import CalculationError
from palletlab.step_performance import StepPerformanceTrace, geometry_footprint, write_step_performance


_MODEL_STANDARD_SECTION = BeamSection(70, 50)
# Keep a sub-visible clearance above the physical bearing plane.  STEP display
# triangles are tessellated approximations and coplanar transparent surfaces
# blend as if the machine were embedded in the wood.
_MODEL_CONTACT_CLEARANCE = 2.0


class StepImportService:
    """Run one isolated STEP import worker and expose its JSON-safe status.

    Tessellating a STEP assembly can take long enough to freeze a webview if it
    runs on the bridge thread.  The existing worker already owns the OpenCascade
    and cache boundary; this service only supervises it and turns its stdout
    protocol into a pollable operation for React and future frontends.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._operations: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def start(self, filename: str | Path) -> dict[str, Any]:
        """Start a worker and return an operation identifier without blocking."""
        path = Path(filename).expanduser().resolve()
        if path.suffix.lower() not in {".step", ".stp"}:
            return {"ok": False, "error": "Выберите STEP-модель с расширением .step или .stp."}
        if not path.is_file():
            return {"ok": False, "error": f"Файл не найден: {path}"}

        operation_id = uuid4().hex
        cached_asset = _cached_web_asset(path)
        with self._lock:
            self._operations[operation_id] = {
                "ok": True,
                "operationId": operation_id,
                "state": "completed" if cached_asset is not None else "running",
                "progress": 100 if cached_asset is not None else 0,
                "label": "STEP-модель загружена из web-кэша." if cached_asset is not None else "Запускаем импорт STEP-модели…",
                "path": str(path),
            }
        if cached_asset is not None:
            return self.status(operation_id)
        Thread(target=self._run, args=(operation_id, path), daemon=True).start()
        return self.status(operation_id)

    def status(self, operation_id: object) -> dict[str, Any]:
        """Return the latest stable operation state without exposing processes."""
        if not isinstance(operation_id, str) or not operation_id:
            return {"ok": False, "error": "Некорректный идентификатор импорта."}
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                return {"ok": False, "error": "Импорт STEP-модели не найден."}
            return dict(operation)

    def cancel(self, operation_id: object) -> dict[str, Any]:
        """Stop a still-running worker; completed operations remain readable."""
        if not isinstance(operation_id, str) or not operation_id:
            return {"ok": False, "error": "Некорректный идентификатор импорта."}
        with self._lock:
            operation = self._operations.get(operation_id)
            process = self._processes.get(operation_id)
            if operation is None:
                return {"ok": False, "error": "Импорт STEP-модели не найден."}
            if operation["state"] != "running":
                return dict(operation)
            operation.update(
                state="cancelling",
                label="Отменяем загрузку STEP-модели…",
            )
        if process is not None and process.poll() is None:
            process.terminate()
        return self.status(operation_id)

    def model_snapshot(self, operation_id: object) -> dict[str, Any]:
        """Return cached render geometry while retaining the original STEP face IDs."""
        status = self.status(operation_id)
        if not status.get("ok"):
            return status
        if status.get("state") != "completed":
            return {"ok": False, "error": "STEP-модель ещё не подготовлена."}
        trace = StepPerformanceTrace()
        try:
            from palletlab.importers.step_model import load_cached_step_model

            cached_asset = _cached_web_asset(Path(str(status["path"])))
            if cached_asset is not None:
                trace.checkpoint("asset-cache-hit", assetBytes=cached_asset.stat().st_size)
                report = trace.report()
                write_step_performance("model-snapshot", report)
                return {"ok": True, "assetPath": str(cached_asset), "performance": report}
            model = load_cached_step_model(str(status["path"]))
            if model is None:
                raise RuntimeError("Кэш STEP-модели не найден.")
            trace.checkpoint("cache-load", **geometry_footprint(model.mesh, model.edges))
            asset = _write_model_asset(model)
            trace.checkpoint("snapshot-packed", **asset["metrics"])
            report = trace.report()
            write_step_performance("model-snapshot", report)
            return {"ok": True, "assetPath": asset["path"], "performance": report}
        except Exception as exc:
            trace.checkpoint("failed", error=str(exc))
            write_step_performance("model-snapshot", trace.report())
            return {"ok": False, "error": str(exc)}

    def build_pallet(self, operation_id: object, project: object, face_index: object) -> dict[str, Any]:
        """Build the standard STEP-driven pallet from one selected CAD face."""
        if not isinstance(face_index, int) or isinstance(face_index, bool) or face_index < 0:
            return {"ok": False, "error": "Некорректная грань опоры."}
        status = self.status(operation_id)
        if not status.get("ok"):
            return status
        if status.get("state") != "completed":
            return {"ok": False, "error": "STEP-модель ещё не подготовлена."}
        trace = StepPerformanceTrace()
        try:
            from palletlab.application.service import ApplicationService
            from palletlab.application.snapshots import project_snapshot
            from palletlab.importers.step_model import (
                coplanar_supports,
                load_cached_step_model,
                pallet_inputs_from_supports,
            )

            state = project_from_dict(project)
            model = load_cached_step_model(str(status["path"]))
            if model is None:
                raise RuntimeError("Кэш STEP-модели не найден.")
            trace.checkpoint("cache-load", **geometry_footprint(model.mesh, model.edges))
            supports = coplanar_supports(model, face_index)
            trace.checkpoint("support-detection", supportCount=len(supports))
            if state.length_input is None or state.width_input is None:
                raise RuntimeError("В проекте отсутствуют параметры поддона.")
            provisional_bearing_height = _MODEL_STANDARD_SECTION.height * 3
            length, width, placement_matrix = pallet_inputs_from_supports(
                model,
                supports,
                length_beam_height=_MODEL_STANDARD_SECTION.height,
                length_beam_width=_MODEL_STANDARD_SECTION.width,
                width_beam_height=_MODEL_STANDARD_SECTION.height,
                width_beam_width=_MODEL_STANDARD_SECTION.width,
                length_margin_start=state.length_input.margin_start,
                length_margin_end=state.length_input.margin_end,
                width_margin_start=state.width_input.margin_start,
                width_margin_end=state.width_input.margin_end,
                round_pallet_size=state.rounding_step != 0,
                rounding_step=state.rounding_step or 5,
                reference_support_index=face_index,
                pallet_height=provisional_bearing_height,
                return_placement_matrix=True,
            )
            trace.checkpoint("model-placement-matrix")
            layers, top_edge_sections = _model_pallet_layers(length, width)
            state.manual_beams.clear()
            state.beam_sections.clear()
            state.layer_sections = top_edge_sections
            controller, errors = ApplicationService._controller_for(state)
            result = controller.calculate_layers(layers, show_error=False)
            if result is None:
                raise CalculationError(errors[-1] if errors else "Не удалось построить поддон по модели.")
            bearing_height = _model_bearing_height(result)
            # Inputs need a height before the pallet exists.  Correct the
            # local Z translation from the calculated top support plane, not
            # from an assumed stack height.  The small clearance prevents a
            # visibly sunk contact when transparent, tessellated surfaces are
            # exactly coplanar in the viewport.
            placement_matrix[2, 3] += (
                bearing_height - provisional_bearing_height + _MODEL_CONTACT_CLEARANCE
            )
            trace.checkpoint(
                "pallet-calculation",
                bearingHeight=bearing_height,
                contactClearance=_MODEL_CONTACT_CLEARANCE,
            )
            report = trace.report()
            write_step_performance("build-pallet", report)
            return {
                "ok": True,
                "snapshot": project_snapshot(state),
                "modelTransform": _viewport_transform(placement_matrix),
                "supportCount": len(supports),
                "referenceFace": face_index,
                "performance": report,
            }
        except (CalculationError, ProjectPersistenceError, RuntimeError, ValueError) as exc:
            trace.checkpoint("failed", error=str(exc))
            write_step_performance("build-pallet", trace.report())
            return {"ok": False, "error": str(exc)}

    def _run(self, operation_id: str, path: Path) -> None:
        process: subprocess.Popen[str] | None = None
        try:
            environment = os.environ.copy()
            source_root = str(Path(__file__).resolve().parents[2])
            environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
            arguments = (
                [sys.executable, "--step-import", str(path)]
                if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "palletlab.importers.step_import_worker", str(path)]
            )
            process = subprocess.Popen(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
            with self._lock:
                self._processes[operation_id] = process

            buffer = ""
            worker_error: str | None = None
            worker_done = False
            assert process.stdout is not None
            for chunk in process.stdout:
                messages, buffer = consume_messages(buffer, chunk)
                for message in messages:
                    if message["kind"] == "progress":
                        self._update(
                            operation_id,
                            progress=int(message["value"]),
                            label=str(message["label"]),
                        )
                    elif message["kind"] == "error":
                        worker_error = str(message["message"])
                    elif message["kind"] == "metrics":
                        write_step_performance("import-worker", dict(message["trace"]))
                    elif message["kind"] == "done":
                        worker_done = True

            exit_code = process.wait()
            with self._lock:
                cancelling = self._operations[operation_id]["state"] == "cancelling"
            if cancelling:
                self._finish(operation_id, "cancelled", "Загрузка STEP-модели отменена.")
            elif exit_code == 0 and worker_done and worker_error is None:
                self._finish(operation_id, "completed", "STEP-модель подготовлена и сохранена в кэше.", 100)
            else:
                stderr = process.stderr.read().strip() if process.stderr is not None else ""
                self._fail(operation_id, worker_error or stderr or "Импорт STEP-модели завершился с ошибкой.")
        except OSError as exc:
            self._fail(operation_id, str(exc))
        finally:
            with self._lock:
                self._processes.pop(operation_id, None)

    def _update(self, operation_id: str, *, progress: int, label: str) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is not None and operation["state"] == "running":
                operation.update(progress=max(0, min(100, progress)), label=label)

    def _finish(self, operation_id: str, state: str, label: str, progress: int | None = None) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is not None:
                operation.update(state=state, label=label)
                if progress is not None:
                    operation["progress"] = progress

    def _fail(self, operation_id: str, error: str) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is not None:
                operation.update(state="failed", error=error, label="Не удалось загрузить STEP-модель.")


def _write_model_asset(model: Any) -> dict[str, Any]:
    """Write one directly-fetchable binary viewport asset without JSON/base64 copies."""
    mesh, edges, faces = model.mesh, model.edges, model.faces
    raw_faces = np.asarray(mesh.faces, dtype=np.uint32)
    if raw_faces.size % 4 != 0 or not np.all(raw_faces[::4] == 3):
        raise RuntimeError("STEP-кэш содержит нетреугольную грань, которую нельзя показать в web viewport.")
    triangles = raw_faces.reshape(-1, 4)
    face_ids = np.asarray(mesh.cell_data["step_face_index"], dtype=np.int32).reshape(-1)
    if len(triangles) != len(face_ids):
        raise RuntimeError("STEP-кэш содержит несогласованные идентификаторы граней.")
    positions = np.asarray(mesh.points, dtype=np.float32).reshape(-1)
    edge_points = np.asarray(edges.points, dtype=np.float32).reshape(-1)
    edge_cells = np.asarray(edges.lines, dtype=np.uint32).reshape(-1)
    if positions.size % 3 != 0 or edge_points.size % 3 != 0:
        raise RuntimeError("STEP-кэш содержит некорректные координаты геометрии.")
    selectable_faces = [
        face.index
        for face in faces
        if face.point is not None and face.normal is not None
    ]
    bounds = [float(value) for value in mesh.bounds]
    arrays = {
        "positions": positions,
        "indices": triangles[:, 1:].reshape(-1),
        "triangleFaceIds": face_ids,
        "selectableFaceIds": np.asarray(selectable_faces, dtype=np.int32),
        "edgePoints": edge_points,
        "edgeCells": edge_cells,
    }
    encoded = {
        name: np.ascontiguousarray(values.astype(values.dtype.newbyteorder("<"), copy=False))
        for name, values in arrays.items()
    }
    offset = 0
    buffers: dict[str, dict[str, Any]] = {}
    for name, values in encoded.items():
        buffers[name] = {"offset": offset, "byteLength": values.nbytes, "dtype": values.dtype.str}
        offset += values.nbytes
    header = json.dumps({"version": 1, "bounds": bounds, "buffers": buffers}, separators=(",", ":")).encode("utf-8")
    padding = (-len(header)) % 4
    path = _web_asset_path(model.source_path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(b"PLSTEP01")
        stream.write(len(header).to_bytes(4, "little"))
        stream.write(header)
        stream.write(b"\0" * padding)
        for values in encoded.values():
            stream.write(memoryview(values))
    _prune_web_assets(directory)
    return {
        "path": str(path),
        "metrics": {
            "assetBytes": path.stat().st_size,
            "geometryBytes": offset,
            "triangleCount": len(triangles),
        },
    }


def _web_asset_path(source_path: Path) -> Path:
    source = source_path.expanduser().resolve()
    stat = source.stat()
    identity = f"{source}\0{stat.st_size}\0{stat.st_mtime_ns}\0web-v1".encode("utf-8")
    key = hashlib.sha256(identity).hexdigest()
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "PalletLab" / "step_cache" / "web_assets"
    return root / f"step-web-v1-{key}.bin"


def _cached_web_asset(source_path: Path) -> Path | None:
    try:
        path = _web_asset_path(source_path)
        if not path.is_file():
            return None
        with path.open("rb") as stream:
            magic = stream.read(8)
            header_length = int.from_bytes(stream.read(4), "little")
            header = json.loads(stream.read(header_length))
        if magic != b"PLSTEP01" or header.get("version") != 1:
            path.unlink(missing_ok=True)
            return None
        return path
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _prune_web_assets(directory: Path) -> None:
    try:
        assets = sorted(directory.glob("step-web-v1-*.bin"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
        for asset in assets[32:]:
            asset.unlink(missing_ok=True)
    except OSError:
        pass


def _viewport_transform(placement_matrix: Any) -> list[float]:
    """Convert Python XYZ affine transform to the viewport's XZY coordinate system."""
    matrix = np.asarray(placement_matrix, dtype=float)
    if matrix.shape != (4, 4):
        raise RuntimeError("Некорректное преобразование STEP-модели.")
    swap_yz = np.array(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)), dtype=float)
    viewport_matrix = swap_yz @ matrix @ swap_yz
    # Geometry coordinates are divided from millimetres to metres before the
    # matrix is applied in Three.js. Rotation/mirroring are unitless, but the
    # translation must use the same metre coordinate system.
    viewport_matrix[:3, 3] /= 1000
    # Three.js Matrix4.fromArray expects column-major storage.
    return [float(value) for value in viewport_matrix.T.reshape(-1)]


def _model_pallet_layers(length_input: Any, width_input: Any) -> tuple[list[LayerInput], dict[tuple[str, int], BeamSection]]:
    """Use the same three-layer STEP construction as the existing desktop UI."""
    length = replace(
        length_input,
        beam_height=_MODEL_STANDARD_SECTION.height,
        beam_width=_MODEL_STANDARD_SECTION.width,
    )
    width = replace(
        width_input,
        beam_height=_MODEL_STANDARD_SECTION.height,
        beam_width=_MODEL_STANDARD_SECTION.width,
    )
    directions = {"length": length, "width": width}
    bottom_axis = (
        "length"
        if calculate_direction(length).pallet_size >= calculate_direction(width).pallet_size
        else "width"
    )
    middle_axis = "width" if bottom_axis == "length" else "length"
    # Every centre in the upper layer is inferred from an actual machine
    # support.  Unlike a generic pallet, shortening outer upper beams would
    # put supports at the edge 45 mm below the remaining bearing plane.
    # Keep the whole support layer at one height.
    top_sections: dict[tuple[str, int], BeamSection] = {}
    return (
        [
            LayerInput(bottom_axis, bottom_axis, directions[bottom_axis]),
            LayerInput(middle_axis, middle_axis, directions[middle_axis]),
            LayerInput("layer-1", bottom_axis, directions[bottom_axis]),
        ],
        top_sections,
    )


def _model_bearing_height(result: Any) -> float:
    """Return the single top plane of the STEP model's support layer."""
    support_beams = [beam for beam in result.beams_3d if beam.layer_id == "layer-1"]
    if not support_beams:
        raise CalculationError("Не найдены несущие брусья верхнего слоя поддона.")
    tops = [beam.z + beam.size_z / 2 for beam in support_beams]
    bearing_height = tops[0]
    if any(not np.isclose(top, bearing_height, atol=1e-6) for top in tops[1:]):
        raise CalculationError("Несущие брусья верхнего слоя находятся на разной высоте.")
    return float(bearing_height)
