from __future__ import annotations

import pytest

from palletlab.controllers.pallet_controller import PalletController
from palletlab.controllers.viewport_geometry import beam_faces, editable_dimensions, insertion_markers, insertion_preview
from palletlab.core.calculator import calculate_direction, insertion_slots, insertion_slots_for_direction
from palletlab.core.models import BeamSection, DirectionInput, LayerInput
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
    assert view.rendered == [(result, {"show_length_gaps": True, "show_width_gaps": True, "material_id": "pine"})]
    assert calculated == [result]
    assert errors == []
    assert stale == [False]
    assert timer.stops == 1


def test_controller_calculates_an_ordered_multilayer_stack():
    controller, state, view, _timer, calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]

    result = controller.calculate_layers(layers)

    assert result is state.result
    assert state.multi_layer_mode
    assert state.layers == layers
    assert result.pallet_height == 210
    assert view.rendered[-1][0] is result
    assert calculated == [result]
    assert errors == []


def test_multilayer_tools_edit_the_selected_layer_not_another_layer_with_the_same_axis():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]
    result = controller.calculate_layers(layers)
    assert result is not None
    bottom_slot = next(slot for slot in insertion_slots_for_direction("bottom", "length", calculate_direction(LENGTH_INPUT))
                       if slot.after_beam_index == 1)
    top_slot = next(slot for slot in insertion_slots_for_direction("top", "length", calculate_direction(LENGTH_INPUT))
                    if slot.after_beam_index == 1)
    markers = insertion_markers(result, (bottom_slot, top_slot))
    assert markers[0].center != markers[1].center
    assert markers[0].center[1] < 0
    assert markers[1].center[1] < 0
    assert abs(markers[0].center[1] - markers[1].center[1]) > markers[0].size * 2.4
    controller.set_section_selection("top", 3, True)
    assert controller.apply_section_change(BeamSection(100, 80)) is not None
    assert state.layer_sections[("top", 3)] == BeamSection(100, 80)
    slot = next(slot for slot in insertion_slots_for_direction("top", "length", calculate_direction(LENGTH_INPUT))
                if slot.after_beam_index == 1)

    assert controller.begin_insertion(slot)
    layer_id, inserted = controller.confirm_insertion(100)
    assert layer_id == "top"
    assert next(layer for layer in state.layers if layer.layer_id == "top").direction is inserted
    assert next(layer for layer in state.layers if layer.layer_id == "bottom").direction is LENGTH_INPUT
    assert state.layer_sections[("top", 4)] == BeamSection(100, 80)

    assert controller.recalculate_from_state() is not None
    second_slot = next(
        slot for slot in insertion_slots_for_direction("top", "length", calculate_direction(inserted))
        if slot.after_beam_index == 2
    )
    assert controller.begin_insertion(second_slot)
    layer_id, inserted_again = controller.confirm_insertion(80)
    assert layer_id == "top"
    assert len(calculate_direction(inserted_again).beam_centers) == len(calculate_direction(inserted).beam_centers) + 1

    assert controller.recalculate_from_state() is not None
    controller.set_section_selection("top", 1, True)
    assert controller.apply_section_change(BeamSection(100, 100)) is not None
    assert state.layer_sections[("top", 1)] == BeamSection(100, 100)
    assert ("bottom", 1) not in state.layer_sections
    assert errors == []


def test_adding_the_first_extra_layer_preserves_legacy_section_changes():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    controller.set_section_selection("length", 1, True)
    assert controller.apply_section_change(BeamSection(100, 80)) is not None
    assert state.beam_sections[("length", 1)] == BeamSection(100, 80)

    layers = [
        LayerInput("length", "length", LENGTH_INPUT),
        LayerInput("width", "width", WIDTH_INPUT),
        LayerInput("layer-1", "length", LENGTH_INPUT),
    ]
    assert controller.calculate_layers(layers) is not None
    assert state.layer_sections[("length", 1)] == BeamSection(100, 80)
    assert errors == []


