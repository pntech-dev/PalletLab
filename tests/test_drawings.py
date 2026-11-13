from palletlab.core.models import Beam3D, DirectionResult, PalletResult
from palletlab.exporters.drawings import assembly_specification_rows, packaging_specification_rows


def test_assembly_specification_groups_identical_beams_and_keeps_quantities():
    direction = DirectionResult(0, 0, 0, False, 0, 0, (), (), ())
    result = PalletResult(
        direction, direction, 2000, 1000, 140, "length",
        (
            Beam3D(0, 0, 0, 2000, 100, 70, "length"),
            Beam3D(0, 100, 0, 2000, 100, 70, "length"),
            Beam3D(100, 0, 0, 100, 1000, 70, "width"),
        ),
    )

    assert [(row.position, row.name, row.dimensions, row.quantity) for row in assembly_specification_rows(result)] == [
        (1, "Брус", "1000×100×70", 1),
        (2, "Брус", "2000×100×70", 2),
    ]


def test_packaging_specification_lists_the_pallet_subassembly_and_imported_model():
    direction = DirectionResult(0, 0, 0, False, 0, 0, (), (), ())
    result = PalletResult(direction, direction, 2000, 1000, 140, "length", ())

    rows = packaging_specification_rows(result, "press.step")

    assert [(row.position, row.name, row.dimensions, row.quantity) for row in rows] == [
        (1, "Поддон", "2000×1000×140", 1),
        (2, "press", "", 1),
    ]


def test_flat_packaging_specification_lists_pallet_parts_and_imported_model():
    direction = DirectionResult(0, 0, 0, False, 0, 0, (), (), ())
    result = PalletResult(
        direction,
        direction,
        2000,
        1000,
        140,
        "length",
        (
            Beam3D(0, 0, 0, 2000, 100, 70, "length"),
            Beam3D(0, 100, 0, 2000, 100, 70, "length"),
        ),
    )

    rows = packaging_specification_rows(result, "press.step", pallet_is_subassembly=False)

    assert [(row.position, row.name, row.dimensions, row.quantity) for row in rows] == [
        (1, "Брус", "2000×100×70", 2),
        (2, "press", "", 1),
    ]
