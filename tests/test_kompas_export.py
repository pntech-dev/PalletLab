from __future__ import annotations

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.exporters.kompas import _placement, create_output_directory


def _result():
    length = DirectionInput(70, 50, (1000,), 100, 100, 100, 100)
    width = DirectionInput(80, 60, (800,), 100, 100, 100, 100)
    return build_pallet(calculate_direction(length), calculate_direction(width))


def test_kompas_export_directory_is_created_inside_chosen_parent_without_overwrite(tmp_path):
    first = create_output_directory(tmp_path, _result())
    second = create_output_directory(tmp_path, _result())

    assert first.parent == tmp_path
    assert first.is_dir()
    assert second.name == f"{first.name}_2"


def test_kompas_placements_share_the_pallet_origin():
    lengthwise = Beam3D(1500, 2000, 105, 3000, 50, 70, "length")
    widthwise = Beam3D(1500, 2000, 35, 50, 3000, 70, "width")

    assert _placement(lengthwise) == (0.0, 1975.0, 70.0, False)
    assert _placement(widthwise) == (1525.0, 0.0, 0.0, True)
