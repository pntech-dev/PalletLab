from palletlab.core.models import DirectionInput, InsertionSlot
from palletlab.core.project_state import ProjectState


def _input() -> DirectionInput:
    return DirectionInput(70, 50, (500,), 100, 100, 100, 100)


def test_project_state_has_the_default_project_and_view_settings():
    state = ProjectState()

    assert state.upper_layer == "width"
    assert state.rounding_step == 50
    assert state.active_tool == "none"
    assert state.camera == "isometric"
    assert state.show_length_dimensions is True
    assert state.show_width_dimensions is True
    assert state.selected_for_deletion == {"length": set(), "width": set()}


def test_project_state_stores_direction_inputs_independently():
    state = ProjectState()
    length_input = _input()
    width_input = _input()

    state.set_input("length", length_input)
    state.set_input("width", width_input)

    assert state.input_for("length") is length_input
    assert state.input_for("width") is width_input


def test_project_state_keeps_interaction_state_separate_from_project_data():
    state = ProjectState()
    slot = InsertionSlot("length", 1, 120, 60)

    state.active_tool = "insertion"
    state.pending_insertion = slot
    state.pending_distance = ("width", 2)
    state.selected_for_deletion["length"].add(3)

    assert state.active_tool == "insertion"
    assert state.pending_insertion is slot
    assert state.pending_distance == ("width", 2)
    assert state.selected_for_deletion == {"length": {3}, "width": set()}
