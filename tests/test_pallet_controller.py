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


def test_deleting_beams_on_a_new_layer_keeps_other_layers_section_changes():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    controller.set_section_selection("length", 1, True)
    assert controller.apply_section_change(BeamSection(100, 80)) is not None
    controller.clear_section_selection()

    layers = [
        LayerInput("length", "length", LENGTH_INPUT),
        LayerInput("width", "width", WIDTH_INPUT),
        LayerInput("layer-1", "length", LENGTH_INPUT),
    ]
    assert controller.calculate_layers(layers) is not None
    controller.set_section_selection("layer-1", 2, True)
    assert controller.apply_section_change(BeamSection(90, 60)) is not None
    controller.clear_section_selection()

    controller.set_deletion_selection("layer-1", 1, True)
    assert controller.confirm_deletion() is not None
    assert controller.recalculate_from_state() is not None

    # Deleting an internal beam renumbers only the edited layer: the override
    # of the untouched "length" layer stays on the same physical beam, while
    # the override of the edited layer follows its new index.
    assert state.layer_sections[("length", 1)] == BeamSection(100, 80)
    assert state.layer_sections[("layer-1", 1)] == BeamSection(90, 60)
    result = state.result
    assert result is not None
    length_beam = next(beam for beam in result.beams_3d if beam.layer_id == "length" and beam.layer_index == 1)
    assert (length_beam.size_x, length_beam.size_z) == (80, 100)
    edited_layer_beam = next(beam for beam in result.beams_3d if beam.layer_id == "layer-1" and beam.layer_index == 1)
    assert (edited_layer_beam.size_x, edited_layer_beam.size_z) == (60, 90)
    assert errors == []


def test_insertion_uses_layer_section_even_if_anchor_was_manually_changed():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]
    assert controller.calculate_layers(layers) is not None
    controller.set_section_selection("top", 1, True)
    assert controller.apply_section_change(BeamSection(100, 80)) is not None
    controller.clear_section_selection()

    slot = next(slot for slot in insertion_slots_for_direction("top", "length", calculate_direction(LENGTH_INPUT))
                if slot.after_beam_index == 1)
    assert controller.begin_insertion(slot)
    assert controller.confirm_insertion(100) is not None
    assert controller.recalculate_from_state() is not None

    assert state.layer_sections[("top", 2)] == BeamSection(70, 50)
    added = next(beam for beam in state.result.beams_3d if beam.layer_id == "top" and beam.layer_index == 2)
    assert (added.size_x, added.size_z) == (50, 70)
    assert errors == []


def test_insertion_without_section_overrides_keeps_the_layer_form_section():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]
    assert controller.calculate_layers(layers) is not None

    slot = next(slot for slot in insertion_slots_for_direction("top", "length", calculate_direction(LENGTH_INPUT))
                if slot.after_beam_index == 1)
    assert controller.begin_insertion(slot)
    assert controller.confirm_insertion(100) is not None
    assert controller.recalculate_from_state() is not None

    # An inserted beam keeps its initial section when the layer is edited.
    assert state.layer_sections[("top", 2)] == BeamSection(70, 50)
    added = next(beam for beam in state.result.beams_3d if beam.layer_id == "top" and beam.layer_index == 2)
    assert (added.size_x, added.size_z) == (50, 70)
    from dataclasses import replace
    changed = [*state.layers[:-1], replace(state.layers[-1], direction=replace(state.layers[-1].direction, beam_height=100, beam_width=80))]
    result = controller.calculate_layers(changed)
    assert result is not None
    inserted = next(beam for beam in result.beams_3d if beam.layer_id == "top" and beam.layer_index == 2)
    automatic = next(beam for beam in result.beams_3d if beam.layer_id == "top" and beam.layer_index == 3)
    assert (inserted.size_x, inserted.size_z) == (50, 70)
    assert (automatic.size_x, automatic.size_z) == (80, 100)
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


def test_manual_beam_uses_outer_edges_even_when_the_viewport_click_is_saved():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    result = controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width")
    assert result is not None
    first, second = [beam for beam in result.beams_3d if beam.layer_id == "width"][:2]
    clicked_y = first.y + first.size_y / 4

    updated = controller.add_manual_beam(
        ("width", 0), ("width", 1), 1000, BeamSection(70, 50),
        start_point=(1000, clicked_y, first.z + first.size_z / 2),
    )

    assert updated is not None
    beam = next(item for item in updated.beams_3d if item.layer_id == "manual-1")
    expected_start = min(first.y - first.size_y / 2, second.y - second.size_y / 2)
    expected_end = max(first.y + first.size_y / 2, second.y + second.size_y / 2)
    assert beam.y - beam.size_y / 2 == pytest.approx(expected_start)
    assert beam.y + beam.size_y / 2 == pytest.approx(expected_end)
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


