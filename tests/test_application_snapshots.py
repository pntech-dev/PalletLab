"""Contract tests for the UI-independent web snapshot boundary."""

from __future__ import annotations

import json

from palletlab.application.snapshots import SNAPSHOT_VERSION, pallet_snapshot, project_snapshot
from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.materials import pallet_mass_kg
from palletlab.core.models import DirectionInput
from palletlab.core.project_state import ProjectState


def _result():
    length = calculate_direction(DirectionInput(100, 80, (700,), 100, 100, 50, 50))
    width = calculate_direction(DirectionInput(80, 60, (500,), 80, 80, 40, 40))
    return build_pallet(length, width, "width")


def test_pallet_snapshot_is_json_safe_and_keeps_viewport_identity() -> None:
    result = _result()

    snapshot = pallet_snapshot(result, material_id="spruce")

    assert json.loads(json.dumps(snapshot)) == snapshot
    assert snapshot["size"] == {
        "length": result.pallet_length,
        "width": result.pallet_width,
        "height": result.pallet_height,
    }
    assert snapshot["beams"][0]["index"] == 0
    assert snapshot["beams"][0]["layerId"] == result.beams_3d[0].layer_id
    assert snapshot["massKg"] == pallet_mass_kg(result.beams_3d, "spruce")
    assert snapshot["insertionMarkers"]


def test_project_snapshot_combines_persisted_and_transient_state() -> None:
    result = _result()
    state = ProjectState(
        length_input=DirectionInput(100, 80, (700,), 100, 100, 50, 50),
        width_input=DirectionInput(80, 60, (500,), 80, 80, 40, 40),
        material_id="spruce",
        result=result,
        active_tool="delete",
        selected_for_deletion={"length": {2, 1}, "width": set()},
    )

    snapshot = project_snapshot(state)

    assert json.loads(json.dumps(snapshot)) == snapshot
    assert snapshot["version"] == SNAPSHOT_VERSION
    assert snapshot["project"]["format_version"] >= 1
    assert snapshot["editor"]["activeTool"] == "delete"
    assert snapshot["editor"]["selectedForDeletion"] == {"length": [1, 2], "width": []}
    assert snapshot["pallet"]["beams"]
    assert snapshot["pallet"]["massKg"] == pallet_mass_kg(result.beams_3d, state.material_id)
