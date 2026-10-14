"""Pure geometry calculations for PalletLab."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable, Mapping, Sequence

from .models import Beam3D, BeamKey, BeamSection, DirectionInput, DirectionResult, InsertionSlot, LayerDefinition, LayerDirection, LayerResult, PalletAxis, PalletResult
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
    if data.support_positions is None:
        support_positions = [data.margin_start + data.first_edge_to_support]
        for distance in data.support_distances:
            support_positions.append(support_positions[-1] + distance)
    else:
        _validate_measurements((("Позиция опоры", value) for value in data.support_positions))
        support_positions = list(data.support_positions)
    centers = [data.beam_width / 2, *support_positions, pallet_size - data.beam_width / 2]
    hidden = tuple(sorted(set(data.hidden_beam_indices)))
    if any(not isinstance(index, int) or index < 0 or index >= len(centers) for index in hidden):
        raise CalculationError("Удалённый брус относится к несуществующей позиции.")
    if len(hidden) >= len(centers):
        raise CalculationError("В слое должен остаться хотя бы один брус.")

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
        hidden_beam_indices=hidden,
    )


def insertion_slots(result: PalletResult, axis: PalletAxis) -> tuple[InsertionSlot, ...]:
    """Return gaps large enough to accept a same-section beam in *axis*."""
    direction = result.length_result if axis == "length" else result.width_result
    return insertion_slots_for_direction(axis, axis, direction)


def insertion_slots_for_direction(
    layer_id: str, axis: PalletAxis, direction: DirectionResult,
) -> tuple[InsertionSlot, ...]:
    """Return insertion slots for one explicitly identified pallet layer."""
    slots = []
    for after_beam_index, gap in enumerate(direction.gaps):
        maximum_clear_gap = gap - direction.beam_width
        if maximum_clear_gap >= -EPSILON:
            maximum_clear_gap = max(0.0, maximum_clear_gap)
            slots.append(InsertionSlot(axis, after_beam_index, maximum_clear_gap, maximum_clear_gap / 2, layer_id))
    return tuple(slots)


def inserted_beam_center(direction: DirectionResult, after_beam_index: int, clear_gap: float) -> float:
    """Return the centre of a beam placed after an existing beam's outer face."""
    if not 0 <= after_beam_index < len(direction.gaps):
        raise CalculationError("Выбранное место для нового бруса больше не существует.")
    maximum_clear_gap = direction.gaps[after_beam_index] - direction.beam_width
    if clear_gap < -EPSILON or clear_gap > maximum_clear_gap + EPSILON:
        raise CalculationError("Новый брус не помещается в выбранный промежуток.")
    return direction.beam_centers[after_beam_index] + direction.beam_width + max(0.0, clear_gap)


def insert_beam(result: PalletResult, slot: InsertionSlot, clear_gap: float) -> PalletResult:
    """Return a new pallet with one internal same-section beam inserted."""
    direction = result.length_result if slot.axis == "length" else result.width_result
    center = inserted_beam_center(direction, slot.after_beam_index, clear_gap)
    centers = list(direction.beam_centers)
    centers.insert(slot.after_beam_index + 1, center)
    gaps = tuple(centers[index + 1] - centers[index] - direction.beam_width for index in range(len(centers) - 1))
    updated_direction = replace(direction, support_positions=tuple(centers[1:-1]), beam_centers=tuple(centers), gaps=gaps)
    if slot.axis == "length":
        return build_pallet(updated_direction, result.width_result, result.upper_layer)
    return build_pallet(result.length_result, updated_direction, result.upper_layer)


def insert_beam_input(
    data: DirectionInput, direction: DirectionResult, after_beam_index: int, clear_gap: float
) -> DirectionInput:
    """Translate a face-gap insertion into the existing support-spacing input model."""
    center = inserted_beam_center(direction, after_beam_index, clear_gap)
    if data.support_positions is not None:
        positions = list(data.support_positions)
        positions.insert(after_beam_index, center)
        return _input_with_support_positions(data, direction, positions)
    distances = list(data.support_distances)
    if after_beam_index == 0:
        distances.insert(0, direction.beam_centers[1] - center)
        # The new first support can occupy the old pallet margin. Moving that
        # amount into the first-edge distance keeps all beam coordinates and
        # the total pallet size unchanged.
        return replace(data, margin_start=0.0, first_edge_to_support=center, support_distances=tuple(distances))
    if after_beam_index == len(direction.beam_centers) - 2:
        final_machine_edge = direction.raw_pallet_size - data.margin_end
        distances.append(center - direction.beam_centers[after_beam_index])
        return replace(data, support_distances=tuple(distances), last_support_to_edge=final_machine_edge - center)
    distance_index = after_beam_index - 1
    next_center = direction.beam_centers[after_beam_index + 1]
    distances[distance_index:distance_index + 1] = [
        center - direction.beam_centers[after_beam_index], next_center - center
    ]
    return replace(data, support_distances=tuple(distances))


