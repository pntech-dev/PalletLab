"""Prepared 3D primitives passed from the controller to the viewport."""

from __future__ import annotations

from dataclasses import dataclass

from palletlab.core.calculator import inserted_beam_center
from palletlab.core.models import InsertionSlot, PalletAxis, PalletResult


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
    axis: PalletAxis
    index: int
    value: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]


def _display_y(result: PalletResult, y: float) -> float:
    return result.pallet_width - y


def beam_faces(result: PalletResult, axis: PalletAxis) -> tuple[tuple[float, float], ...]:
    """Return the real left/right (or start/end) faces of beams on one axis."""
    length_count = len(result.length_result.beam_centers)
    beams = result.beams_3d[:length_count] if axis == "length" else result.beams_3d[length_count:]
    if axis == "length":
        return tuple((beam.x - beam.size_x / 2, beam.x + beam.size_x / 2) for beam in beams)
    return tuple((beam.y - beam.size_y / 2, beam.y + beam.size_y / 2) for beam in beams)


def insertion_markers(result: PalletResult, slots: tuple[InsertionSlot, ...]) -> tuple[InsertionMarker, ...]:
    size = max(24.0, min(result.pallet_length, result.pallet_width) * 0.06)
    markers = []
    for slot in slots:
        faces = beam_faces(result, slot.axis)
        start = faces[slot.after_beam_index][1]
        end = faces[slot.after_beam_index + 1][0]
        position = (start + end) / 2
        center = ((position, _display_y(result, result.pallet_width / 2), result.pallet_height + 5)
                  if slot.axis == "length"
                  else (result.pallet_length / 2, _display_y(result, position), result.pallet_height + 5))
        markers.append(InsertionMarker(slot, center, size, insertion_preview(result, slot, slot.suggested_clear_gap)))
    return tuple(markers)


def insertion_preview(result: PalletResult, slot: InsertionSlot, clear_gap: float) -> PreviewBox:
    direction = result.length_result if slot.axis == "length" else result.width_result
    center = inserted_beam_center(direction, slot.after_beam_index, clear_gap)
    if slot.axis == "length":
        z = result.width_result.beam_height if result.upper_layer == "length" else 0.0
        return PreviewBox((center, _display_y(result, result.pallet_width / 2), z + direction.beam_height / 2),
                          (direction.beam_width, result.pallet_width, direction.beam_height))
    z = result.length_result.beam_height if result.upper_layer == "width" else 0.0
    return PreviewBox((result.pallet_length / 2, _display_y(result, center), z + direction.beam_height / 2),
                      (result.pallet_length, direction.beam_width, direction.beam_height))


def editable_dimensions(result: PalletResult) -> tuple[EditableDimension, ...]:
    handles = []
    for axis, direction, offset in (
        ("length", result.length_result, max(50.0, result.pallet_width * 0.055)),
        ("width", result.width_result, max(50.0, result.pallet_length * 0.035)),
    ):
        faces = beam_faces(result, axis)
        base = faces[0][0]
        last = len(direction.beam_centers) - 1
        for index, _center in enumerate(direction.beam_centers[1:], start=1):
            end = faces[index][1] if index == last else faces[index][0]
            if axis == "length":
                start_point, end_point = (base, _display_y(result, -offset * index), result.pallet_height + 2), (end, _display_y(result, -offset * index), result.pallet_height + 2)
            else:
                start_point, end_point = (-offset * index, _display_y(result, base), result.pallet_height + 2), (-offset * index, _display_y(result, end), result.pallet_height + 2)
            handles.append(EditableDimension(axis, index, end - base, start_point, end_point))
    return tuple(handles)
