"""Commands shared by the current and future desktop frontends."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from palletlab.application.snapshots import project_snapshot
from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.models import DirectionInput, LayerInput
from palletlab.core.materials import MATERIALS
from palletlab.core.persistence import ProjectPersistenceError, load_project, project_from_dict, project_to_dict, save_project
from palletlab.core.project_state import ProjectState


class ApplicationService:
    """Run validated project commands without exposing a GUI toolkit to callers."""

    def calculate(self, project: object) -> dict[str, Any]:
        """Validate *project*, rebuild it and return a frontend-safe snapshot."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}

        errors: list[str] = []
        controller = PalletController(
            state,
            _HeadlessView(),
            on_calculated=lambda _result: None,
            on_error=lambda error, _show: errors.append(str(error)),
            on_stale_changed=lambda _stale: None,
            timer=_HeadlessTimer(),
        )
        result = controller.recalculate_from_state(show_error=False)
        if result is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def default_project(self) -> dict[str, Any]:
        """Return the same starting configuration as the current desktop reset."""
        length = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100)
        width = DirectionInput(70, 50, (560, 720), 277, 179, 100, 100)
        layers = [
            LayerInput("length", "length", length),
            LayerInput("width", "width", width),
            LayerInput("layer-1", "length", length),
        ]
        state = ProjectState(
            length_input=length,
            width_input=width,
            layers=layers,
            multi_layer_mode=True,
        )
        return cast(dict[str, Any], project_to_dict(state))

    def materials(self) -> list[dict[str, str]]:
        """Return selectable pallet materials without leaking CAD-specific fields."""
        return [{"id": material.id, "name": material.name} for material in MATERIALS.values()]

    def save(self, project: object, path: str) -> dict[str, Any]:
        try:
            state = project_from_dict(project)
            save_project(Path(path), state)
        except (OSError, ProjectPersistenceError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def load(self, path: str) -> dict[str, Any]:
        try:
            return {"ok": True, "project": project_to_dict(load_project(Path(path)))}
        except (OSError, ProjectPersistenceError) as exc:
            return {"ok": False, "error": str(exc)}


class _Signal:
    def connect(self, _callback: object) -> None:
        pass


class _HeadlessTimer:
    """Satisfy controller scheduling without constructing a Qt event loop."""

    def __init__(self) -> None:
        self.timeout = _Signal()

    def setSingleShot(self, _value: bool) -> None:
        pass

    def setInterval(self, _value: int) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _HeadlessView:
    """Accept rendering notifications while the web viewport is still pending."""

    def show_pallet(self, _result: object, **_kwargs: object) -> None:
        pass
