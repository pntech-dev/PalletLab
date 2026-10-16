"""Material catalogue shared by the editor, calculations and CAD exporters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PalletMaterial:
    id: str
    name: str
    density_kg_m3: float
    solidworks_name: str
    kompas_name: str


MATERIALS = {
    "pine": PalletMaterial("pine", "Сосна", 500.0, "Сосна", "Сосна"),
    "spruce": PalletMaterial("spruce", "Ель", 450.0, "Ель", "Ель"),
}
DEFAULT_MATERIAL_ID = "pine"

# The first value is used for transverse beams and the second for longitudinal
# beams.  Pine preserves the established application appearance; spruce is
# intentionally a little darker while keeping the same warm wood palette.
WOOD_PALETTES = {
    "pine": {
        "length_beam": "#b7791f",
        "width_beam": "#8b5a2b",
        "default_edge": "#4a2c12",
    },
    "spruce": {
        "length_beam": "#9f681c",
        "width_beam": "#754a25",
        "default_edge": "#39220f",
    },
}


def get_material(material_id: str) -> PalletMaterial:
    return MATERIALS.get(material_id, MATERIALS[DEFAULT_MATERIAL_ID])


def wood_palette(material_id: str) -> dict[str, str]:
    """Return the viewport timber colours for a known material."""
    return WOOD_PALETTES.get(material_id, WOOD_PALETTES[DEFAULT_MATERIAL_ID]).copy()


def pallet_mass_kg(beams, material_id: str) -> float:
    volume_m3 = sum(beam.size_x * beam.size_y * beam.size_z for beam in beams) / 1_000_000_000
    return volume_m3 * get_material(material_id).density_kg_m3
