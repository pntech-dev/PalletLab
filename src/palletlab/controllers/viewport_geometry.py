"""Prepared 3D primitives passed from the controller to the viewport."""

from __future__ import annotations

from dataclasses import dataclass

from palletlab.core.calculator import inserted_beam_center
from palletlab.core.models import InsertionSlot, ManualBeamInput, PalletAxis, PalletResult
from palletlab.core.validation import CalculationError


@dataclass(frozen=True)
class InsertionMarker:
    slot: InsertionSlot
    center: tuple[float, float, float]
    size: float
    preview: "PreviewBox"


@dataclass(frozen=True)
class PreviewBox:
    center: tuple[float, float, float]
    size: tuple[float, float, float]


@dataclass(frozen=True)
class EditableDimension:
    layer_id: str
    axis: PalletAxis
    index: int
    value: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    editable: bool = True
    start_extension: tuple[float, float, float] | None = None
    end_extension: tuple[float, float, float] | None = None
    edit_value: float | None = None


def _display_y(result: PalletResult, y: float) -> float:
    return result.pallet_width - y


def beam_faces(result: PalletResult, layer_id: str) -> tuple[tuple[float, float], ...]:
    """Return the real faces of one layer's beams, in layer order."""
    beams = tuple(beam for beam in result.beams_3d if (beam.layer_id or beam.orientation) == layer_id)
    if not beams and layer_id in ("length", "width"):
        # Compatibility with results created by older callers.
        beams = tuple(beam for beam in result.beams_3d if (beam.orientation == "width") == (layer_id == "length"))
    axis: PalletAxis = "length" if beams and beams[0].orientation == "width" else "width"
    if axis == "length":
        return tuple((beam.x - beam.size_x / 2, beam.x + beam.size_x / 2) for beam in beams)
    return tuple((beam.y - beam.size_y / 2, beam.y + beam.size_y / 2) for beam in beams)


def insertion_markers(result: PalletResult, slots: tuple[InsertionSlot, ...]) -> tuple[InsertionMarker, ...]:
    size = max(24.0, min(result.pallet_length, result.pallet_width) * 0.06)
    layer_number = {layer.layer_id: number for number, layer in enumerate(result.layers, start=1)}
    markers = []
    for slot in slots:
        layer_id = slot.layer_id or slot.axis
        faces = beam_faces(result, layer_id)
        start = faces[slot.after_beam_index][1]
        end = faces[slot.after_beam_index + 1][0]
        position = (start + end) / 2
        # A stack may contain equal grids on several layers.  Markers placed
        # above the pallet then overlap perfectly and only the top actor can
        # be picked.  Put each layer on its own outer guide line while keeping
        # it aligned with the exact gap it represents.
        # ``PalletView`` gives a plus a hitbox of ``size * 2.4``.  The guide
        # spacing must exceed that hitbox, otherwise a click on a third-layer
        # marker can be intercepted by the same gap in the first layer.
        guide_offset = max(64.0, size * 2.6) * layer_number.get(layer_id, 1)
        center = ((position, _display_y(result, result.pallet_width + guide_offset), result.pallet_height + 5)
                  if slot.axis == "length"
                  else (result.pallet_length + guide_offset, _display_y(result, position), result.pallet_height + 5))
        markers.append(InsertionMarker(slot, center, size, insertion_preview(result, slot, slot.suggested_clear_gap)))
    return tuple(markers)


def insertion_preview(result: PalletResult, slot: InsertionSlot, clear_gap: float) -> PreviewBox:
    layer_id = slot.layer_id or slot.axis
    beams = tuple(beam for beam in result.beams_3d if (beam.layer_id or beam.orientation) == layer_id)
    if not beams:
        raise CalculationError("Слой для добавления бруса больше не существует.")
    source = beams[slot.after_beam_index]
    faces = beam_faces(result, layer_id)
    center = faces[slot.after_beam_index][1] + source.size_x / 2 + max(0.0, clear_gap) if slot.axis == "length" else faces[slot.after_beam_index][1] + source.size_y / 2 + max(0.0, clear_gap)
    if slot.axis == "length":
        return PreviewBox((center, _display_y(result, source.y), source.z),
                          (source.size_x, source.size_y, source.size_z))
    return PreviewBox((source.x, _display_y(result, center), source.z),
                      (source.size_x, source.size_y, source.size_z))


