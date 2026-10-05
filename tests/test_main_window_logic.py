"""Controller-like behaviour of the current main window.

These tests deliberately call the window methods with small test doubles.
They lock down the workflow before the UI is moved behind an MVC controller,
without creating a Qt window or a VTK render surface.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from palletlab.core.calculator import build_pallet, calculate_direction, insertion_slots
from palletlab.core.models import DirectionInput
from palletlab.ui.main_window import MainWindow


LENGTH_INPUT = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100)
WIDTH_INPUT = DirectionInput(70, 50, (560, 720), 277, 179, 100, 100)


class _Timer:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


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


def test_auto_recalculation_is_debounced_and_suppresses_modal_errors():
    timer = _Timer()
    stale_values: list[bool] = []
    calculate_calls: list[dict[str, bool]] = []
    window = SimpleNamespace(
        _rebuild_timer=timer,
        _set_stale=stale_values.append,
        calculate=lambda **kwargs: calculate_calls.append(kwargs),
    )

    MainWindow._schedule_recalculation(window)
    MainWindow._schedule_recalculation(window)
    MainWindow._calculate_automatically(window)

    assert stale_values == [True, True]
    assert timer.starts == 2
    assert calculate_calls == [{"show_error": False}]


def test_calculate_rebuilds_model_from_current_panels():
    timer = _Timer()
    scene_results = []
    rendered = []
    stale_values = []
    window = SimpleNamespace(
        _rebuild_timer=timer,
        rounding_buttons=SimpleNamespace(checkedId=lambda: 50),
        length_panel=_Panel(LENGTH_INPUT),
        width_panel=_Panel(WIDTH_INPUT),
        upper_layer=lambda: "width",
        _update_scene_info=scene_results.append,
        view=SimpleNamespace(show_pallet=lambda result, **kwargs: rendered.append((result, kwargs))),
        show_length_gaps=SimpleNamespace(isChecked=lambda: True),
        show_width_gaps=SimpleNamespace(isChecked=lambda: True),
        add_beam_button=_Toggle(),
        delete_beam_button=_Toggle(),
        edit_distance_button=_Toggle(),
        _set_stale=stale_values.append,
    )

    MainWindow.calculate(window, show_error=False)

    assert timer.stops == 1
    assert window._last_result is scene_results[0]
    assert rendered[0][0] is window._last_result
    assert rendered[0][1] == {"show_length_gaps": True, "show_width_gaps": True}
    assert window._last_inputs["length"].rounding_step == 50
    assert stale_values == [False]


def test_confirm_insertion_updates_the_input_panel_then_recalculates():
    result = _pallet_result()
    slot = next(candidate for candidate in insertion_slots(result, "length") if candidate.after_beam_index == 1)
    length_panel = _Panel()
    recalculated: list[bool] = []
    window = SimpleNamespace(
        _pending_insertion=slot,
        _last_result=result,
        _last_inputs={"length": LENGTH_INPUT, "width": WIDTH_INPUT},
        insertion_gap=SimpleNamespace(value=lambda: 100.0),
        length_panel=length_panel,
        width_panel=_Panel(),
        insertion_editor=_Visibility(),
        calculate=lambda: recalculated.append(True),
    )

    MainWindow._confirm_insertion(window)

    assert length_panel.applied_data is not None
    assert calculate_direction(length_panel.applied_data).beam_count == result.length_result.beam_count + 1
    assert window._pending_insertion is None
    assert window.insertion_editor.visible is False
    assert recalculated == [True]


def test_confirm_deletion_updates_selected_axes_then_recalculates():
    result = _pallet_result()
    length_panel, width_panel = _Panel(), _Panel()
    recalculated: list[bool] = []
    status_bar = _StatusBar()
    window = SimpleNamespace(
        _last_result=result,
        _last_inputs={"length": LENGTH_INPUT, "width": WIDTH_INPUT},
        _selected_for_deletion={"length": {1, 3}, "width": set()},
        length_panel=length_panel,
        width_panel=width_panel,
        delete_beam_button=_Toggle(True),
        calculate=lambda: recalculated.append(True),
        statusBar=lambda: status_bar,
    )

    MainWindow._confirm_deletion(window)

    assert length_panel.applied_data is not None
    assert calculate_direction(length_panel.applied_data).beam_count == result.length_result.beam_count - 2
    assert window.delete_beam_button.checked is False
    assert recalculated == [True]
    assert status_bar.messages[-1] == "Удалено брусьев: 2."


def test_confirm_distance_edit_updates_input_panel_then_recalculates():
    result = _pallet_result()
    length_panel = _Panel()
    recalculated: list[bool] = []
    window = SimpleNamespace(
        _pending_distance=("length", 2),
        _last_result=result,
        _last_inputs={"length": LENGTH_INPUT, "width": WIDTH_INPUT},
        distance_value=SimpleNamespace(value=lambda: 1500.0),
        length_panel=length_panel,
        width_panel=_Panel(),
        distance_editor=_Visibility(),
        calculate=lambda: recalculated.append(True),
        statusBar=lambda: _StatusBar(),
    )

    MainWindow._confirm_distance_edit(window)

    assert length_panel.applied_data is not None
    assert calculate_direction(length_panel.applied_data).beam_centers[2] == 1525.0
    assert window._pending_distance is None
    assert window.distance_editor.visible is False
    assert recalculated == [True]