def _input_with_support_positions(
    data: DirectionInput, direction: DirectionResult, positions: Iterable[float]
) -> DirectionInput:
    """Encode support centres in editable form fields whenever possible."""
    centres = tuple(positions)
    if not centres:
        # A blank distances field normally represents one support; retaining
        # this explicit empty tuple is the only unambiguous zero-support case.
        # Keep the original pallet span: the two edge beams must not collapse
        # merely because every internal support was removed.
        return replace(
            data,
            support_distances=(),
            first_edge_to_support=0.0,
            last_support_to_edge=direction.machine_size,
            support_positions=(),
        )
    return replace(
        data,
        support_distances=tuple(right - left for left, right in zip(centres, centres[1:])),
        first_edge_to_support=centres[0] - data.margin_start,
        last_support_to_edge=direction.raw_pallet_size - data.margin_end - centres[-1],
        support_positions=None,
    )


def delete_beams_input(
    data: DirectionInput, direction: DirectionResult, beam_indices: Iterable[int]
) -> DirectionInput:
    """Persist removal of beams, including physical edge beams."""
    selected = set(beam_indices)
    if not selected:
        return data
    last_index = len(direction.beam_centers) - 1
    if any(not isinstance(index, int) or index < 0 or index > last_index for index in selected):
        raise CalculationError("Выбран несуществующий брус.")
    if len(set(data.hidden_beam_indices) | selected) >= len(direction.beam_centers):
        raise CalculationError("В слое должен остаться хотя бы один брус.")
    edge_indices = {index for index in selected if index in (0, last_index)}
    internal_indices = selected - edge_indices
    remaining = tuple(center for index, center in enumerate(direction.beam_centers) if index not in internal_indices)
    updated = _input_with_support_positions(data, direction, remaining[1:-1]) if internal_indices else data
    hidden_before = set(data.hidden_beam_indices) | edge_indices
    hidden_after = tuple(
        index - sum(removed < index for removed in internal_indices)
        for index in sorted(hidden_before)
        if index not in internal_indices
    )
    return replace(updated, hidden_beam_indices=hidden_after)


def set_beam_face_distance_input(
    data: DirectionInput, direction: DirectionResult, beam_index: int, face_distance: float
) -> DirectionInput:
    """Persist a displayed cumulative dimension to an internal beam or pallet edge.

    Dimension annotations are measured from the outer face of the first edge
    beam.  Moving an internal dimension changes that support beam centre;
    moving the final dimension changes the pallet's end margin.
    """
    last_index = len(direction.beam_centers) - 1
    if not 0 < beam_index <= last_index:
        raise CalculationError("Изменять можно только размер от первого края поддона.")
    _validate_measurements((("Новое расстояние", face_distance),))
    if beam_index == last_index:
        margin_end = data.margin_end + face_distance - direction.raw_pallet_size
        _validate_measurements((("Отступ поддона с конца", margin_end),), allow_empty=True)
        return replace(data, margin_end=margin_end)
    positions = list(direction.beam_centers[1:-1])
    positions[beam_index - 1] = face_distance + direction.beam_width / 2
    return _input_with_support_positions(data, direction, positions)


def _section_for(
    axis: PalletAxis, index: int, direction: DirectionResult, overrides: Mapping[BeamKey, BeamSection],
) -> BeamSection:
    section = overrides.get((axis, index), BeamSection(direction.beam_height, direction.beam_width))
    _validate_measurements((("Высота сечения бруса", section.height), ("Ширина сечения бруса", section.width)))
    return section


def _centres_for_sections(direction: DirectionResult, sections: tuple[BeamSection, ...]) -> tuple[float, ...]:
    """Keep the two structural edge beams flush with the pallet boundary."""
    centres = list(direction.beam_centers)
    if len(centres) > 1:
        centres[0] = sections[0].width / 2
        centres[-1] = direction.pallet_size - sections[-1].width / 2
    return tuple(centres)


