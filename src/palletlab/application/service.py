"""Commands shared by the current and future desktop frontends."""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, cast

from palletlab.application.snapshots import project_snapshot
from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.models import BeamSection, DirectionInput, LayerInput
from palletlab.core.materials import MATERIALS
from palletlab.core.persistence import ProjectPersistenceError, load_project, project_from_dict, project_to_dict, save_project
from palletlab.core.project_state import ProjectState
from palletlab.exporters.kompas import KompasExportError, export_pallet as export_kompas_pallet
from palletlab.exporters.solidworks import SolidWorksExportError, export_pallet as export_solidworks_pallet
from palletlab.exporters.drawings import DrawingExportError, DrawingScope, DrawingTemplateError
from palletlab.exporters.kompas import create_drawings as create_kompas_drawings
from palletlab.exporters.solidworks import create_drawings as create_solidworks_drawings


class ApplicationService:
    """Run validated project commands without exposing a GUI toolkit to callers."""

    def calculate(self, project: object) -> dict[str, Any]:
        """Validate *project*, rebuild it and return a frontend-safe snapshot."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}

        controller, errors = self._controller_for(state)
        result = controller.recalculate_from_state(show_error=False)
        if result is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def delete_beams(self, project: object, selection: object) -> dict[str, Any]:
        """Delete the selected rendered beams through the existing controller command."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}
        selections, error = _deletion_selection(selection)
        if error:
            return {"ok": False, "error": error}

        controller, errors = self._controller_for(state)
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        for layer_id, indices in selections.items():
            for index in indices:
                if not controller.set_deletion_selection(layer_id, index, True):
                    return {"ok": False, "error": errors[-1] if errors else "Выбранный брус больше не существует."}
        if controller.confirm_deletion() is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось удалить выбранные брусья."}
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось пересчитать поддон."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def change_beam_sections(self, project: object, selection: object, section: object) -> dict[str, Any]:
        """Apply one validated cross-section to selected rendered beams."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}
        selections, error = _deletion_selection(selection)
        if error:
            return {"ok": False, "error": error}
        beam_section, error = _beam_section(section)
        if error:
            return {"ok": False, "error": error}

        controller, errors = self._controller_for(state)
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        for layer_id, indices in selections.items():
            for index in indices:
                controller.set_section_selection(layer_id, index, True)
        if controller.apply_section_change(beam_section) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось изменить сечение бруса."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def change_beam_distance(self, project: object, target: object, face_distance: object) -> dict[str, Any]:
        """Move a rendered beam face using the established controller rules.

        The viewport sends the identity already present in an editable dimension
        snapshot.  Keeping the conversion here means React never needs to know
        how support distances, manual beams, or pallet envelope dimensions are
        represented in the persisted project.
        """
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}
        layer_id, beam_index, error = _distance_target(target)
        if error:
            return {"ok": False, "error": error}
        if (
            not isinstance(face_distance, (int, float))
            or isinstance(face_distance, bool)
            or not isfinite(face_distance)
        ):
            return {"ok": False, "error": "Расстояние должно быть конечным числом."}

        controller, errors = self._controller_for(state)
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        controller.begin_distance_edit(layer_id, beam_index)
        if controller.confirm_distance_edit(float(face_distance)) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось изменить расстояние."}
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось пересчитать поддон."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def insert_beam(self, project: object, slot: object, clear_gap: object) -> dict[str, Any]:
        """Insert one beam through a snapshot insertion slot."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}
        insertion_slot, error = _insertion_slot(slot)
        if error:
            return {"ok": False, "error": error}
        if not isinstance(clear_gap, (int, float)) or isinstance(clear_gap, bool) or not isfinite(clear_gap):
            return {"ok": False, "error": "Зазор должен быть конечным числом."}
        controller, errors = self._controller_for(state)
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        if not controller.begin_insertion(insertion_slot):
            return {"ok": False, "error": "Точка вставки больше недоступна."}
        if controller.confirm_insertion(float(clear_gap)) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось добавить брус."}
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось пересчитать поддон."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def add_manual_beam(self, project: object, supports: object, options: object) -> dict[str, Any]:
        """Create a manually supported beam selected in the web viewport."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}
        parsed_supports, error = _manual_supports(supports)
        if error:
            return {"ok": False, "error": error}
        distance, section, reference, reference_face, start_point, error = _manual_options(options)
        if error:
            return {"ok": False, "error": error}
        controller, errors = self._controller_for(state)
        if controller.recalculate_from_state(show_error=False) is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось рассчитать поддон."}
        result = controller.add_manual_beam(
            parsed_supports[0], parsed_supports[1], distance, section,
            reference_support=reference, reference_face=reference_face,
            start_point=start_point,
        )
        if result is None:
            return {"ok": False, "error": errors[-1] if errors else "Не удалось добавить брус."}
        return {"ok": True, "snapshot": project_snapshot(state)}

    def default_project(self) -> dict[str, Any]:
        """Return the same starting configuration as the current desktop reset."""
        length = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100, True, 50)
        width = DirectionInput(70, 50, (560, 720), 277, 179, 100, 100, True, 50)
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

    def export_kompas(self, project: object, parent_directory: object) -> dict[str, Any]:
        """Recalculate and export the current project through KOMPAS-3D.

        The bridge receives a persisted project rather than a viewport snapshot so
        CAD output is always produced by the same calculation path as PyQt.
        """
        state, directory, error = self._export_input(project, parent_directory)
        if error:
            return {"ok": False, "error": error}
        result, error = self._calculate_result(state)
        if error:
            return {"ok": False, "error": error}
        try:
            output = export_kompas_pallet(result, directory, state.material_id)
        except KompasExportError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "output": str(output)}

    def export_solidworks(self, project: object, parent_directory: object, options: object) -> dict[str, Any]:
        """Recalculate and export the current project through SolidWorks."""
        state, directory, error = self._export_input(project, parent_directory)
        if error:
            return {"ok": False, "error": error}
        templates, material_library, material_name, error = _solidworks_options(options)
        if error:
            return {"ok": False, "error": error}
        result, error = self._calculate_result(state)
        if error:
            return {"ok": False, "error": error}
        try:
            output = export_solidworks_pallet(
                result,
                directory,
                templates,
                state.material_id,
                material_library,
                material_name,
            )
        except SolidWorksExportError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "output": str(output)}

    def create_drawings(
        self,
        project: object,
        cad: object,
        scope: object,
        model_directory: object,
        template: object,
    ) -> dict[str, Any]:
        """Create native drawings from an existing web-exported CAD directory."""
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return {"ok": False, "error": str(exc)}
        if cad not in {"solidworks", "kompas"}:
            return {"ok": False, "error": "Выберите CAD-систему для создания чертежей."}
        scopes = {item.value: item for item in DrawingScope}
        if scope not in scopes:
            return {"ok": False, "error": "Выберите состав чертежей."}
        if not isinstance(model_directory, str) or not Path(model_directory).is_dir():
            return {"ok": False, "error": "Выберите папку с экспортированными CAD-моделями."}
        if template is not None and (not isinstance(template, str) or not template.strip()):
            return {"ok": False, "error": "Некорректный шаблон чертежа."}

        result, error = self._calculate_result(state)
        if error:
            return {"ok": False, "error": error}
        try:
            create = create_solidworks_drawings if cad == "solidworks" else create_kompas_drawings
            output = create(Path(model_directory), scopes[scope], template or None, result)
        except DrawingTemplateError as exc:
            return {"ok": False, "error": str(exc), "needsTemplate": True}
        except DrawingExportError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "output": str(output)}

    def _export_input(self, project: object, parent_directory: object) -> tuple[ProjectState | None, Path | None, str | None]:
        try:
            state = project_from_dict(project)
        except ProjectPersistenceError as exc:
            return None, None, str(exc)
        if not isinstance(parent_directory, str) or not parent_directory.strip():
            return None, None, "Выберите папку для экспорта."
        directory = Path(parent_directory)
        if not directory.is_dir():
            return None, None, "Выбранная папка для экспорта не существует."
        return state, directory, None

    def _calculate_result(self, state: ProjectState | None) -> tuple[Any | None, str | None]:
        if state is None:
            return None, "Некорректный проект."
        controller, errors = self._controller_for(state)
        result = controller.recalculate_from_state(show_error=False)
        if result is None:
            return None, errors[-1] if errors else "Не удалось рассчитать поддон."
        return result, None

    @staticmethod
    def _controller_for(state: ProjectState) -> tuple[PalletController, list[str]]:
        errors: list[str] = []
        controller = PalletController(
            state,
            _HeadlessView(),
            on_calculated=lambda _result: None,
            on_error=lambda error, _show: errors.append(str(error)),
            on_stale_changed=lambda _stale: None,
            timer=_HeadlessTimer(),
        )
        return controller, errors


def _deletion_selection(selection: object) -> tuple[dict[str, tuple[int, ...]], str | None]:
    """Validate the small bridge payload before it reaches controller state."""
    if not isinstance(selection, dict) or not selection:
        return {}, "Выберите хотя бы один брус для удаления."

    validated: dict[str, tuple[int, ...]] = {}
    for layer_id, indices in selection.items():
        if not isinstance(layer_id, str) or not isinstance(indices, list):
            return {}, "Некорректный набор брусьев для удаления."
        if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in indices):
            return {}, "Некорректный набор брусьев для удаления."
        unique_indices = tuple(sorted(set(indices)))
        if not unique_indices:
            return {}, "Некорректный набор брусьев для удаления."
        validated[layer_id] = unique_indices
    return validated, None


def _beam_section(section: object) -> tuple[BeamSection | None, str | None]:
    """Parse the frontend cross-section without accepting malformed numbers."""
    if not isinstance(section, dict):
        return None, "Некорректное сечение бруса."
    height = section.get("height")
    width = section.get("width")
    if (
        not isinstance(height, (int, float))
        or isinstance(height, bool)
        or not isinstance(width, (int, float))
        or isinstance(width, bool)
        or not isfinite(height)
        or not isfinite(width)
        or height <= 0
        or width <= 0
    ):
        return None, "Высота и ширина сечения должны быть числами больше нуля."
    return BeamSection(float(height), float(width)), None


def _distance_target(target: object) -> tuple[str, int, str | None]:
    """Validate an editable-dimension identity received over the web bridge."""
    if not isinstance(target, dict):
        return "", 0, "Некорректная размерная линия."
    layer_id = target.get("layerId")
    beam_index = target.get("beamIndex")
    if (
        not isinstance(layer_id, str)
        or not layer_id
        or not isinstance(beam_index, int)
        or isinstance(beam_index, bool)
        or beam_index < 0
    ):
        return "", 0, "Некорректная размерная линия."
    return layer_id, beam_index, None


def _insertion_slot(slot: object):
    from palletlab.core.models import InsertionSlot
    if not isinstance(slot, dict):
        return None, "Некорректная точка вставки."
    axis, layer_id, index, maximum, suggested = (
        slot.get("axis"), slot.get("layerId"), slot.get("afterBeamIndex"),
        slot.get("maximumClearGap"), slot.get("suggestedClearGap"),
    )
    if axis not in ("length", "width") or not isinstance(layer_id, str) or not isinstance(index, int) or index < 0:
        return None, "Некорректная точка вставки."
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) for value in (maximum, suggested)):
        return None, "Некорректная точка вставки."
    return InsertionSlot(axis, index, float(maximum), float(suggested), layer_id), None


def _manual_supports(value: object):
    if not isinstance(value, list) or len(value) != 2:
        return None, "Выберите две разные параллельные опоры."
    parsed = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("layerId"), str) or not isinstance(item.get("layerIndex"), int):
            return None, "Некорректная опора для нового бруса."
        parsed.append((item["layerId"], item["layerIndex"]))
    if parsed[0] == parsed[1]:
        return None, "Выберите две разные параллельные опоры."
    return tuple(parsed), None


def _manual_options(value: object):
    if not isinstance(value, dict):
        return 0.0, None, None, None, None, "Некорректные параметры нового бруса."
    distance, section = value.get("distance"), value.get("section")
    beam_section, error = _beam_section(section)
    if error or not isinstance(distance, (int, float)) or isinstance(distance, bool) or not isfinite(distance):
        return 0.0, None, None, None, None, error or "Расстояние должно быть конечным числом."
    raw_start_point = value.get("startPoint")
    if raw_start_point is None:
        start_point = None
    elif (not isinstance(raw_start_point, list) or len(raw_start_point) != 3
          or any(not isinstance(item, (int, float)) or isinstance(item, bool) or not isfinite(item) for item in raw_start_point)):
        return 0.0, None, None, None, None, "Некорректная точка начала нового бруса."
    else:
        start_point = tuple(float(item) for item in raw_start_point)
    reference = value.get("reference")
    reference_face = value.get("referenceFace")
    if reference is None:
        return float(distance), beam_section, None, None, start_point, None
    parsed, error = _manual_supports([reference, {"layerId": "_placeholder", "layerIndex": 0}])
    if error or reference_face not in {"x_min", "x_max", "y_min", "y_max"}:
        return 0.0, None, None, None, None, "Некорректная грань точки отсчёта."
    return float(distance), beam_section, parsed[0], reference_face, start_point, None


def _solidworks_options(value: object) -> tuple[tuple[str, str] | None, str | None, str | None, str | None]:
    """Validate the explicit SolidWorks resources selected in the web UI."""
    if not isinstance(value, dict):
        return None, None, None, "Некорректные параметры экспорта SolidWorks."
    part_template = value.get("partTemplate")
    assembly_template = value.get("assemblyTemplate")
    material_library = value.get("materialLibrary")
    material_name = value.get("materialName")
    values = (part_template, assembly_template, material_library, material_name)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        return None, None, None, "Выберите шаблоны и материал SolidWorks перед экспортом."
    paths = (Path(part_template), Path(assembly_template), Path(material_library))
    if any(not path.is_file() for path in paths):
        return None, None, None, "Выбранный файл SolidWorks больше не существует."
    return (part_template, assembly_template), material_library, material_name, None


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
