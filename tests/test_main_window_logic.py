"""Thin-view behaviour of the current main window.

These tests deliberately call the window methods with small test doubles.
They verify delegation to the MVC controller without creating a Qt window or a
VTK render surface.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from palletlab.core.calculator import build_pallet, calculate_direction, insertion_slots
from palletlab.core.models import DirectionInput, LayerInput
from palletlab.core.project_state import ProjectHistory, ProjectState
from palletlab.ui.main_window import MainWindow


LENGTH_INPUT = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100)
WIDTH_INPUT = DirectionInput(70, 50, (560, 720), 277, 179, 100, 100)


class _Panel:
    def __init__(self, data: DirectionInput | None = None) -> None:
        self.data = data
        self.applied_data: DirectionInput | None = None

    def values(self, round_pallet_size: bool, rounding_step: int) -> DirectionInput:
        assert self.data is not None
        return replace(self.data, round_pallet_size=round_pallet_size, rounding_step=rounding_step)

    def apply_position_data(self, data: DirectionInput) -> None:
        self.applied_data = data


class _Visibility:
    def __init__(self) -> None:
        self.visible: bool | None = None

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class _Toggle:
    def __init__(self, checked: bool = False) -> None:
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked

    def setChecked(self, checked: bool) -> None:
        self.checked = checked


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


def _pallet_result():
    return build_pallet(calculate_direction(LENGTH_INPUT), calculate_direction(WIDTH_INPUT))


def test_auto_recalculation_is_delegated_to_the_controller():
    scheduled = []
    window = SimpleNamespace(
        controller=SimpleNamespace(schedule_recalculation=lambda: scheduled.append(True)),
    )

    MainWindow._schedule_recalculation(window)
    MainWindow._schedule_recalculation(window)

    assert scheduled == [True, True]


def test_successful_deferred_calculation_closes_its_history_transaction():
    """A later action must not be combined with a completed field edit."""
    state = ProjectState()
    history = ProjectHistory()
    window = SimpleNamespace(
        state=state,
        _history=history,
        _history_restoring=False,
        _pending_history_snapshot=None,
        _update_scene_info=lambda _result: None,
    )

    MainWindow._begin_history_transaction(window)
    state.material_id = "history-test-material"
    MainWindow._calculation_succeeded(window, _pallet_result())

    assert window._pending_history_snapshot is None
    assert len(history.undo_stack) == 1
    assert history.undo(state)
    assert state.material_id != "history-test-material"


def test_dimension_visibility_is_written_to_project_state():
    refreshed = []
    state = ProjectState()
    history = ProjectHistory()
    window = SimpleNamespace(
        state=state,
        _history=history,
        _history_restoring=False,
        _pending_history_snapshot=None,
        show_length_gaps=_Toggle(False),
        show_width_gaps=_Toggle(True),
        _refresh_dimension_annotations=lambda: refreshed.append(True),
    )

    MainWindow._dimension_visibility_changed(window)

    assert state.show_length_dimensions is False
    assert state.show_width_dimensions is True
    assert refreshed == [True]
    assert history.undo(state)
    assert state.show_length_dimensions is True


def test_camera_change_is_a_complete_undoable_project_edit():
    state = ProjectState()
    history = ProjectHistory()
    camera_calls = []
    window = SimpleNamespace(
        state=state,
        _history=history,
        _history_restoring=False,
        _pending_history_snapshot=None,
        camera_combo=SimpleNamespace(itemData=lambda _index: "top"),
        view=SimpleNamespace(
            camera_isometric=lambda: camera_calls.append("isometric"),
            camera_top=lambda: camera_calls.append("top"),
            camera_front=lambda: camera_calls.append("front"),
            camera_side=lambda: camera_calls.append("side"),
        ),
    )

    MainWindow._set_camera(window, 1)

    assert state.camera == "top"
    assert camera_calls == ["top"]
    assert history.undo(state)
    assert state.camera == "isometric"


def test_layer_and_rounding_changes_snapshot_state_before_controller_mutates_it():
    state = ProjectState()
    history = ProjectHistory()
    scheduled = []
    window = SimpleNamespace(
        state=state,
        _history=history,
        _history_restoring=False,
        _pending_history_snapshot=None,
        controller=SimpleNamespace(
            set_upper_layer=lambda layer: setattr(state, "upper_layer", layer),
            set_rounding_step=lambda step: setattr(state, "rounding_step", step),
        ),
        upper_layer=lambda: "length",
        rounding_buttons=SimpleNamespace(checkedId=lambda: 5),
        _schedule_recalculation=lambda: scheduled.append(True),
    )

    MainWindow._layer_changed(window)
    MainWindow._commit_history_transaction(window)
    MainWindow._rounding_changed(window)
    MainWindow._commit_history_transaction(window)

    assert history.undo(state)
    assert state.rounding_step == 50
    assert history.undo(state)
    assert state.upper_layer == "width"
    assert scheduled == [True, True]


def test_layer_edit_synchronizes_the_parallel_layer_envelope():
    changed = replace(LENGTH_INPUT, margin_end=LENGTH_INPUT.margin_end + 250)
    peer_panel = _Panel(LENGTH_INPUT)
    window = SimpleNamespace(
        _layer_envelope_source="top",
        _layer_panels={"length": peer_panel},
    )

    layers = MainWindow._synchronize_layer_envelopes(window, [
        LayerInput("length", "length", LENGTH_INPUT),
        LayerInput("width", "width", WIDTH_INPUT),
        LayerInput("top", "length", changed),
    ])

    length_layer = next(layer for layer in layers if layer.layer_id == "length")
    assert calculate_direction(length_layer.direction).raw_pallet_size == pytest.approx(
        calculate_direction(changed).raw_pallet_size
    )
    assert peer_panel.applied_data == length_layer.direction


def test_calculate_rebuilds_model_from_current_panels():
    result = _pallet_result()
    calculation_calls = []
    window = SimpleNamespace(
        state=ProjectState(),
        rounding_buttons=SimpleNamespace(checkedId=lambda: 50),
        length_panel=_Panel(LENGTH_INPUT),
        width_panel=_Panel(WIDTH_INPUT),
        upper_layer=lambda: "width",
        _read_calculation_inputs=lambda: (replace(LENGTH_INPUT, round_pallet_size=True, rounding_step=50),
                                          replace(WIDTH_INPUT, round_pallet_size=True, rounding_step=50), "width"),
        controller=SimpleNamespace(calculate=lambda *args, **kwargs: calculation_calls.append((args, kwargs)) or result),
        add_beam_button=_Toggle(),
        delete_beam_button=_Toggle(),
        edit_distance_button=_Toggle(),
        change_section_button=_Toggle(),
    )

    MainWindow.calculate(window, show_error=False)

    args, kwargs = calculation_calls[0]
    assert args[0].rounding_step == 50
    assert args[1].rounding_step == 50
    assert args[2] == "width"
    assert kwargs == {"show_error": False}


def test_save_project_delegates_current_state_to_controller():
    result = _pallet_result()
    saved_paths: list[str] = []
    status_bar = _StatusBar()
    window = SimpleNamespace(
        _project_path="C:/projects/pallet.palletlab.json",
        calculate=lambda **_kwargs: result,
        controller=SimpleNamespace(save_project=lambda path: saved_paths.append(path) or True),
        statusBar=lambda: status_bar,
    )

    MainWindow.save_project(window)

    assert saved_paths == ["C:/projects/pallet.palletlab.json"]
    assert status_bar.messages[-1].endswith("pallet.palletlab.json")


def test_confirm_insertion_updates_the_input_panel_then_recalculates():
    result = _pallet_result()
    slot = next(candidate for candidate in insertion_slots(result, "length") if candidate.after_beam_index == 1)
    length_panel = _Panel()
    recalculated: list[bool] = []
    window = SimpleNamespace(
        controller=SimpleNamespace(
            confirm_insertion=lambda _gap: ("length", LENGTH_INPUT),
            recalculate_from_state=lambda: recalculated.append(True),
        ),
        insertion_gap=SimpleNamespace(value=lambda: 100.0),
        length_panel=length_panel,
        width_panel=_Panel(),
        insertion_editor=_Visibility(),
    )

    MainWindow._confirm_insertion(window)

    assert length_panel.applied_data is not None
    assert length_panel.applied_data is LENGTH_INPUT
    assert window.insertion_editor.visible is False
    assert recalculated == [True]


def test_confirm_deletion_updates_selected_axes_then_recalculates():
    result = _pallet_result()
    length_panel, width_panel = _Panel(), _Panel()
    recalculated: list[bool] = []
    status_bar = _StatusBar()
    window = SimpleNamespace(
        controller=SimpleNamespace(
            confirm_deletion=lambda: {"length": LENGTH_INPUT},
            recalculate_from_state=lambda: recalculated.append(True),
        ),
        _selected_for_deletion={"length": {1, 3}, "width": set()},
        length_panel=length_panel,
        width_panel=width_panel,
        delete_beam_button=_Toggle(True),
        statusBar=lambda: status_bar,
    )

    MainWindow._confirm_deletion(window)

    assert length_panel.applied_data is not None
    assert length_panel.applied_data is LENGTH_INPUT
    assert window.delete_beam_button.checked is True
    assert recalculated == [True]
    assert status_bar.messages[-1] == "Удалено брусьев: 2."


def test_confirm_distance_edit_updates_input_panel_then_recalculates():
    result = _pallet_result()
    length_panel = _Panel()
    recalculated: list[bool] = []
    window = SimpleNamespace(
        controller=SimpleNamespace(
            confirm_distance_edit=lambda _value: ("length", LENGTH_INPUT),
            recalculate_from_state=lambda: recalculated.append(True),
        ),
        distance_value=SimpleNamespace(value=lambda: 1500.0),
        length_panel=length_panel,
        width_panel=_Panel(),
        distance_editor=_Visibility(),
        statusBar=lambda: _StatusBar(),
    )

    MainWindow._confirm_distance_edit(window)

    assert length_panel.applied_data is not None
    assert length_panel.applied_data is LENGTH_INPUT
    assert window.distance_editor.visible is False
    assert recalculated == [True]