def _validate_sections(
    direction: DirectionResult, sections: tuple[BeamSection, ...], centres: tuple[float, ...],
) -> None:
    """Ensure individually sized beams fit on their physical centre grid."""
    for index, (center, section) in enumerate(zip(centres, sections)):
        if center - section.width / 2 < -EPSILON or center + section.width / 2 > direction.pallet_size + EPSILON:
            raise CalculationError(f"Брус {index + 1} выходит за границу поддона после изменения сечения.")
    for index, (left, right) in enumerate(zip(sections, sections[1:])):
        centre_distance = centres[index + 1] - centres[index]
        required_distance = (left.width + right.width) / 2
        if centre_distance < required_distance - EPSILON:
            raise CalculationError(
                f"Брусья {index + 1} и {index + 2} пересекаются после изменения сечения: "
                f"расстояние между центрами {centre_distance:g} мм, требуется не менее {required_distance:g} мм."
            )


def build_multilayer_pallet(layers: Sequence[LayerDefinition]) -> PalletResult:
    """Build any number of layers supplied from bottom to top.

    Every layer has its own beam grid and section set.  The first layer is
    top-aligned so a shorter selected beam cannot leave the second layer
    hanging; every later layer starts at the bearing plane of the layer below.
    A pallet must contain at least one X-grid and one Y-grid layer in order to
    define both external dimensions.
    """
    if not layers:
        raise CalculationError("Поддон должен содержать хотя бы один слой.")
    if len({layer.layer_id for layer in layers}) != len(layers) or any(not layer.layer_id for layer in layers):
        raise CalculationError("Каждый слой должен иметь уникальный идентификатор.")
    by_axis: dict[PalletAxis, list[LayerDefinition]] = {"length": [], "width": []}
    for layer in layers:
        if layer.axis not in by_axis:
            raise CalculationError("Направление слоя должно быть «длина» или «ширина».")
        by_axis[layer.axis].append(layer)
    if not by_axis["length"] or not by_axis["width"]:
        raise CalculationError("Для габаритов поддона нужны слои по длине и ширине.")

    def axis_size(axis: PalletAxis) -> float:
        sizes = [layer.direction.pallet_size for layer in by_axis[axis]]
        if any(not math.isclose(size, sizes[0], abs_tol=EPSILON) for size in sizes[1:]):
            raise CalculationError(f"Слои по оси {axis} должны иметь одинаковый габарит поддона.")
        return sizes[0]

    pallet_length, pallet_width = axis_size("length"), axis_size("width")
    beams: list[Beam3D] = []
    calculated_layers: list[LayerResult] = []
    base_z = 0.0
    for layer_index, layer in enumerate(layers):
        direction = layer.direction
        sections = layer.sections or tuple(
            BeamSection(direction.beam_height, direction.beam_width) for _ in direction.beam_centers
        )
        if len(sections) != len(direction.beam_centers):
            raise CalculationError(f"Слой «{layer.layer_id}» содержит неверное число сечений брусьев.")
        centres = _centres_for_sections(direction, sections)
        _validate_sections(direction, sections, centres)
        visible_indices = tuple(index for index in range(len(sections)) if index not in direction.hidden_beam_indices)
        layer_height = max(sections[index].height for index in visible_indices)
        top_z = base_z + layer_height
        beam_start_index = len(beams)
        for beam_index, (centre, section) in enumerate(zip(centres, sections)):
            if beam_index in direction.hidden_beam_indices:
                continue
            # The first layer is top-aligned to provide one continuous bearing
            # plane for the next layer.  Other layers rest on the plane below.
            z = top_z - section.height / 2 if layer_index == 0 else base_z + section.height / 2
            if layer.axis == "length":
                beams.append(Beam3D(
                    centre, pallet_width / 2, z, section.width, pallet_width, section.height,
                    "width", layer.layer_id, beam_index,
                ))
            else:
                beams.append(Beam3D(
                    pallet_length / 2, centre, z, pallet_length, section.width, section.height,
                    "length", layer.layer_id, beam_index,
                ))
        calculated_layers.append(LayerResult(
            layer.layer_id, layer.axis, base_z, top_z, beam_start_index, len(visible_indices)
        ))
        base_z = top_z

    length_result = by_axis["length"][0].direction
    width_result = by_axis["width"][0].direction
    result = PalletResult(
        length_result, width_result, pallet_length, pallet_width, base_z,
        layers[-1].axis, tuple(beams), tuple(calculated_layers),
    )
    bounds = pallet_bounds(result.beams_3d)
    if not (math.isclose(bounds[1] - bounds[0], pallet_length, abs_tol=EPSILON)
            and math.isclose(bounds[3] - bounds[2], pallet_width, abs_tol=EPSILON)):
        raise CalculationError("3D-геометрия не совпадает с рассчитанным габаритом поддона.")
    return result


