from __future__ import annotations

from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.calculator import insertion_slots
from palletlab.core.models import DirectionInput
from palletlab.core.project_state import ProjectState


LENGTH_INPUT = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100)
WIDTH_INPUT = DirectionInput(70, 50, (560, 720), 277, 179, 100, 100)


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _Timer:
    def __init__(self) -> None:
        self.timeout = _Signal()
        self.starts = 0
        self.stops = 0
        self.single_shot = False
        self.interval = None

    def setSingleShot(self, value: bool) -> None:
        self.single_shot = value

    def setInterval(self, value: int) -> None:
        self.interval = value

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class _View:
    def __init__(self) -> None:
        self.rendered = []
        self.annotations = []
        self.previews = []
        self.insertion_cleared = 0
        self.preview_cleared = 0

    def show_pallet(self, result, **kwargs) -> None:
        self.rendered.append((result, kwargs))

    def update_dimension_annotations(self, result, **kwargs) -> None:
        self.annotations.append((result, kwargs))

    def show_insertion_preview(self, result, slot, clear_gap) -> None:
        self.previews.append((result, slot, clear_gap))

    def clear_insertion_selection(self) -> None:
        self.insertion_cleared += 1

    def clear_insertion_preview(self) -> None:
        self.preview_cleared += 1


def _controller():
    state = ProjectState()
    view = _View()
    timer = _Timer()
    calculated = []
    errors = []
    stale = []
    controller = PalletController(
        state,
        view,
        on_calculated=calculated.append,
        on_error=lambda error, show_error: errors.append((str(error), show_error)),
        on_stale_changed=stale.append,
        timer=timer,
    )
    return controller, state, view, timer, calculated, errors, stale


def test_controller_calculates_updates_state_and_renders_the_view():
    controller, state, view, timer, calculated, errors, stale = _controller()

    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")

    assert result is state.result
    assert state.length_input is LENGTH_INPUT
    assert state.width_input is WIDTH_INPUT
    assert view.rendered == [(result, {"show_length_gaps": True, "show_width_gaps": True})]
    assert calculated == [result]
    assert errors == []
    assert stale == [False]
    assert timer.stops == 1


def test_controller_debounces_automatic_recalculation():
    controller, _state, _view, timer, _calculated, _errors, stale = _controller()
    rebuilds = []

    controller.schedule_recalculation(lambda: rebuilds.append(True))
    controller.schedule_recalculation(lambda: rebuilds.append(True))
    timer.timeout.callback()

    assert timer.starts == 2
    assert stale == [True, True]
    assert rebuilds == [True]


def test_controller_handles_insert_delete_and_distance_edits_through_project_state():
    controller, state, view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    slot = next(slot for slot in insertion_slots(result, "length") if slot.after_beam_index == 1)

    assert controller.begin_insertion(slot)
    controller.preview_insertion(100)
    axis, inserted = controller.confirm_insertion(100)
    assert axis == "length"
    assert state.length_input is inserted
    assert view.previews[-1] == (result, slot, 100)

    assert controller.recalculate_from_state() is not None
    controller.set_deletion_selection("length", 1, True)
    deleted = controller.confirm_deletion()
    assert deleted is not None
    assert "length" in deleted

    assert controller.recalculate_from_state() is not None
    controller.begin_distance_edit("length", 2)
    edited = controller.confirm_distance_edit(1500)
    assert edited is not None
    assert state.pending_distance is None
    assert errors == []