def test_manual_beam_spans_the_outer_edges_of_two_selected_supports():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None

    updated = controller.add_manual_beam(("width", 0), ("width", 1), 1000, BeamSection(70, 50))
    assert updated is not None
    beam = next(beam for beam in updated.beams_3d if beam.layer_id == "manual-1")
    supports = [beam for beam in result.beams_3d if beam.layer_id == "width"]
    expected_start = min(item.y - item.size_y / 2 for item in supports[:2])
    expected_end = max(item.y + item.size_y / 2 for item in supports[:2])
    assert beam.y - beam.size_y / 2 == pytest.approx(expected_start)
    assert beam.y + beam.size_y / 2 == pytest.approx(expected_end)
    assert beam.x == pytest.approx(1025)
    assert beam.x - beam.size_x / 2 == pytest.approx(1000)
    assert state.manual_beams[0].section == BeamSection(70, 50)
    assert errors == []


def test_manual_beam_can_be_built_below_two_selected_bottom_faces():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None

    updated = controller.add_manual_beam(
        ("width", 0), ("width", 1), 1000, BeamSection(70, 50),
        first_face="bottom", second_face="bottom",
    )
    assert updated is not None
    beam = next(beam for beam in updated.beams_3d if beam.layer_id == "manual-1")
    supports = [beam for beam in result.beams_3d if beam.layer_id == "width"]
    assert beam.z + beam.size_z / 2 == pytest.approx(min(item.z - item.size_z / 2 for item in supports[:2]))
    assert errors == []


def test_manual_beam_uses_the_selected_lateral_face_as_its_reference():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None

    updated = controller.add_manual_beam(
        ("width", 0), ("width", 1), 100, BeamSection(70, 50),
        reference_support=("width", 0), reference_face="x_max",
    )
    assert updated is not None
    beam = next(beam for beam in updated.beams_3d if beam.layer_id == "manual-1")
    reference = next(beam for beam in result.beams_3d if beam.layer_id == "width" and beam.layer_index == 0)
    assert beam.x == pytest.approx(reference.x + reference.size_x / 2 + 100 + beam.size_x / 2)
    assert errors == []


def test_negative_manual_beam_distance_keeps_its_absolute_edge_gap():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    original = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert original is not None

    result = controller.add_manual_beam(
        ("width", 0), ("width", 1), -300, BeamSection(70, 50),
        reference_support=("width", 0), reference_face="x_max",
    )

    assert result is not None
    reference = next(beam for beam in original.beams_3d if beam.layer_id == "width" and beam.layer_index == 0)
    beam = next(beam for beam in result.beams_3d if beam.layer_id == "manual-1")
    assert (reference.x - reference.size_x / 2) - (beam.x + beam.size_x / 2) == pytest.approx(300)
    dimension = next(item for item in editable_dimensions(result, tuple(state.manual_beams)) if item.layer_id == "manual-1")
    assert dimension.value == pytest.approx(300)
    assert errors == []


def test_manual_beam_accepts_zero_offset_from_a_selected_lateral_face():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None

    updated = controller.add_manual_beam(
        ("width", 0), ("width", 1), 0, BeamSection(70, 50),
        reference_support=("width", 0), reference_face="x_max",
    )
    assert updated is not None
    beam = next(beam for beam in updated.beams_3d if beam.layer_id == "manual-1")
    reference = next(beam for beam in result.beams_3d if beam.layer_id == "width" and beam.layer_index == 0)
    assert beam.x == pytest.approx(reference.x + reference.size_x / 2 + beam.size_x / 2)
    assert errors == []


def test_manual_beam_can_use_a_previous_manual_beam_as_its_reference():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    first_result = controller.add_manual_beam(("width", 0), ("width", 1), 1000, BeamSection(70, 50))
    assert first_result is not None
    first = next(beam for beam in first_result.beams_3d if beam.layer_id == "manual-1")

    result = controller.add_manual_beam(
        ("width", 0), ("width", 1), 100, BeamSection(70, 50),
        reference_support=("manual-1", 0), reference_face="x_max",
    )

    assert result is not None
    second = next(beam for beam in result.beams_3d if beam.layer_id == "manual-2")
    assert second.x == pytest.approx(first.x + first.size_x / 2 + 100 + second.size_x / 2)
    assert state.manual_beams[-1].reference_support == ("manual-1", 0)
    assert errors == []


