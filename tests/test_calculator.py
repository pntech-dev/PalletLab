from dataclasses import replace

import pytest

from palletlab.core.calculator import (build_multilayer_pallet, build_pallet, calculate_direction, delete_beams_input, insert_beam, insert_beam_input,
                                       insertion_slots, pallet_bounds)
from palletlab.core.calculator import set_beam_face_distance_input
from palletlab.core.models import BeamSection, DirectionInput, LayerDefinition
from palletlab.core.validation import CalculationError
from palletlab.visualization.pallet_view import PalletView


WIDTH_EXAMPLE = DirectionInput(70, 50, (560, 720), 277.55, 179, 100, 100)
LENGTH_EXAMPLE = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100)


def test_width_example_calculates_specification_values():
    result = calculate_direction(WIDTH_EXAMPLE)
    assert result.machine_size == pytest.approx(1736.55)
    assert result.pallet_size == pytest.approx(1936.55)
    assert result.support_count == 3
    assert result.beam_count == 5
    assert result.beam_centers == pytest.approx((25, 377.55, 937.55, 1657.55, 1911.55))
    assert result.gaps == pytest.approx((302.55, 510, 670, 204))
    assert sum(result.gaps) + result.beam_count * result.beam_width == pytest.approx(result.pallet_size)


def test_length_example_calculates_specification_values():
    result = calculate_direction(LENGTH_EXAMPLE)
    assert result.machine_size == 4004
    assert result.pallet_size == 4204
    assert result.support_count == 5
    assert result.beam_count == 7
    assert result.gaps == pytest.approx((148, 1020, 410, 1250, 449, 577))


def test_optional_rounding_increases_pallet_to_next_five_mm_without_moving_supports():
    exact = calculate_direction(LENGTH_EXAMPLE)
    rounded = calculate_direction(DirectionInput(
        70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100, round_pallet_size=True
    ))
    assert exact.pallet_size == 4204
    assert rounded.raw_pallet_size == 4204
    assert rounded.pallet_size == 4205
    assert rounded.rounding_applied
    assert rounded.support_positions == exact.support_positions
    assert rounded.gaps[-1] == pytest.approx(exact.gaps[-1] + 1)


def test_rounding_fractional_dimension_uses_next_five_mm():
    rounded = calculate_direction(DirectionInput(70, 50, (560, 720), 277.55, 179, 100, 100, True))
    assert rounded.pallet_size == 1940


@pytest.mark.parametrize(("raw_size", "rounded_size"), [(1936, 1950), (1915, 1950), (1908, 1900)])
def test_fifty_millimetre_rounding_follows_the_production_threshold(raw_size, rounded_size):
    rounded = calculate_direction(DirectionInput(70, 50, (100,), raw_size - 350, 100, 100, 50, True, 50))
    assert rounded.raw_pallet_size == raw_size
    assert rounded.pallet_size == rounded_size


def test_custom_section_and_asymmetric_margins_are_used():
    result = calculate_direction(DirectionInput(42.5, 80.25, (300.5,), 100.25, 50.5, 20.25, 70.75))
    assert result.machine_size == pytest.approx(451.25)
    assert result.pallet_size == pytest.approx(542.25)
    assert result.beam_height == 42.5
    assert result.beam_width == 80.25
    assert result.beam_centers[0] == pytest.approx(40.125)
    assert result.beam_centers[-1] == pytest.approx(502.125)


@pytest.mark.parametrize("data", [
    DirectionInput(70, 50, (30,), 100, 100, 100, 100),
])
def test_overlapping_beams_raise_readable_error(data):
    with pytest.raises(CalculationError, match="пересекаются"):
        calculate_direction(data)


def test_too_small_start_margin_can_put_internal_beam_outside_pallet():
    with pytest.raises(CalculationError, match="выходит за границу"):
        calculate_direction(DirectionInput(70, 50, (100,), 10, 100, 0, 100))


@pytest.mark.parametrize("data", [
    DirectionInput(-70, 50, (100,), 100, 100, 100, 100),
    DirectionInput(70, 0, (100,), 100, 100, 100, 100),
    DirectionInput(70, 50, (float("nan"),), 100, 100, 100, 100),
    DirectionInput(70, 50, (100,), -1, 100, 100, 100),
])
def test_invalid_measurements_raise_errors(data):
    with pytest.raises(CalculationError):
        calculate_direction(data)


def test_pallet_geometry_matches_calculated_dimensions_and_layer_switch():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)
    width_upper = build_pallet(length, width, "width")
    length_upper = build_pallet(length, width, "length")
    assert width_upper.pallet_height == 140
    assert len(width_upper.beams_3d) == 12
    assert pallet_bounds(width_upper.beams_3d) == pytest.approx((0, 4204, 0, 1936.55, 0, 140))
    assert pallet_bounds(length_upper.beams_3d) == pytest.approx((0, 4204, 0, 1936.55, 0, 140))
    # Upper-layer toggle must really move the corresponding physical beams.
    assert [b.z for b in width_upper.beams_3d if b.orientation == "length"][0] == pytest.approx(105)
    assert [b.z for b in length_upper.beams_3d if b.orientation == "length"][0] == pytest.approx(35)


