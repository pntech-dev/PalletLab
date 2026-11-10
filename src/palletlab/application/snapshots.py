"""JSON-safe snapshots consumed by the future web frontend.

The calculation model remains the source of truth.  These functions deliberately
translate it at the application boundary instead of exposing Python dataclasses
or PyVista-specific objects to a UI.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from palletlab.controllers.viewport_geometry import InsertionMarker, editable_dimensions, insertion_markers
from palletlab.core.calculator import calculate_direction, insertion_slots, insertion_slots_for_direction
from palletlab.core.models import Beam3D, InsertionSlot, LayerInput, ManualBeamInput, PalletResult
from palletlab.core.persistence import project_to_dict
from palletlab.core.project_state import ProjectState, beam_layer_ids

SNAPSHOT_VERSION = 1


def project_snapshot(state: ProjectState) -> dict[str, Any]:
    """Return the complete JSON-safe state required to render a pallet project.

    Stable project data intentionally uses the existing persistence payload, so
    loading an old ``.palletlab.json`` and opening the same state in the web UI
    share one representation.  Transient editor state is kept separately.
    """
    result = state.result
    return {
        "version": SNAPSHOT_VERSION,
        "project": project_to_dict(state),
        "editor": {
            "activeTool": state.active_tool,
            "pendingDistance": list(state.pending_distance) if state.pending_distance else None,
            "selectedForDeletion": _selection_payload(state.selected_for_deletion),
            "selectedForSection": _selection_payload(state.selected_for_section),
        },
        "pallet": pallet_snapshot(result, state.manual_beams, state.layers if state.multi_layer_mode else ()) if result else None,
    }


def pallet_snapshot(
    result: PalletResult,
    manual_beams: Sequence[ManualBeamInput] = (),
    layers: Sequence[LayerInput] = (),
) -> dict[str, Any]:
    """Return viewport data without coupling the caller to PyVista or Qt."""
    slots = _insertion_slots(result, layers)
    physical_layers = beam_layer_ids(layers, manual_beams)
    def viewport_dimension_point(point: tuple[float, float, float]) -> list[float]:
        # Legacy dimension geometry uses a mirrored Y axis; web beams do not.
        return [point[0], result.pallet_width - point[1], point[2]]

    return {
        "size": {
            "length": result.pallet_length,
            "width": result.pallet_width,
            "height": result.pallet_height,
        },
        "upperLayer": result.upper_layer,
        "layers": [
            {
                "id": layer.layer_id,
                "axis": layer.axis,
                "baseZ": layer.base_z,
                "topZ": layer.top_z,
                "beamStartIndex": layer.beam_start_index,
                "beamCount": layer.beam_count,
            }
            for layer in result.layers
        ],
        "beams": [
            {**_beam_payload(index, beam), "physicalLayerId": physical_layers.get(beam.layer_id, beam.layer_id)}
            for index, beam in enumerate(result.beams_3d)
        ],
        "dimensions": [
            {
                "layerId": dimension.layer_id,
                "axis": dimension.axis,
                "index": dimension.index,
                "value": dimension.value,
                "editValue": dimension.edit_value,
                "editable": dimension.editable,
                "start": viewport_dimension_point(dimension.start),
                "end": viewport_dimension_point(dimension.end),
                "startExtension": viewport_dimension_point(dimension.start_extension) if dimension.start_extension else None,
                "endExtension": viewport_dimension_point(dimension.end_extension) if dimension.end_extension else None,
            }
            for dimension in editable_dimensions(result, tuple(manual_beams))
        ],
        "insertionMarkers": [_marker_payload(marker) for marker in insertion_markers(result, slots)],
    }


def _beam_payload(index: int, beam: Beam3D) -> dict[str, Any]:
    return {
        "index": index,
        "layerId": beam.layer_id,
        "layerIndex": beam.layer_index,
        "orientation": beam.orientation,
        "center": [beam.x, beam.y, beam.z],
        "size": [beam.size_x, beam.size_y, beam.size_z],
    }


def _insertion_slots(result: PalletResult, layers: Sequence[LayerInput]) -> tuple[InsertionSlot, ...]:
    """Return slots for both legacy and generic multilayer project models."""
    if layers:
        return tuple(
            slot
            for layer in layers
            for slot in insertion_slots_for_direction(
                layer.layer_id,
                layer.axis,
                calculate_direction(layer.direction),
            )
        )
    return (*insertion_slots(result, "length"), *insertion_slots(result, "width"))


def _marker_payload(marker: InsertionMarker) -> dict[str, Any]:
    return {
        "slot": {
            "axis": marker.slot.axis,
            "layerId": marker.slot.layer_id,
            "afterBeamIndex": marker.slot.after_beam_index,
            "maximumClearGap": marker.slot.maximum_clear_gap,
            "suggestedClearGap": marker.slot.suggested_clear_gap,
        },
        "center": list(marker.center),
        "size": marker.size,
        "preview": {
            "center": list(marker.preview.center),
            "size": list(marker.preview.size),
        },
    }


def _selection_payload(selection: dict[str, set[int]]) -> dict[str, list[int]]:
    """Sort selection sets so equal state always produces equal JSON."""
    return {layer_id: sorted(indices) for layer_id, indices in selection.items()}