def test_manual_beam_dimensions_follow_the_chosen_reference_side():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None

    from_base = controller.add_manual_beam(("width", 0), ("width", 1), 1000, BeamSection(70, 50))
    assert from_base is not None
    dimensions = editable_dimensions(from_base, tuple(state.manual_beams))
    base_dimension = next(item for item in dimensions if item.layer_id == "manual-1")
    regular_length_dimensions = [item for item in dimensions if item.axis == "length" and item.editable and item.layer_id != "manual-1"]
    assert base_dimension.value == pytest.approx(1000)
    assert base_dimension.start[0] == pytest.approx(0)
    assert base_dimension.end[0] == pytest.approx(1000)
    preceding = max((item for item in regular_length_dimensions if item.value < base_dimension.value), key=lambda item: item.value)
    following = min((item for item in regular_length_dimensions if item.value > base_dimension.value), key=lambda item: item.value)
    assert preceding.start[1] < base_dimension.start[1] < following.start[1]
    assert base_dimension.editable
    assert base_dimension.edit_value == pytest.approx(1000)

    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    original = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert original is not None
    from_object = controller.add_manual_beam(
        ("width", 0), ("width", 1), 100, BeamSection(70, 50),
        reference_support=("width", 0), reference_face="x_max",
    )
    assert from_object is not None
    dimensions = editable_dimensions(from_object, tuple(state.manual_beams))
    object_dimension = next(item for item in dimensions if item.layer_id == "manual-1")
    reference = next(beam for beam in original.beams_3d if beam.layer_id == "width" and beam.layer_index == 0)
    regular_length_dimensions = [item for item in dimensions if item.axis == "length" and item.editable and item.layer_id != "manual-1"]
    assert object_dimension.value == pytest.approx(100)
    assert object_dimension.start[0] == pytest.approx(reference.x + reference.size_x / 2)
    assert object_dimension.end[0] == pytest.approx(reference.x + reference.size_x / 2 + 100)
    assert object_dimension.start[1] < min(item.start[1] for item in regular_length_dimensions)
    assert object_dimension.start_extension is not None
    assert object_dimension.end_extension is not None
    assert object_dimension.start_extension[1] != pytest.approx(from_object.pallet_width)
    assert errors == []


def test_three_layer_pallet_accepts_a_manual_beam_at_the_base_point_and_section_changes():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]
    assert controller.calculate_layers(layers) is not None

    assert controller.add_manual_beam(("middle", 0), ("middle", 1), 0, BeamSection(70, 50)) is not None
    controller.set_section_selection("manual-1", 0, True)
    assert controller.apply_section_change(BeamSection(100, 80)) is not None
    assert state.manual_beams[0].distance == 0
    assert errors == []


def test_identical_dimensions_of_parallel_layers_are_not_duplicated():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate_layers([
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ])
    assert result is not None

    dimensions = editable_dimensions(result)
    length_dimensions = [item for item in dimensions if item.axis == "length"]
    assert len(length_dimensions) == len(result.length_result.beam_centers) - 1
    assert errors == []


def test_dimension_chain_uses_faces_of_the_uppermost_parallel_layer():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate_layers([
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]) is not None
    controller.set_section_selection("top", 1, True)
    result = controller.apply_section_change(BeamSection(100, 80))
    assert result is not None

    dimensions = editable_dimensions(result)
    assert {item.layer_id for item in dimensions if item.axis == "length"} == {"top"}
    assert errors == []


def test_dimension_chain_falls_back_to_a_parallel_layer_when_top_edge_beams_are_hidden():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate_layers([
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ])
    assert result is not None

    top_beam_count = len(calculate_direction(LENGTH_INPUT).beam_centers)
    controller.set_deletion_selection("top", 0, True)
    controller.set_deletion_selection("top", top_beam_count - 1, True)
    assert controller.confirm_deletion() is not None
    updated = controller.recalculate_from_state()

    assert updated is not None
    dimensions = editable_dimensions(updated)
    assert {item.layer_id for item in dimensions if item.axis == "length"} == {"bottom"}
    assert errors == []


