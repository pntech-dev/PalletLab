from __future__ import annotations

import json

import pytest

from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.models import BeamSection, DirectionInput, LayerInput
from palletlab.core.persistence import ProjectPersistenceError, load_project, project_from_dict, save_project
from palletlab.core.project_state import ProjectState


def _state() -> ProjectState:
    return ProjectState(
        length_input=DirectionInput(70, 50, (100, 500), 120, 240, 100, 150, True, 50),
        width_input=DirectionInput(60, 40, (200,), 90, 190, 80, 70, False, 5),
        upper_layer="length",
        rounding_step=50,
        material_id="spruce",
        camera="top",
        show_length_dimensions=False,
        show_width_dimensions=True,
    )


def test_project_json_round_trip_preserves_configuration_not_transient_state(tmp_path):
    state = _state()
    state.active_tool = "deletion"
    state.selected_for_deletion["length"].add(2)
    state.beam_sections[("length", 2)] = BeamSection(100, 75)
    path = tmp_path / "project.json"

    save_project(path, state)
    restored = load_project(path)

    assert restored.length_input == state.length_input
    assert restored.width_input == state.width_input
    assert restored.upper_layer == "length"
    assert restored.material_id == "spruce"
    assert restored.camera == "top"
    assert restored.show_length_dimensions is False
    assert restored.active_tool == "none"
    assert restored.selected_for_deletion == {"length": set(), "width": set()}
    assert restored.beam_sections == {("length", 2): BeamSection(100, 75)}
    assert restored.layers == [
        LayerInput("width", "width", state.width_input), LayerInput("length", "length", state.length_input)
    ]
    assert restored.layer_sections == {("length", 2): BeamSection(100, 75)}
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == 3


def test_project_json_rejects_unknown_or_invalid_format():
    with pytest.raises(ProjectPersistenceError):
        project_from_dict({"format_version": 99})


def test_version_two_project_is_migrated_to_an_ordered_layer_stack(tmp_path):
    state = _state()
    path = tmp_path / "project.json"
    save_project(path, state)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["format_version"] = 2
    raw["pallet"].pop("layers")
    raw["pallet"].pop("layer_sections")
    raw["pallet"].pop("multi_layer_mode")

    restored = project_from_dict(raw)

    assert [layer.layer_id for layer in restored.layers] == ["width", "length"]
    assert not restored.multi_layer_mode


def test_multilayer_stack_and_its_sections_round_trip(tmp_path):
    state = _state()
    state.layers = [
        LayerInput("bottom", "length", state.length_input),
        LayerInput("middle", "width", state.width_input),
        LayerInput("top", "length", state.length_input),
    ]
    state.layer_sections[("middle", 1)] = BeamSection(100, 75)
    state.multi_layer_mode = True
    path = tmp_path / "project.json"

    save_project(path, state)
    restored = load_project(path)

    assert [layer.layer_id for layer in restored.layers] == ["bottom", "middle", "top"]
    assert restored.layer_sections == {("middle", 1): BeamSection(100, 75)}
    assert restored.multi_layer_mode


class _Signal:
    def connect(self, _callback) -> None:
        pass


class _Timer:
    timeout = _Signal()
    def setSingleShot(self, _value): pass
    def setInterval(self, _value): pass
    def stop(self): pass
    def start(self): pass


class _View:
    def show_pallet(self, *_args, **_kwargs): pass


def test_controller_opens_saved_project_and_rebuilds_it(tmp_path):
    path = tmp_path / "project.json"
    save_project(path, _state())
    state = ProjectState()
    loaded = []
    controller = PalletController(
        state, _View(), on_calculated=lambda _result: None,
        on_error=lambda _error, _show: pytest.fail("opening should not fail"),
        on_stale_changed=lambda _value: None, on_project_loaded=loaded.append, timer=_Timer(),
    )

    result = controller.open_project(str(path))

    assert result is state.result
    assert loaded == [state]
    assert state.camera == "top"
