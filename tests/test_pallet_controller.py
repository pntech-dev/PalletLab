from __future__ import annotations

import pytest

from palletlab.controllers.pallet_controller import PalletController
from palletlab.controllers.viewport_geometry import beam_faces, editable_dimensions, insertion_markers, insertion_preview
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

    def show_insertion_preview(self, preview) -> None:
        self.previews.append(preview)

    def enable_insertion_mode(self, _markers, _callback) -> None:
        pass

    def enable_distance_editing(self, _dimensions, _callback) -> None:
        pass

    def clear_insertion_selection(self) -> None:
        self.insertion_cleared += 1

    def clear_insertion_preview(self) -> None:
        self.preview_cleared += 1


def _controller(*, input_provider=None):
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
        input_provider=input_provider,
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
    requests = [(LENGTH_INPUT, WIDTH_INPUT, "width")]
    controller, state, _view, timer, _calculated, _errors, stale = _controller(input_provider=lambda: requests.pop())

    controller.schedule_recalculation()
    controller.schedule_recalculation()
    timer.timeout.callback()

    assert timer.starts == 2
    assert stale == [True, True, False]
    assert state.result is not None


def test_controller_handles_insert_delete_and_distance_edits_through_project_state():
    controller, state, view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    slot = next(slot for slot in insertion_slots(result, "length") if slot.after_beam_index == 1)

    assert controller.begin_insertion(slot)
    controller.preview_insertion(100)
    axis, inserted = controller.confirm_insertion(100)
    assert axis == "length"
    assert state.length_input is inserted
    assert view.previews[-1].size[0] == result.length_result.beam_width

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


def test_viewport_geometry_is_prepared_outside_the_3d_view():
    controller, _state, _view, _timer, _calculated, _errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    slot = next(slot for slot in insertion_slots(result, "length") if slot.after_beam_index == 1)

    markers = insertion_markers(result, (slot,))
    preview = insertion_preview(result, slot, 100)
    dimensions = editable_dimensions(result)

    assert markers[0].slot is slot
    assert markers[0].preview.size == preview.size
    assert preview.size[0] == result.length_result.beam_width
    assert {dimension.axis for dimension in dimensions} == {"length", "width"}


def test_viewport_geometry_uses_actual_faces_after_a_section_change():
    from palletlab.core.calculator import build_pallet, calculate_direction
    from palletlab.core.models import BeamSection

    length = calculate_direction(LENGTH_INPUT)
    width = calculate_direction(WIDTH_INPUT)
    result = build_pallet(length, width, section_overrides={("length", 1): BeamSection(70, 80)})

    faces = beam_faces(result, "length")
    dimensions = editable_dimensions(result)
    first_internal = next(item for item in dimensions if item.axis == "length" and item.index == 1)
    assert faces[1][0] == pytest.approx(length.beam_centers[1] - 40)
    assert first_internal.value == pytest.approx(faces[1][0] - faces[0][0])