def test_pallet_length_dimension_remains_when_no_cross_beam_chain_survives():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    # One of two extreme transverse beams is hidden, leaving no editable
    # cross-beam interval while the longitudinal layer stays visible.
    state.length_input = DirectionInput(
        70, 50, (), 0, 0, 100, 100, support_positions=(), hidden_beam_indices=(0,),
    )
    updated = controller.recalculate_from_state()

    assert updated is not None
    dimensions = editable_dimensions(updated)
    length_dimension = next(item for item in dimensions if item.layer_id == "pallet-length")
    assert length_dimension.value == pytest.approx(updated.pallet_length)
    assert length_dimension.editable
    assert errors == []


def test_pallet_length_dimension_remains_when_hidden_edges_leave_internal_cross_beams():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None
    direction = calculate_direction(LENGTH_INPUT)

    controller.set_deletion_selection("length", 0, True)
    controller.set_deletion_selection("length", len(direction.beam_centers) - 1, True)
    assert controller.confirm_deletion() is not None
    updated = controller.recalculate_from_state()

    assert updated is not None
    dimensions = editable_dimensions(updated)
    length_dimension = next(item for item in dimensions if item.layer_id == "pallet-length")
    assert length_dimension.value == pytest.approx(updated.pallet_length)
    assert length_dimension.editable
    assert errors == []


def test_envelope_dimension_edits_the_last_physical_beam_of_its_axis():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    original = state.length_input
    state.length_input = DirectionInput(
        70, 50, (), 0, 0, 100, 100, support_positions=(), hidden_beam_indices=(0,),
    )
    assert controller.recalculate_from_state() is not None

    controller.begin_distance_edit("pallet-length", 0)
    assert controller.confirm_distance_edit(1000) is not None

    assert state.length_input is not None
    assert state.length_input.margin_end != original.margin_end
    assert errors == []


def test_section_tool_changes_a_manually_added_beam():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    assert controller.add_manual_beam(("width", 0), ("width", 1), 1000, BeamSection(70, 50)) is not None

    controller.set_section_selection("manual-1", 0, True)
    result = controller.apply_section_change(BeamSection(100, 80))
    assert result is not None
    assert state.manual_beams[0].section == BeamSection(100, 80)
    beam = next(beam for beam in result.beams_3d if beam.layer_id == "manual-1")
    assert (beam.size_z, beam.size_x) == (100, 80)
    assert errors == []


def test_manual_beam_can_be_selected_and_deleted():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    assert controller.add_manual_beam(("width", 0), ("width", 1), 1000, BeamSection(70, 50)) is not None

    controller.set_deletion_selection("manual-1", 0, True)
    assert controller.confirm_deletion() == {}
    assert state.manual_beams == []
    assert errors == []


def test_invalid_manual_beam_is_rejected_without_changing_the_project():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None

    assert controller.add_manual_beam(
        ("width", 0), ("width", 0), 100, BeamSection(70, 50),
    ) is None

    assert state.manual_beams == []
    assert errors


def test_edge_beam_can_be_deleted_without_changing_the_pallet_envelope():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None

    controller.set_deletion_selection("length", 0, True)
    assert controller.confirm_deletion() is not None
    updated = controller.recalculate_from_state()
    assert updated is not None
    assert state.length_input.hidden_beam_indices == (0,)
    assert not any(beam.layer_id == "length" and beam.layer_index == 0 for beam in updated.beams_3d)
    assert updated.pallet_length == result.pallet_length
    assert errors == []


def test_deletion_is_atomic_and_clears_only_its_confirmed_selection():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    original = state.length_input
    controller.set_deletion_selection("length", 1, True)
    assert not controller.set_deletion_selection("removed-layer", 0, True)

    assert controller.confirm_deletion() is not None
    assert state.length_input != original
    assert state.selected_for_deletion == {"length": set(), "width": set()}

    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    controller.set_deletion_selection("length", 1, True)
    state.result = None
    assert controller.confirm_deletion() is None
    assert state.length_input == LENGTH_INPUT

    assert errors


def test_invalid_distance_edit_does_not_leave_an_unusable_zero_support_spacing():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    original = state.length_input

    controller.begin_distance_edit("length", 1)
    assert controller.confirm_distance_edit(1) is None

    assert state.length_input == original
    assert errors


