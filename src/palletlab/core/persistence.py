"""Versioned JSON persistence for editable pallet projects."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import BeamSection, DirectionInput, LayerInput, ManualBeamInput
from .materials import MATERIALS, DEFAULT_MATERIAL_ID
from .project_state import ProjectState


FORMAT_VERSION = 3


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
        "hidden_beam_indices": list(data.hidden_beam_indices),
    }


def _direction_from_dict(raw: object, name: str) -> DirectionInput:
    if not isinstance(raw, dict):
        raise ProjectPersistenceError(f"Раздел «{name}» должен быть объектом.")
    try:
        positions = raw.get("support_positions")
        if positions is not None and not isinstance(positions, list):
            raise TypeError
        hidden = raw.get("hidden_beam_indices", [])
        if not isinstance(hidden, list):
            raise TypeError
        distances = raw["support_distances"]
        if not isinstance(distances, list):
            raise TypeError
        return DirectionInput(
            float(raw["beam_height"]), float(raw["beam_width"]), tuple(float(value) for value in distances),
            float(raw["first_edge_to_support"]), float(raw["last_support_to_edge"]),
            float(raw["margin_start"]), float(raw["margin_end"]), bool(raw["round_pallet_size"]),
            int(raw["rounding_step"]), None if positions is None else tuple(float(value) for value in positions),
            tuple(int(value) for value in hidden),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectPersistenceError(f"Раздел «{name}» содержит некорректные параметры.") from exc


def _layer_to_dict(layer: LayerInput) -> dict[str, Any]:
    return {"id": layer.layer_id, "axis": layer.axis, "direction": _direction_to_dict(layer.direction)}


def _layer_from_dict(raw: object) -> LayerInput:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or raw.get("axis") not in ("length", "width"):
        raise ProjectPersistenceError("Слой содержит некорректные параметры.")
    layer_id = raw["id"].strip()
    if not layer_id:
        raise ProjectPersistenceError("Идентификатор слоя не может быть пустым.")
    return LayerInput(layer_id, raw["axis"], _direction_from_dict(raw.get("direction"), f"слой «{layer_id}»"))


def _legacy_layers(length: DirectionInput, width: DirectionInput, upper_layer: str) -> list[LayerInput]:
    ordered = (("length", length), ("width", width)) if upper_layer == "width" else (("width", width), ("length", length))
    return [LayerInput(axis, axis, direction) for axis, direction in ordered]


def project_to_dict(state: ProjectState) -> dict[str, Any]:
    """Convert stable project and view settings to a portable JSON object."""
    if state.length_input is None or state.width_input is None:
        raise ProjectPersistenceError("Нельзя сохранить проект без рассчитанных параметров.")
    layers = state.layers or _legacy_layers(state.length_input, state.width_input, state.upper_layer)
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
            "layers": [_layer_to_dict(layer) for layer in layers],
            "layer_sections": [
                {"layer_id": layer_id, "index": index, "height": section.height, "width": section.width}
                for (layer_id, index), section in sorted(state.layer_sections.items())
            ],
            "multi_layer_mode": state.multi_layer_mode,
            "manual_beams": [
                {"id": beam.beam_id, "first": list(beam.first_support), "second": list(beam.second_support),
                 "distance": beam.distance, "height": beam.section.height, "width": beam.section.width,
                 "reference": list(beam.reference_support) if beam.reference_support else None,
                 "reference_face": beam.reference_face,
                 "first_face": beam.first_face, "second_face": beam.second_face}
                for beam in state.manual_beams
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
    if not isinstance(raw, dict) or raw.get("format_version") not in (1, 2, FORMAT_VERSION):
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
    length_input = _direction_from_dict(pallet.get("length"), "длина")
    width_input = _direction_from_dict(pallet.get("width"), "ширина")
    raw_layers = pallet.get("layers")
    if raw_layers is None:
        layers = _legacy_layers(length_input, width_input, upper_layer)
    elif not isinstance(raw_layers, list):
        raise ProjectPersistenceError("Слои поддона должны быть списком.")
    else:
        layers = [_layer_from_dict(item) for item in raw_layers]
        if not layers or len({layer.layer_id for layer in layers}) != len(layers):
            raise ProjectPersistenceError("Слои поддона должны иметь уникальные идентификаторы.")
    layer_sections: dict[tuple[str, int], BeamSection] = {}
    raw_layer_sections = pallet.get("layer_sections", [])
    if not isinstance(raw_layer_sections, list):
        raise ProjectPersistenceError("Сечения слоёв должны быть списком.")
    layer_ids = {layer.layer_id for layer in layers}
    for item in raw_layer_sections:
        if not isinstance(item, dict):
            raise ProjectPersistenceError("Сечение слоя содержит некорректные параметры.")
        try:
            layer_id, index = item["layer_id"], item["index"]
            height, width = float(item["height"]), float(item["width"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectPersistenceError("Сечение слоя содержит некорректные параметры.") from exc
        if layer_id not in layer_ids or not isinstance(index, int) or index < 0 or not all(
            math.isfinite(value) and value > 0 for value in (height, width)
        ):
            raise ProjectPersistenceError("Сечение слоя содержит недопустимые значения.")
        layer_sections[(layer_id, index)] = BeamSection(height, width)
    if not layer_sections:
        layer_sections = {(axis, index): section for (axis, index), section in beam_sections.items()}
    manual_beams: list[ManualBeamInput] = []
    raw_manual = pallet.get("manual_beams", [])
    if not isinstance(raw_manual, list):
        raise ProjectPersistenceError("Пользовательские брусья должны быть списком.")
    for item in raw_manual:
        try:
            beam_id = str(item["id"])
            first, second = item["first"], item["second"]
            reference = item.get("reference")
            first_key = (str(first[0]), int(first[1]))
            second_key = (str(second[0]), int(second[1]))
            reference_key = (str(reference[0]), int(reference[1])) if reference is not None else None
            section = BeamSection(float(item["height"]), float(item["width"]))
            distance = float(item["distance"])
            first_face = item.get("first_face", "top")
            second_face = item.get("second_face", "top")
            reference_face = item.get("reference_face")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ProjectPersistenceError("Пользовательский брус содержит некорректные параметры.") from exc
        if (not beam_id or first_key[0] not in layer_ids or second_key[0] not in layer_ids
                or (reference_key is not None and reference_key[0] not in layer_ids)
                or first_face not in ("top", "bottom") or second_face not in ("top", "bottom")
                or reference_face not in (None, "top", "bottom", "x_min", "x_max", "y_min", "y_max")
                or not math.isfinite(distance) or not all(value > 0 and math.isfinite(value) for value in (section.height, section.width))):
            raise ProjectPersistenceError("Пользовательский брус содержит недопустимые параметры.")
        manual_beams.append(ManualBeamInput(
            beam_id, first_key, second_key, distance, section,
            reference_support=reference_key, reference_face=reference_face,
            first_face=first_face, second_face=second_face,
        ))
    return ProjectState(
        length_input=length_input,
        width_input=width_input,
        upper_layer=upper_layer,
        rounding_step=rounding_step,
        material_id=material_id,
        beam_sections=beam_sections,
        layers=layers,
        layer_sections=layer_sections,
        manual_beams=manual_beams,
        multi_layer_mode=bool(pallet.get("multi_layer_mode", False)),
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
