from palletlab.core.materials import get_material, pallet_mass_kg, wood_palette
from palletlab.core.models import Beam3D


def test_pine_is_the_safe_default_material():
    assert get_material("unknown").id == "pine"


def test_pallet_mass_uses_beam_volume_and_material_density():
    beam = Beam3D(0, 0, 0, 1000, 100, 100, "length")

    assert pallet_mass_kg((beam,), "pine") == 5.0


def test_spruce_uses_a_darker_viewport_palette_than_default_pine():
    assert wood_palette("pine") == {
        "length_beam": "#b7791f", "width_beam": "#8b5a2b", "default_edge": "#4a2c12",
    }
    pine = wood_palette("pine")
    spruce = wood_palette("spruce")
    assert sum(bytes.fromhex(spruce["length_beam"][1:])) < sum(bytes.fromhex(pine["length_beam"][1:]))
    assert sum(bytes.fromhex(spruce["width_beam"][1:])) < sum(bytes.fromhex(pine["width_beam"][1:]))
    assert wood_palette("unknown") == wood_palette("pine")
