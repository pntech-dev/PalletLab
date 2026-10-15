from __future__ import annotations

import json
from pathlib import Path

import pytest

import palletlab.controllers.pallet_controller as pallet_controller_module
from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.models import BeamSection, DirectionInput, LayerInput
from palletlab.core.persistence import ProjectPersistenceError, load_project, project_from_dict, project_to_dict, save_project
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


def test_failed_project_rebuild_restores_the_previously_applied_ui_state(monkeypatch):
    state = _state()
    previous_length = state.length_input
    previous_camera = state.camera
    invalid = _state()
    invalid.length_input = DirectionInput(70, 50, (100,), -1, 240, 100, 150, True, 50)
    applied: list[tuple[DirectionInput | None, str]] = []
    controller = PalletController(
        state,
        _View(),
        on_calculated=lambda _result: None,
        on_error=lambda _error, _show: None,
        on_stale_changed=lambda _value: None,
        on_project_loaded=lambda loaded: applied.append((loaded.length_input, loaded.camera)),
        timer=_Timer(),
    )
    monkeypatch.setattr(pallet_controller_module, "load_project", lambda _path: invalid)

    assert controller.open_project("invalid-but-readable.json") is None

    assert state.length_input == previous_length
    assert state.camera == previous_camera
    assert applied == [(invalid.length_input, invalid.camera), (previous_length, previous_camera)]


def test_save_replaces_a_project_atomically_after_validation(tmp_path, monkeypatch):
    path = tmp_path / "project.json"
    path.write_text('{"previous": true}', encoding="utf-8")

    def successful_replace(source, destination):
        Path(destination).write_bytes(Path(source).read_bytes())
        Path(source).unlink()

    monkeypatch.setattr("palletlab.core.persistence.os.replace", successful_replace)

    save_project(path, _state())

    assert project_from_dict(json.loads(path.read_text(encoding="utf-8"))).material_id == "spruce"
    assert not list(tmp_path.glob(".project.json.*.tmp"))


def test_save_keeps_the_original_file_when_atomic_replace_is_locked(tmp_path, monkeypatch):
    path = tmp_path / "project.json"
    previous = '{"previous": true}'
    path.write_text(previous, encoding="utf-8")

    def locked_replace(_source, _destination):
        raise PermissionError("locked")

    monkeypatch.setattr("palletlab.core.persistence.os.replace", locked_replace)

    with pytest.raises(ProjectPersistenceError, match="Временная копия сохранена"):
        save_project(path, _state())

    assert path.read_text(encoding="utf-8") == previous
    recovery_files = list(tmp_path.glob(".project.json.*.tmp"))
    assert len(recovery_files) == 1
    recovery_files[0].unlink()


@pytest.mark.parametrize("field, value", [
    ("show_length_dimensions", "false"),
    ("show_width_dimensions", 1),
    ("multi_layer_mode", "true"),
    ("round_pallet_size", "false"),
])
def test_project_rejects_non_boolean_flags(field, value):
    raw = project_to_dict(_state())
    container = raw["view"] if field.startswith("show_") else raw["pallet"]
    if field == "round_pallet_size":
        raw["pallet"]["length"][field] = value
    else:
        container[field] = value

    with pytest.raises(ProjectPersistenceError):
        project_from_dict(raw)


def test_project_rejects_duplicate_manual_beam_ids():
    raw = project_to_dict(_state())
    beam = {
        "id": "manual-1", "first": ["length", 0], "second": ["width", 0],
        "distance": 100, "height": 50, "width": 50, "reference": None,
        "reference_face": None, "first_face": "top", "second_face": "top",
    }
    raw["pallet"]["manual_beams"] = [beam, beam.copy()]

    with pytest.raises(ProjectPersistenceError, match="не должны повторяться"):
        project_from_dict(raw)