@pytest.mark.parametrize(("layer", "axis", "first_face", "second_face"), [
    ("width", "x", "x_max", "x_min"), ("length", "y", "y_max", "y_min"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_manual_beam_stays_centered_between_faces(layer, axis, first_face, second_face, reverse):
    from dataclasses import replace
    from palletlab.core.persistence import project_from_dict, project_to_dict

    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    reference_layer = "length" if layer == "width" else "width"
    ref1, ref2 = (reference_layer, 0), (reference_layer, 1)
    if reverse:
        ref1, ref2, first_face, second_face = ref2, ref1, second_face, first_face
    result = controller.add_manual_beam(
        (layer, 0), (layer, 1), 0, BeamSection(70, 50),
        reference_support=ref1, reference_face=first_face,
        second_reference_support=ref2, second_reference_face=second_face,
    )
    assert result is not None

    def verify(pallet):
        beam = next(item for item in pallet.beams_3d if item.layer_id == "manual-1")
        refs = [next(item for item in pallet.beams_3d if (item.layer_id, item.layer_index) == key) for key in (ref1, ref2)]
        first_coordinate = controller._reference_face_coordinate(refs[0], first_face)
        second_coordinate = controller._reference_face_coordinate(refs[1], second_face)
        assert getattr(beam, axis) == pytest.approx((first_coordinate + second_coordinate) / 2)
        dimension = next(item for item in editable_dimensions(pallet, tuple(state.manual_beams)) if item.layer_id == "manual-1")
        assert dimension.start[0 if axis == "x" else 1] == pytest.approx(0 if axis == "x" else pallet.pallet_width)
        assert dimension.value == pytest.approx(abs(getattr(beam, axis) - beam.size_x / 2 if axis == "x" else beam.y - beam.size_y / 2))
        assert not dimension.editable

    verify(result)
    saved = project_to_dict(state)
    restored = project_from_dict(saved)
    assert restored.manual_beams[0].second_reference_support == ref2
    assert restored.manual_beams[0].second_reference_face == second_face
    changed_length = replace(LENGTH_INPUT, support_distances=(1270, *LENGTH_INPUT.support_distances[1:]))
    changed_width = replace(WIDTH_INPUT, support_distances=(760, *WIDTH_INPUT.support_distances[1:]))
    changed = controller.calculate(changed_length, changed_width, "width")
    assert changed is not None
    verify(changed)
    assert errors == []


def test_centered_manual_beam_rejects_faces_that_do_not_face_each_other():
    controller, _state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    result = controller.add_manual_beam(
        ("width", 0), ("width", 1), 0, BeamSection(70, 50),
        reference_support=("length", 0), reference_face="x_min",
        second_reference_support=("length", 1), second_reference_face="x_max",
    )
    assert result is None
    assert errors


def test_centered_manual_beam_rejects_an_oversized_section_and_protects_both_references():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    assert controller.add_manual_beam(
        ("width", 0), ("width", 1), 0, BeamSection(70, 50),
        reference_support=("length", 0), reference_face="x_max",
        second_reference_support=("length", 1), second_reference_face="x_min",
    ) is not None
    controller.set_section_selection("manual-1", 0, True)
    assert controller.apply_section_change(BeamSection(70, 500)) is None
    assert state.manual_beams[0].section == BeamSection(70, 50)
    controller.set_deletion_selection("length", 1, True)
    assert controller.confirm_deletion() is None
    assert state.manual_beams[0].second_reference_support == ("length", 1)
    assert errors


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


@pytest.mark.parametrize(("support_layer", "face", "axis"), [("width", "x_max", 0), ("length", "y_max", 1)])
@pytest.mark.parametrize("distance", [100, -100])
def test_web_manual_dimension_extensions_touch_the_actual_beam_faces(support_layer, face, axis, distance):
    from palletlab.application.snapshots import pallet_snapshot

    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    assert controller.calculate(LENGTH_INPUT, WIDTH_INPUT, "width") is not None
    result = controller.add_manual_beam(
        (support_layer, 0), (support_layer, 1), distance, BeamSection(70, 50),
        reference_support=(support_layer, 0), reference_face=face,
    )
    assert result is not None
    reference = next(beam for beam in result.beams_3d if beam.layer_id == support_layer and beam.layer_index == 0)
    added = next(beam for beam in result.beams_3d if beam.layer_id == "manual-1")
    dimension = next(item for item in pallet_snapshot(result, tuple(state.manual_beams))["dimensions"]
                     if item["layerId"] == "manual-1")
    reference_direction = 1 if distance >= 0 else -1
    for endpoint, beam, direction in ((dimension["startExtension"], reference, reference_direction),
                                      (dimension["endExtension"], added, -reference_direction)):
        centers = (beam.x, beam.y)
        sizes = (beam.size_x, beam.size_y)
        assert endpoint[axis] == pytest.approx(centers[axis] + direction * sizes[axis] / 2)
        assert endpoint[1 - axis] == pytest.approx(centers[1 - axis] + sizes[1 - axis] / 2)
        assert endpoint[2] == pytest.approx(beam.z + beam.size_z / 2)
    assert abs(dimension["end"][axis] - dimension["start"][axis]) == pytest.approx(100)
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


def test_three_layer_pallet_rejects_a_manual_beam_above_its_top_layer():
    controller, state, _view, _timer, _calculated, errors, _stale = _controller()
    layers = [
        LayerInput("bottom", "length", LENGTH_INPUT),
        LayerInput("middle", "width", WIDTH_INPUT),
        LayerInput("top", "length", LENGTH_INPUT),
    ]
    assert controller.calculate_layers(layers) is not None

    assert controller.add_manual_beam(("top", 0), ("top", 1), 0, BeamSection(70, 50)) is None
    assert state.manual_beams == []
    assert "выше верхнего слоя" in errors[-1][0]


def test_identical_parallel_layers_share_one_dimension_chain():
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
    assert {item.layer_id for item in length_dimensions} == {"top"}
    assert errors == []


def test_dimension_chains_include_parallel_layers_with_different_sections():
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
    assert {item.layer_id for item in dimensions if item.axis == "length"} == {"bottom", "top"}
    assert errors == []


def test_dimension_chains_keep_the_lower_layer_when_top_edge_beams_are_hidden():
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
    assert {item.layer_id for item in dimensions if item.axis == "length"} == {"bottom", "top"}
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
