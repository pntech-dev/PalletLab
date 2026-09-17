"""Pure geometry calculations for PalletLab."""

from __future__ import annotations

import math
from typing import Iterable

from .models import Beam3D, DirectionInput, DirectionResult, LayerDirection, PalletResult
from .validation import CalculationError

EPSILON = 1e-7


def round_up_to_five(value: float) -> float:
    """Round a non-negative measurement upward to the next whole 5 mm."""
    return math.ceil(value / 5 - EPSILON) * 5


def round_to_fifty(value: float) -> float:
    """Round to 50 mm, dropping only a remainder smaller than 10 mm.

    This follows the production convention: 1908 -> 1900, while 1915 and
    1936 both become 1950.
    """
    lower = math.floor(value / 50) * 50
    remainder = value - lower
    if math.isclose(remainder, 0, abs_tol=EPSILON) or remainder < 10:
        return lower
    return lower + 50


def _validate_measurements(values: Iterable[tuple[str, float]], *, allow_empty: bool = False) -> None:
    for name, value in values:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise CalculationError(f"{name}: требуется конечное число.")
        if value < 0 or (not allow_empty and value == 0):
            raise CalculationError(f"{name}: значение должно быть больше нуля.")


def calculate_direction(data: DirectionInput) -> DirectionResult:
    """Calculate centres and clear gaps along one axis.

    Edge beams are placed fully inside 0..pallet_size; every other beam is
    centred precisely on its corresponding support.
    """
    _validate_measurements(
        (("Высота бруса", data.beam_height), ("Ширина бруса", data.beam_width))
    )
    if not data.support_distances:
        raise CalculationError("Укажите хотя бы одно расстояние между центрами соседних опор.")
    _validate_measurements(
        (("Расстояние между опорами", value) for value in data.support_distances)
    )
    _validate_measurements(
        (
            ("От габарита до первой опоры", data.first_edge_to_support),
            ("От последней опоры до габарита", data.last_support_to_edge),
            ("Отступ поддона с первой стороны", data.margin_start),
            ("Отступ поддона со второй стороны", data.margin_end),
        ),
        allow_empty=True,
    )

    machine_size = data.first_edge_to_support + sum(data.support_distances) + data.last_support_to_edge
    raw_pallet_size = data.margin_start + machine_size + data.margin_end
    if data.round_pallet_size:
        pallet_size = round_to_fifty(raw_pallet_size) if data.rounding_step == 50 else round_up_to_five(raw_pallet_size)
    else:
        pallet_size = raw_pallet_size
    support_positions = [data.margin_start + data.first_edge_to_support]
    for distance in data.support_distances:
        support_positions.append(support_positions[-1] + distance)
    centers = [data.beam_width / 2, *support_positions, pallet_size - data.beam_width / 2]

    for index, center in enumerate(centers):
        left, right = center - data.beam_width / 2, center + data.beam_width / 2
        if left < -EPSILON or right > pallet_size + EPSILON:
            raise CalculationError(f"Брус {index + 1} выходит за границу поддона.")

    gaps = tuple(centers[index + 1] - centers[index] - data.beam_width for index in range(len(centers) - 1))
    for index, gap in enumerate(gaps):
        if gap < -EPSILON:
            centre_distance = centers[index + 1] - centers[index]
            raise CalculationError(
                f"Брусья {index + 1} и {index + 2} пересекаются: "
                f"расстояние между центрами {centre_distance:g} мм, ширина бруса {data.beam_width:g} мм."
            )
    total = sum(gaps) + len(centers) * data.beam_width
    if not math.isclose(total, pallet_size, rel_tol=1e-9, abs_tol=EPSILON):
        raise CalculationError("Проверка геометрии не сошлась; модель не построена.")
    return DirectionResult(
        machine_size=machine_size,
        raw_pallet_size=raw_pallet_size,
        pallet_size=pallet_size,
        rounding_applied=data.round_pallet_size and not math.isclose(raw_pallet_size, pallet_size, abs_tol=EPSILON),
        beam_width=data.beam_width,
        beam_height=data.beam_height,
        support_positions=tuple(support_positions),
        beam_centers=tuple(centers),
        gaps=gaps,
    )


def build_pallet(length: DirectionResult, width: DirectionResult, upper_layer: LayerDirection = "width") -> PalletResult:
    """Turn two already-calculated directions into real 3D beam boxes.

    Input coordinates are the only positioning source: length-axis centres make
    beams spanning Y, while width-axis centres make beams spanning X.
    """
    if upper_layer not in ("length", "width"):
        raise CalculationError("Верхний слой должен быть задан как 'length' или 'width'.")
    lower = "width" if upper_layer == "length" else "length"
    z_length = width.beam_height if lower == "width" else 0.0
    z_width = length.beam_height if lower == "length" else 0.0
    beams: list[Beam3D] = []
    # Length-result centres lie on X: these beams span the full pallet width.
    for x in length.beam_centers:
        beams.append(Beam3D(x, width.pallet_size / 2, z_length + length.beam_height / 2,
                            length.beam_width, width.pallet_size, length.beam_height, "width"))
    # Width-result centres lie on Y: these beams span the full pallet length.
    for y in width.beam_centers:
        beams.append(Beam3D(length.pallet_size / 2, y, z_width + width.beam_height / 2,
                            length.pallet_size, width.beam_width, width.beam_height, "length"))
    result = PalletResult(length, width, length.pallet_size, width.pallet_size,
                          length.beam_height + width.beam_height, upper_layer, tuple(beams))
    bounds = pallet_bounds(result.beams_3d)
    if not (math.isclose(bounds[1] - bounds[0], result.pallet_length, abs_tol=EPSILON)
            and math.isclose(bounds[3] - bounds[2], result.pallet_width, abs_tol=EPSILON)):
        raise CalculationError("3D-геометрия не совпадает с рассчитанным габаритом поддона.")
    return result


def pallet_bounds(beams: Iterable[Beam3D]) -> tuple[float, float, float, float, float, float]:
    """Return xmin, xmax, ymin, ymax, zmin, zmax for physical beam boxes."""
    boxes = list(beams)
    if not boxes:
        raise CalculationError("Невозможно определить габариты пустой модели.")
    return (
        min(beam.x - beam.size_x / 2 for beam in boxes), max(beam.x + beam.size_x / 2 for beam in boxes),
        min(beam.y - beam.size_y / 2 for beam in boxes), max(beam.y + beam.size_y / 2 for beam in boxes),
        min(beam.z - beam.size_z / 2 for beam in boxes), max(beam.z + beam.size_z / 2 for beam in boxes),
    )
