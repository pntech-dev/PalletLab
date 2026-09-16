import math

import pytest

from palletlab.core.calculator import build_pallet, calculate_direction, pallet_bounds
from palletlab.core.models import DirectionInput
from palletlab.core.validation import CalculationError


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