def build_pallet(
    length: DirectionResult,
    width: DirectionResult,
    upper_layer: LayerDirection = "width",
    section_overrides: Mapping[BeamKey, BeamSection] | None = None,
) -> PalletResult:
    """Turn two already-calculated directions into real 3D beam boxes.

    Input coordinates are the only positioning source: length-axis centres make
    beams spanning Y, while width-axis centres make beams spanning X.
    """
    if upper_layer not in ("length", "width"):
        raise CalculationError("Верхний слой должен быть задан как 'length' или 'width'.")
    overrides = section_overrides or {}
    valid_keys = {
        *( ("length", index) for index in range(len(length.beam_centers)) ),
        *( ("width", index) for index in range(len(width.beam_centers)) ),
    }
    if any(key not in valid_keys for key in overrides):
        raise CalculationError("Изменённое сечение относится к брусу, которого больше нет.")
    length_sections = tuple(_section_for("length", index, length, overrides) for index in range(len(length.beam_centers)))
    width_sections = tuple(_section_for("width", index, width, overrides) for index in range(len(width.beam_centers)))
    length_centres = _centres_for_sections(length, length_sections)
    width_centres = _centres_for_sections(width, width_sections)
    _validate_sections(length, length_sections, length_centres)
    _validate_sections(width, width_sections, width_centres)

    lower = "width" if upper_layer == "length" else "length"
    lower_direction = width if lower == "width" else length
    lower_sections = width_sections if lower == "width" else length_sections
    lower_height = max(
        section.height for index, section in enumerate(lower_sections)
        if index not in lower_direction.hidden_beam_indices
    )
    # A layer is a bearing plane.  Beams with a smaller height are therefore
    # lifted inside their own lower layer so their *upper* faces remain flush
    # with the highest beam.  Keeping them on Z=0 would leave a visible and
    # structural gap below every beam of the next layer.
    z_length = lower_height if lower == "width" else 0.0
    z_width = lower_height if lower == "length" else 0.0
    beams: list[Beam3D] = []
    # Length-result centres lie on X: these beams span the full pallet width.
    for index, (x, section) in enumerate(zip(length_centres, length_sections)):
        if index in length.hidden_beam_indices:
            continue
        beam_z = z_length + section.height / 2 if lower != "length" else lower_height - section.height / 2
        beams.append(Beam3D(x, width.pallet_size / 2, beam_z,
                            section.width, width.pallet_size, section.height, "width", "length", index))
    # Width-result centres lie on Y: these beams span the full pallet length.
    for index, (y, section) in enumerate(zip(width_centres, width_sections)):
        if index in width.hidden_beam_indices:
            continue
        beam_z = z_width + section.height / 2 if lower != "width" else lower_height - section.height / 2
        beams.append(Beam3D(length.pallet_size / 2, y, beam_z,
                            length.pallet_size, section.width, section.height, "length", "width", index))
    upper_direction = length if upper_layer == "length" else width
    upper_sections = length_sections if upper_layer == "length" else width_sections
    result = PalletResult(
        length, width, length.pallet_size, width.pallet_size,
        lower_height + max(
            section.height for index, section in enumerate(upper_sections)
            if index not in upper_direction.hidden_beam_indices
        ), upper_layer, tuple(beams),
    )
    bounds = pallet_bounds(result.beams_3d)
    if not (math.isclose(bounds[1] - bounds[0], result.pallet_length, abs_tol=EPSILON)
            and math.isclose(bounds[3] - bounds[2], result.pallet_width, abs_tol=EPSILON)):
        raise CalculationError("3D-геометрия не совпадает с рассчитанным габаритом поддона.")
    return result


def pallet_bounds(beams: Iterable[Beam3D]) -> tuple[float, float, float, float, float, float]:
    """Return xmin, xmax, ymin, ymax, zmin, zmax for physical beam boxes."""
    iterator = iter(beams)
    try:
        first = next(iterator)
    except StopIteration:
        raise CalculationError("Невозможно определить габариты пустой модели.")
    xmin, xmax = first.x - first.size_x / 2, first.x + first.size_x / 2
    ymin, ymax = first.y - first.size_y / 2, first.y + first.size_y / 2
    zmin, zmax = first.z - first.size_z / 2, first.z + first.size_z / 2
    for beam in iterator:
        xmin = min(xmin, beam.x - beam.size_x / 2)
        xmax = max(xmax, beam.x + beam.size_x / 2)
        ymin = min(ymin, beam.y - beam.size_y / 2)
        ymax = max(ymax, beam.y + beam.size_y / 2)
        zmin = min(zmin, beam.z - beam.size_z / 2)
        zmax = max(zmax, beam.z + beam.size_z / 2)
    return xmin, xmax, ymin, ymax, zmin, zmax
