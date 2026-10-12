from __future__ import annotations

from pathlib import Path

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.exporters.solidworks import _matrix, _metres, _new_document, create_output_directory


def _result():
    length = DirectionInput(70, 50, (1000,), 100, 100, 100, 100)
    width = DirectionInput(80, 60, (800,), 100, 100, 100, 100)
    return build_pallet(calculate_direction(length), calculate_direction(width))


def test_export_directory_is_created_inside_chosen_parent_and_does_not_overwrite(tmp_path):
    first = create_output_directory(tmp_path, _result())
    second = create_output_directory(tmp_path, _result())

    assert first.parent == tmp_path
    assert first.is_dir()
    assert second.is_dir()
    assert second.name == f"{first.name}_2"


def test_new_document_uses_the_active_solidworks_document():
    document = object()

    class _SolidWorks:
        IActiveDoc2 = document

        def NewDocument(self, *_args):
            return document

    assert _new_document(_SolidWorks(), Path(__file__), "detail") is document


def test_solidworks_coordinates_are_floats_for_com():
    assert isinstance(_metres(0), float)
    assert isinstance(-_metres(50) / 2.0, float)


def test_transform_converts_palletlab_height_and_width_to_solidworks_axes():
    beam = Beam3D(1000, 2000, 150, 50, 3000, 70, "width")

    matrix = _matrix(beam)

    assert matrix[9:12] == (1.0, 0.15, 0.0)
    # A width beam's long local Z axis is the template's negative Z axis.
    assert matrix[6:9] == (0.0, 0.0, -1.0)


def test_lengthwise_beam_starts_at_the_shared_pallet_corner():
    beam = Beam3D(1500, 2000, 35, 4000, 50, 70, "length")

    matrix = _matrix(beam)

    assert matrix[9:12] == (0.0, 0.035, -2.0)
