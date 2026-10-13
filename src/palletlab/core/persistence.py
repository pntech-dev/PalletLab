"""Versioned JSON persistence for editable pallet projects."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import BeamSection, DirectionInput
from .materials import MATERIALS, DEFAULT_MATERIAL_ID
from .project_state import ProjectState


FORMAT_VERSION = 2


class ProjectPersistenceError(ValueError):
    """Raised when a project JSON file cannot be read safely."""


def _direction_to_dict(data: DirectionInput) -> dict[str, Any]:
    return {
        "beam_height": data.beam_height,
        "beam_width": data.beam_width,
        "support_distances": list(data.support_distances),
        "first_edge_to_support": data.first_edge_to_support,
        "last_support_to_edge": data.last_support_to_edge,
        "margin_start": data.margin_start,
        "margin_end": data.margin_end,
        "round_pallet_size": data.round_pallet_size,
        "rounding_step": data.rounding_step,
        "support_positions": list(data.support_positions) if data.support_positions is not None else None,
    }


def _direction_from_dict(raw: object, name: str) -> DirectionInput:
    if not isinstance(raw, dict):
        raise ProjectPersistenceError(f"Раздел «{name}» должен быть объектом.")
    try:
        positions = raw.get("support_positions")
        if positions is not None and not isinstance(positions, list):
            raise TypeError
        distances = raw["support_distances"]
        if not isinstance(distances, list):
            raise TypeError
        return DirectionInput(
            float(raw["beam_height"]), float(raw["beam_width"]), tuple(float(value) for value in distances),
            float(raw["first_edge_to_support"]), float(raw["last_support_to_edge"]),
            float(raw["margin_start"]), float(raw["margin_end"]), bool(raw["round_pallet_size"]),
            int(raw["rounding_step"]), None if positions is None else tuple(float(value) for value in positions),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectPersistenceError(f"Раздел «{name}» содержит некорректные параметры.") from exc


def project_to_dict(state: ProjectState) -> dict[str, Any]:
    """Convert stable project and view settings to a portable JSON object."""
    if state.length_input is None or state.width_input is None:
        raise ProjectPersistenceError("Нельзя сохранить проект без рассчитанных параметров.")
    return {
        "format_version": FORMAT_VERSION,
        "pallet": {
            "length": _direction_to_dict(state.length_input),
            "width": _direction_to_dict(state.width_input),
            "upper_layer": state.upper_layer,
            "rounding_step": state.rounding_step,
            "material_id": state.material_id,
            "beam_sections": [
                {"axis": axis, "index": index, "height": section.height, "width": section.width}
                for (axis, index), section in sorted(state.beam_sections.items())
            ],
        },
        "view": {
            "camera": state.camera,
            "show_length_dimensions": state.show_length_dimensions,
            "show_width_dimensions": state.show_width_dimensions,
        },
    }


def project_from_dict(raw: object) -> ProjectState:
    """Read a stable project configuration, never restoring transient UI state."""
    if not isinstance(raw, dict) or raw.get("format_version") not in (1, FORMAT_VERSION):
        raise ProjectPersistenceError("Неподдерживаемый формат файла проекта.")
    pallet, view = raw.get("pallet"), raw.get("view")
    if not isinstance(pallet, dict) or not isinstance(view, dict):
        raise ProjectPersistenceError("В файле отсутствуют разделы поддона или вида.")
    upper_layer, rounding_step, camera = pallet.get("upper_layer"), pallet.get("rounding_step"), view.get("camera")
    material_id = pallet.get("material_id", DEFAULT_MATERIAL_ID)
    if upper_layer not in ("length", "width") or rounding_step not in (0, 5, 50) or camera not in ("isometric", "top", "front", "side") or material_id not in MATERIALS:
        raise ProjectPersistenceError("Файл содержит неподдерживаемые настройки проекта.")
    beam_sections: dict[tuple[str, int], BeamSection] = {}
    raw_sections = pallet.get("beam_sections", [])
    if not isinstance(raw_sections, list):
        raise ProjectPersistenceError("Сечения брусьев должны быть списком.")
    for item in raw_sections:
        if not isinstance(item, dict):
            raise ProjectPersistenceError("Сечение бруса содержит некорректные параметры.")
        try:
            axis, index = item["axis"], item["index"]
            height, width = float(item["height"]), float(item["width"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectPersistenceError("Сечение бруса содержит некорректные параметры.") from exc
        if axis not in ("length", "width") or not isinstance(index, int) or index < 0 or not all(
            math.isfinite(value) and value > 0 for value in (height, width)
        ):
            raise ProjectPersistenceError("Сечение бруса содержит недопустимые значения.")
        beam_sections[(axis, index)] = BeamSection(height, width)
    return ProjectState(
        length_input=_direction_from_dict(pallet.get("length"), "длина"),
        width_input=_direction_from_dict(pallet.get("width"), "ширина"),
        upper_layer=upper_layer,
        rounding_step=rounding_step,
        material_id=material_id,
        beam_sections=beam_sections,
        camera=camera,
        show_length_dimensions=bool(view.get("show_length_dimensions", True)),
        show_width_dimensions=bool(view.get("show_width_dimensions", True)),
    )


def save_project(path: str | Path, state: ProjectState) -> None:
    Path(path).write_text(json.dumps(project_to_dict(state), ensure_ascii=False, indent=2), encoding="utf-8")


def load_project(path: str | Path) -> ProjectState:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectPersistenceError("Не удалось прочитать файл проекта.") from exc
    return project_from_dict(raw)
