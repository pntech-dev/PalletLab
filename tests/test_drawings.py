from palletlab.core.models import Beam3D, DirectionResult, PalletResult
from palletlab.exporters.drawings import assembly_specification_rows


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
