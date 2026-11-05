"""Background STEP import operations for toolkit-independent frontends."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from palletlab.importers.step_import_protocol import consume_messages


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
        with self._lock:
            self._operations[operation_id] = {
                "ok": True,
                "operationId": operation_id,
                "state": "running",
                "progress": 0,
                "label": "Запускаем импорт STEP-модели…",
                "path": str(path),
            }
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
        try:
            from palletlab.importers.step_model import load_cached_step_model

            model = load_cached_step_model(str(status["path"]))
            if model is None:
                raise RuntimeError("Кэш STEP-модели не найден.")
            return {"ok": True, "model": _snapshot_from_cached_model(model)}
        except Exception as exc:
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


def _snapshot_from_cached_model(model: Any) -> dict[str, Any]:
    """Flatten triangle mesh data into a JSON bridge payload for Three.js.

    The worker cache already stores the tessellated surface plus one original
    STEP face ID per rendered triangle. Keeping that array intact is essential:
    a browser click can later be mapped back to support detection without
    re-reading or approximating the CAD topology in JavaScript.
    """
    faces = model.mesh.faces
    face_ids = model.mesh.cell_data["step_face_index"]
    indices: list[int] = []
    triangle_face_ids: list[int] = []
    cursor = 0
    triangle_index = 0
    while cursor < len(faces):
        point_count = int(faces[cursor])
        if point_count != 3:
            raise RuntimeError("STEP-кэш содержит нетреугольную грань, которую нельзя показать в web viewport.")
        indices.extend(int(value) for value in faces[cursor + 1:cursor + 4])
        triangle_face_ids.append(int(face_ids[triangle_index]))
        cursor += point_count + 1
        triangle_index += 1
    if triangle_index != len(face_ids):
        raise RuntimeError("STEP-кэш содержит несогласованные идентификаторы граней.")

    selectable_faces = [
        face.index
        for face in model.faces
        if face.point is not None and face.normal is not None
    ]
    bounds = [float(value) for value in model.mesh.bounds]
    return {
        "positions": [float(value) for point in model.mesh.points for value in point],
        "indices": indices,
        "triangleFaceIds": triangle_face_ids,
        "selectableFaceIds": selectable_faces,
        "edgePositions": _edge_segments(model.edges),
        "bounds": bounds,
    }


def _edge_segments(edges: Any) -> list[float]:
    """Flatten cached feature-edge polylines into independent Three.js segments."""
    lines = edges.lines
    points = edges.points
    segments: list[float] = []
    cursor = 0
    while cursor < len(lines):
        point_count = int(lines[cursor])
        point_ids = [int(value) for value in lines[cursor + 1:cursor + point_count + 1]]
        for start, end in zip(point_ids, point_ids[1:]):
            segments.extend(float(value) for value in points[start])
            segments.extend(float(value) for value in points[end])
        cursor += point_count + 1
    return segments
