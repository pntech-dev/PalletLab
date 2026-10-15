from palletlab.ui.tool_state import ToolStateMachine


def test_enabling_a_tool_replaces_the_active_tool() -> None:
    state = ToolStateMachine()

    assert state.transition("insertion", True) == ("none", "insertion")
    assert state.transition("distance_editing", True) == ("insertion", "distance_editing")
    assert state.active == "distance_editing"


def test_turning_off_an_inactive_tool_keeps_current_capture() -> None:
    state = ToolStateMachine("deletion")

    assert state.transition("section_editing", False) == ("deletion", "deletion")
    assert state.active == "deletion"


def test_turning_off_active_tool_releases_it() -> None:
    state = ToolStateMachine("section_editing")

    assert state.transition("section_editing", False) == ("section_editing", "none")
    assert state.active == "none"