def editable_dimensions(
    result: PalletResult, manual_beams: tuple[ManualBeamInput, ...] = (),
) -> tuple[EditableDimension, ...]:
    handles = []
    layer_ids = tuple(dict.fromkeys(beam.layer_id or beam.orientation for beam in result.beams_3d))
    layer_beams = {
        layer_id: tuple(beam for beam in result.beams_3d if (beam.layer_id or beam.orientation) == layer_id)
        for layer_id in layer_ids
    }
    # A manually added beam is selectable, but it has no neighbouring beam
    # from which to form a dimension chain.  It must not replace a structural
    # layer as the source of the visible dimensions.
    dimension_layers = tuple(
        layer_id for layer_id, beams in layer_beams.items()
        if not layer_id.startswith("manual-") and len(beams) > 1
    )
    # Show one clear dimension chain per axis.  Prefer a parallel layer whose
    # visible outer faces still cover the pallet envelope.  An upper layer can
    # have both edge beams deliberately hidden; in that case its remaining
    # beams must not make the dimensions disappear while a lower parallel
    # layer still provides the real outer faces.
    visible_layer_by_axis: dict[PalletAxis, str] = {}
    for layer_id in dimension_layers:
        beams = layer_beams[layer_id]
        axis: PalletAxis = "length" if beams[0].orientation == "width" else "width"
        current = visible_layer_by_axis.get(axis)
        if current is None or _dimension_layer_priority(result, beams, axis) > _dimension_layer_priority(
            result, layer_beams[current], axis,
        ):
            visible_layer_by_axis[axis] = layer_id
    for layer_id in dimension_layers:
        beams = layer_beams[layer_id]
        axis: PalletAxis = "length" if beams[0].orientation == "width" else "width"
        # One clear dimension chain per axis is readable and corresponds to
        # the editable visible grid.  Repeating it for every stacked layer
        # causes extension lines to cross as soon as sections differ.
        if visible_layer_by_axis[axis] != layer_id:
            continue
        # Use the same pitch for both directions.
        offset = max(50.0, result.pallet_width * 0.045)
        faces = beam_faces(result, layer_id)
        base = faces[0][0]
        last = len(beams) - 1
        for index in range(1, len(beams)):
            end = faces[index][1] if index == last else faces[index][0]
            if axis == "length":
                start_point, end_point = (base, _display_y(result, -offset * index), result.pallet_height + 2), (end, _display_y(result, -offset * index), result.pallet_height + 2)
            else:
                start_point, end_point = (-offset * index, _display_y(result, base), result.pallet_height + 2), (-offset * index, _display_y(result, end), result.pallet_height + 2)
            value = end - base
            handles.append(EditableDimension(layer_id, axis, beams[index].layer_index, value, start_point, end_point))
    # The calculated pallet envelope remains meaningful after every beam of
    # one direction is hidden.  Do not make its overall length/width vanish
    # merely because there is no longer a same-direction chain to edit: the
    # perpendicular beams still make the physical pallet and its dimensions
    # visible.  This fallback is deliberately read-only because it has no
    # surviving beam index to move.
    for axis in ("length", "width"):
        if result.beams_3d and _needs_envelope_dimension(result, axis, handles):
            handles.append(_envelope_dimension(result, axis))
    handles.extend(_manual_beam_dimensions(result, manual_beams, handles))
    return _arrange_base_dimensions(result, tuple(handles))


def _envelope_dimension(result: PalletResult, axis: PalletAxis) -> EditableDimension:
    """Return an editable overall size when a visible chain is absent.

    The controller maps this synthetic dimension back to the last physical
    beam of the appropriate layer, so users can still change the maximum
    pallet length or width after an outer beam was hidden.
    """
    offset = max(50.0, result.pallet_width * 0.045)
    z = result.pallet_height + 2
    if axis == "length":
        start, end = (0.0, _display_y(result, -offset), z), (result.pallet_length, _display_y(result, -offset), z)
    else:
        start, end = (-offset, _display_y(result, 0.0), z), (-offset, _display_y(result, result.pallet_width), z)
    return EditableDimension(f"pallet-{axis}", axis, 0, result.pallet_length if axis == "length" else result.pallet_width,
                             start, end, editable=True)


def _needs_envelope_dimension(
    result: PalletResult, axis: PalletAxis, dimensions: list[EditableDimension],
) -> bool:
    """Keep the overall size if hidden edge beams shortened every chain."""
    envelope = result.pallet_length if axis == "length" else result.pallet_width
    tolerance = max(1e-6, envelope * 1e-9)
    return not any(
        dimension.axis == axis
        and abs(dimension.value - envelope) <= tolerance
        and dimension.start_extension is None
        for dimension in dimensions
    )


def _dimension_layer_priority(result: PalletResult, beams: tuple, axis: PalletAxis) -> tuple[bool, float]:
    """Rank a dimension source by envelope coverage, then visible height."""
    faces = (
        tuple((beam.x - beam.size_x / 2, beam.x + beam.size_x / 2) for beam in beams)
        if axis == "length"
        else tuple((beam.y - beam.size_y / 2, beam.y + beam.size_y / 2) for beam in beams)
    )
    envelope = result.pallet_length if axis == "length" else result.pallet_width
    tolerance = max(1e-6, envelope * 1e-9)
    covers_envelope = faces[0][0] <= tolerance and faces[-1][1] >= envelope - tolerance
    return covers_envelope, max(beam.z for beam in beams)