def test_final_dimension_edit_keeps_parallel_multilayer_grids_on_one_envelope():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]
    result = controller.calculate_layers(layers)
    assert result is not None

    controller.begin_distance_edit("top", len(calculate_direction(LENGTH_INPUT).beam_centers) - 1)
    assert controller.confirm_distance_edit(result.pallet_length + 100) is not None
    updated = controller.recalculate_from_state()

    assert updated is not None
    length_sizes = [calculate_direction(layer.direction).pallet_size for layer in state.layers if layer.axis == "length"]
    assert length_sizes == [updated.pallet_length, updated.pallet_length]
    assert errors == []


def test_manual_beam_distance_can_be_changed_with_its_signed_input_value():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    assert controller.add_manual_beam(
        ("width", 0), ("width", 1), 100, BeamSection(70, 50),
        reference_support=("width", 0), reference_face="x_max",
    ) is not None

    controller.begin_distance_edit("manual-1", 0)
    assert controller.confirm_distance_edit(-300) == ("manual-1", None)
    assert state.manual_beams[0].distance == pytest.approx(-300)
    result = controller.recalculate_from_state()
    assert result is not None
    dimension = next(item for item in editable_dimensions(result, tuple(state.manual_beams)) if item.layer_id == "manual-1")
    assert dimension.value == pytest.approx(300)
    assert dimension.edit_value == pytest.approx(-300)
    assert errors == []


def test_controller_debounces_automatic_recalculation():
    requests = [(LENGTH_INPUT, WIDTH_INPUT, "width")]
    controller, state, _view, timer, _calculated, _errors, stale = _controller(input_provider=lambda: requests.pop())

    controller.schedule_recalculation()
    controller.schedule_recalculation()
    timer.timeout.callback()

    assert timer.starts == 2
    assert stale == [True, True, False]
    assert state.result is not None


def test_invalid_calculation_keeps_the_previous_project_and_scene():
    controller, state, view, _timer, calculated, errors, _stale = _controller()
    original = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert original is not None

    invalid = DirectionInput(70, 50, (30,), 100, 100, 100, 100)

    assert controller.calculate(invalid, WIDTH_INPUT, "width", show_error=False) is None
    assert state.length_input == LENGTH_INPUT
    assert state.result is original
    assert [rendered[0] for rendered in view.rendered] == [original]
    assert calculated == [original]
    assert errors


def test_cancelled_automatic_rebuild_cannot_apply_stale_form_values():
    requests = [(LENGTH_INPUT, WIDTH_INPUT, "width")]
    controller, state, view, timer, _calculated, _errors, _stale = _controller(
        input_provider=lambda: requests.pop(),
    )

    controller.schedule_recalculation()
    controller.invalidate_scheduled_recalculation()
    timer.timeout.callback()

    assert state.result is None
    assert view.rendered == []


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


def test_insertion_reindexes_manual_beam_supports_to_the_same_physical_beams():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert controller.add_manual_beam(
        ("width", 0), ("width", 1), 1000, BeamSection(70, 50),
        reference_support=("width", 0), reference_face="x_min",
    ) is not None
    slot = next(slot for slot in insertion_slots(result, "width") if slot.after_beam_index == 0)

    assert controller.begin_insertion(slot)
    assert controller.confirm_insertion(100) is not None

    manual = state.manual_beams[0]
    assert manual.first_support == ("width", 0)
    assert manual.second_support == ("width", 2)
    assert manual.reference_support == ("width", 0)
    assert controller.recalculate_from_state() is not None
    assert errors == []


def test_deletion_of_a_manual_beam_support_is_rejected_without_mutation():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert controller.add_manual_beam(("width", 0), ("width", 1), 1000, BeamSection(70, 50)) is not None
    original = state.width_input
    controller.set_deletion_selection("width", 1, True)

    assert controller.confirm_deletion() is None
    assert state.width_input is original
    assert len(state.manual_beams) == 1
    assert "ручные брусья" in errors[-1][0]


def test_deletion_reindexes_manual_supports_after_a_removed_preceding_beam():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert controller.add_manual_beam(("width", 2), ("width", 3), 1000, BeamSection(70, 50)) is not None
    controller.set_deletion_selection("width", 1, True)

    assert controller.confirm_deletion() is not None
    manual = state.manual_beams[0]
    assert manual.first_support == ("width", 1)
    assert manual.second_support == ("width", 2)
    assert controller.recalculate_from_state() is not None
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
