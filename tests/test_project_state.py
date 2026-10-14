from palletlab.core.models import DirectionInput, InsertionSlot
from palletlab.core.project_state import ProjectHistory, ProjectState


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


def test_history_restores_editable_state_without_restoring_tool_selection():
    state = ProjectState(length_input=_input(), material_id="pine")
    state.active_tool = "insertion"
    state.pending_insertion = InsertionSlot("length", 1, 120, 60)
    state.selected_for_deletion["length"].add(3)
    history = ProjectHistory()

    history.record(history.snapshot(state))
    state.length_input = DirectionInput(70, 50, (700,), 100, 100, 100, 100)
    state.material_id = "spruce"

    assert history.undo(state)
    assert state.length_input == _input()
    assert state.material_id == "pine"
    assert state.active_tool == "none"
    assert state.pending_insertion is None
    assert state.selected_for_deletion == {"length": set(), "width": set()}
    assert history.redo(state)
    assert state.length_input.support_distances == (700,)
    assert state.material_id == "spruce"


def test_history_is_limited_and_a_new_edit_clears_redo():
    state = ProjectState(length_input=_input())
    history = ProjectHistory(limit=2)
    for spacing in (600, 700, 800):
        history.record(history.snapshot(state))
        state.length_input = DirectionInput(70, 50, (spacing,), 100, 100, 100, 100)

    assert len(history.undo_stack) == 2
    assert history.undo(state)
    history.record(history.snapshot(state))
    assert history.redo_stack == []