def test_changed_lower_beam_section_lifts_the_whole_upper_layer_by_its_top_face():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)

    result = build_pallet(length, width, "width", {("length", 2): BeamSection(100, 50)})

    lower = result.beams_3d[:len(length.beam_centers)]
    upper = result.beams_3d[len(length.beam_centers):]
    assert {round(beam.z + beam.size_z / 2, 6) for beam in lower} == {100}
    assert all(beam.z - beam.size_z / 2 == pytest.approx(100) for beam in upper)
    assert result.pallet_height == pytest.approx(170)


def test_changed_sections_cannot_overlap_on_the_existing_beam_grid():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)

    with pytest.raises(CalculationError, match="после изменения сечения"):
        build_pallet(length, width, section_overrides={
            ("width", 1): BeamSection(70, 600),
            ("width", 2): BeamSection(70, 600),
        })


def test_changed_edge_sections_stay_flush_with_the_pallet_boundary():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)

    result = build_pallet(length, width, section_overrides={
        ("length", 0): BeamSection(70, 100),
        ("length", len(length.beam_centers) - 1): BeamSection(70, 100),
    })

    edge_beams = (result.beams_3d[0], result.beams_3d[len(length.beam_centers) - 1])
    assert edge_beams[0].x - edge_beams[0].size_x / 2 == pytest.approx(0)
    assert edge_beams[1].x + edge_beams[1].size_x / 2 == pytest.approx(result.pallet_length)


def test_multilayer_calculator_places_arbitrary_layers_in_bottom_to_top_order():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)
    result = build_multilayer_pallet((
        LayerDefinition("bottom", "length", length),
        LayerDefinition("middle", "width", width),
        LayerDefinition("top", "length", length),
    ))

    assert len(result.layers) == 3
    assert [(layer.layer_id, layer.base_z, layer.top_z) for layer in result.layers] == [
        ("bottom", 0, 70), ("middle", 70, 140), ("top", 140, 210),
    ]
    assert result.pallet_height == 210
    assert {beam.layer_id for beam in result.beams_3d} == {"bottom", "middle", "top"}


def test_multilayer_first_layer_aligns_shorter_beams_to_its_bearing_plane():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)
    sections = tuple(
        BeamSection(100 if index == 0 else 70, 50) for index in range(len(length.beam_centers))
    )
    result = build_multilayer_pallet((
        LayerDefinition("bottom", "length", length, sections),
        LayerDefinition("top", "width", width),
    ))

    bottom = result.beams_3d[:len(length.beam_centers)]
    top = result.beams_3d[len(length.beam_centers):]
    assert {round(beam.z + beam.size_z / 2, 6) for beam in bottom} == {100}
    assert all(beam.z - beam.size_z / 2 == pytest.approx(100) for beam in top)


def test_interactive_beam_insertion_uses_a_face_gap_and_updates_the_existing_input_model():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)
    result = build_pallet(length, width)
    slot = next(slot for slot in insertion_slots(result, "length") if slot.after_beam_index == 1)
    clear_gap = 100

    inserted = insert_beam(result, slot, clear_gap)
    expected_center = length.beam_centers[1] + length.beam_width + clear_gap
    assert inserted.length_result.beam_centers[2] == pytest.approx(expected_center)
    assert inserted.length_result.beam_count == length.beam_count + 1
    assert pallet_bounds(inserted.beams_3d) == pytest.approx((0, 4204, 0, 1936.55, 0, 140))

    updated_input = insert_beam_input(LENGTH_EXAMPLE, length, slot.after_beam_index, clear_gap)
    recalculated = calculate_direction(updated_input)
    assert recalculated.beam_centers == pytest.approx(inserted.length_result.beam_centers)


@pytest.mark.parametrize("after_beam_index", [0, -2])
def test_interactive_insertion_persists_at_the_first_and_last_available_gaps(after_beam_index):
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)
    result = build_pallet(length, width)
    index = len(length.beam_centers) + after_beam_index if after_beam_index < 0 else after_beam_index
    slot = next(slot for slot in insertion_slots(result, "length") if slot.after_beam_index == index)

    inserted = insert_beam(result, slot, min(20, slot.maximum_clear_gap))
    updated_input = insert_beam_input(LENGTH_EXAMPLE, length, slot.after_beam_index, min(20, slot.maximum_clear_gap))

    assert calculate_direction(updated_input).beam_centers == pytest.approx(inserted.length_result.beam_centers)