def _arrange_base_dimensions(
    result: PalletResult, dimensions: tuple[EditableDimension, ...],
) -> tuple[EditableDimension, ...]:
    """Fit base-point measurements into the regular chain by their distance."""
    arranged = list(dimensions)
    offset = max(50.0, result.pallet_width * 0.045)
    for axis in ("length", "width"):
        indices = [
            index for index, dimension in enumerate(arranged)
            if dimension.axis == axis and dimension.start_extension is None
        ]
        for position, index in enumerate(sorted(indices, key=lambda item: arranged[item].value), start=1):
            dimension = arranged[index]
            if axis == "length":
                y = _display_y(result, -offset * position)
                arranged[index] = EditableDimension(
                    dimension.layer_id, dimension.axis, dimension.index, dimension.value,
                    (dimension.start[0], y, dimension.start[2]), (dimension.end[0], y, dimension.end[2]),
                    dimension.editable, dimension.start_extension, dimension.end_extension, dimension.edit_value,
                )
            else:
                x = -offset * position
                arranged[index] = EditableDimension(
                    dimension.layer_id, dimension.axis, dimension.index, dimension.value,
                    (x, dimension.start[1], dimension.start[2]), (x, dimension.end[1], dimension.end[2]),
                    dimension.editable, dimension.start_extension, dimension.end_extension, dimension.edit_value,
                )
    return tuple(arranged)


def _manual_beam_dimensions(
    result: PalletResult,
    manual_beams: tuple[ManualBeamInput, ...],
    structural_dimensions: list[EditableDimension],
) -> tuple[EditableDimension, ...]:
    """Create read-only dimensions for explicitly placed beams.

    A distance entered from the base point is part of the regular dimension
    chain.  A distance entered from a selected beam instead belongs on the
    opposite side, where it remains legible without covering that chain.
    """
    source = {(beam.layer_id, beam.layer_index): beam for beam in result.beams_3d}
    by_id = {beam.layer_id: beam for beam in result.beams_3d if beam.layer_id.startswith("manual-")}
    counts = {
        axis: sum(1 for dimension in structural_dimensions if dimension.axis == axis)
        for axis in ("length", "width")
    }
    dimensions: list[EditableDimension] = []
    offset = max(50.0, result.pallet_width * 0.045)
    for item in manual_beams:
        beam = by_id.get(item.beam_id)
        if beam is None:
            continue
        axis: PalletAxis = "length" if beam.orientation == "width" else "width"
        reference = source.get(item.reference_support) if item.reference_support else None
        position = _manual_measurement_edge(beam, axis)
        if reference is None:
            counts[axis] += 1
            line_offset = offset * counts[axis]
            if axis == "length":
                start = (0.0, _display_y(result, -line_offset), result.pallet_height + 2)
                end = (position, _display_y(result, -line_offset), result.pallet_height + 2)
            else:
                start = (-line_offset, _display_y(result, 0.0), result.pallet_height + 2)
                end = (-line_offset, _display_y(result, position), result.pallet_height + 2)
        else:
            counts[axis] += 1
            line_offset = offset * counts[axis]
            reference_position, position = _facing_face_positions(reference, beam, axis)
            if axis == "length":
                start = (reference_position, _display_y(result, result.pallet_width + line_offset), result.pallet_height + 2)
                end = (position, _display_y(result, result.pallet_width + line_offset), result.pallet_height + 2)
                start_extension = (reference_position, _display_y(result, reference.y + reference.size_y / 2), result.pallet_height + 2)
                end_extension = (position, _display_y(result, beam.y + beam.size_y / 2), result.pallet_height + 2)
            else:
                start = (result.pallet_length + line_offset, _display_y(result, reference_position), result.pallet_height + 2)
                end = (result.pallet_length + line_offset, _display_y(result, position), result.pallet_height + 2)
                start_extension = (reference.x + reference.size_x / 2, _display_y(result, reference_position), result.pallet_height + 2)
                end_extension = (beam.x + beam.size_x / 2, _display_y(result, position), result.pallet_height + 2)
        if reference is None:
            start_extension = None
            end_extension = None
        dimensions.append(EditableDimension(
            item.beam_id, axis, 0, abs(position - (0.0 if reference is None else reference_position)), start, end,
            editable=True, start_extension=start_extension, end_extension=end_extension, edit_value=item.distance,
        ))
    return tuple(dimensions)


def _facing_face_positions(reference, beam, axis: PalletAxis) -> tuple[float, float]:
    """Return the two faces that look at each other across the beam gap."""
    if axis == "length":
        if beam.x >= reference.x:
            return reference.x + reference.size_x / 2, beam.x - beam.size_x / 2
        return reference.x - reference.size_x / 2, beam.x + beam.size_x / 2
    if beam.y >= reference.y:
        return reference.y + reference.size_y / 2, beam.y - beam.size_y / 2
    return reference.y - reference.size_y / 2, beam.y + beam.size_y / 2


def _manual_measurement_edge(beam, axis: PalletAxis) -> float:
    """Return the new beam face nearest to the signed base-point direction."""
    if axis == "length":
        return beam.x - beam.size_x / 2 if beam.x >= 0 else beam.x + beam.size_x / 2
    return beam.y - beam.size_y / 2 if beam.y >= 0 else beam.y + beam.size_y / 2
