from palletlab.core.materials import get_material, pallet_mass_kg
from palletlab.core.models import Beam3D


def test_pine_is_the_safe_default_material():
    assert get_material("unknown").id == "pine"


def test_pallet_mass_uses_beam_volume_and_material_density():
    beam = Beam3D(0, 0, 0, 1000, 100, 100, "length")

    assert pallet_mass_kg((beam,), "pine") == 5.0