def test_interactive_deletion_preserves_remaining_beams_and_allows_multiple_selection():
    direction = calculate_direction(LENGTH_EXAMPLE)
    updated_input = delete_beams_input(LENGTH_EXAMPLE, direction, (1, 3))

    recalculated = calculate_direction(updated_input)
    assert recalculated.beam_centers == pytest.approx((25, 1293, 3053, 3552, 4179))
    assert updated_input.support_positions is None
    assert updated_input.support_distances == pytest.approx((1760, 499))
    assert updated_input.first_edge_to_support == pytest.approx(1193)
    assert updated_input.last_support_to_edge == pytest.approx(552)
    assert calculate_direction(replace(updated_input, first_edge_to_support=1200)).beam_centers[1] == pytest.approx(1300)


def test_interactive_deletion_can_leave_only_the_edge_beams():
    direction = calculate_direction(WIDTH_EXAMPLE)
    updated_input = delete_beams_input(WIDTH_EXAMPLE, direction, range(1, direction.beam_count - 1))

    recalculated = calculate_direction(updated_input)
    assert recalculated.beam_centers == pytest.approx((25, 1911.55))
    assert updated_input.support_positions == ()


def test_empty_support_data_with_zero_edge_distances_means_only_edge_beams():
    result = calculate_direction(DirectionInput(70, 50, (), 0, 0, 100, 100, support_positions=()))

    assert result.beam_centers == pytest.approx((25, 175))


@pytest.mark.parametrize("beam_indices", [(0,), (6,)])
def test_interactive_deletion_allows_edge_beams(beam_indices):
    direction = calculate_direction(LENGTH_EXAMPLE)
    updated = delete_beams_input(LENGTH_EXAMPLE, direction, beam_indices)
    assert updated.hidden_beam_indices == beam_indices


def test_interactive_deletion_rejects_a_nonexistent_beam():
    direction = calculate_direction(LENGTH_EXAMPLE)
    with pytest.raises(CalculationError, match="несуществующий"):
        delete_beams_input(LENGTH_EXAMPLE, direction, (-1,))


def test_editing_a_displayed_distance_moves_its_internal_beam_and_updates_input_data():
    direction = calculate_direction(LENGTH_EXAMPLE)
    updated_input = set_beam_face_distance_input(LENGTH_EXAMPLE, direction, 2, 1500)

    recalculated = calculate_direction(updated_input)
    assert recalculated.beam_centers[2] == pytest.approx(1525)
    assert updated_input.support_distances == pytest.approx((1302, 228, 1300, 499))


def test_editing_the_first_edge_dimension_is_rejected():
    direction = calculate_direction(LENGTH_EXAMPLE)
    with pytest.raises(CalculationError, match="первого края"):
        set_beam_face_distance_input(LENGTH_EXAMPLE, direction, 0, 100)


def test_editing_the_final_dimension_changes_the_pallet_size():
    direction = calculate_direction(LENGTH_EXAMPLE)
    updated_input = set_beam_face_distance_input(LENGTH_EXAMPLE, direction, direction.beam_count - 1, 4300)

    assert updated_input.margin_end == pytest.approx(196)
    assert calculate_direction(updated_input).pallet_size == pytest.approx(4300)


class _DimensionRecorder:
    """Minimal non-Qt receiver for testing the coordinates passed to PyVista."""

    _display_y = staticmethod(PalletView._display_y)

    def __init__(self):
        self.segments = []
        self.labels = []

    def _add_dimension_segment(self, start, end, name):
        self.segments.append((start, end, name))

    def _add_t_end(self, point, perpendicular, size, name):
        pass

    def add_point_labels(self, points, labels, **kwargs):
        self.labels = list(zip(points, labels))


def test_view_dimensions_are_cumulative_from_the_first_beam_outer_face():
    length = calculate_direction(LENGTH_EXAMPLE)
    width = calculate_direction(WIDTH_EXAMPLE)
    result = build_pallet(length, width)
    recorder = _DimensionRecorder()

    PalletView._add_length_gap_dimensions(recorder, result)

    dimension_segments = [segment for segment in recorder.segments if segment[2].startswith("length-dimension-")]
    assert len(dimension_segments) == len(length.beam_centers) - 1
    assert dimension_segments[0][0][0] == pytest.approx(0)
    for index, segment in enumerate(dimension_segments[:-1], start=1):
        assert segment[1][0] == pytest.approx(length.beam_centers[index] - length.beam_width / 2)
    assert recorder.labels[0][1] == f"{length.beam_centers[1] - length.beam_width / 2:g} mm"
    assert dimension_segments[-1][1][0] == pytest.approx(length.pallet_size)
    assert recorder.labels[-1][1] == f"{length.pallet_size:g} mm"
