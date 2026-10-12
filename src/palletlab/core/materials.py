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
    "pine": PalletMaterial("pine", "Сосна", 500.0, "Pine", "Сосна"),
    "spruce": PalletMaterial("spruce", "Ель", 450.0, "Spruce", "Ель"),
}
DEFAULT_MATERIAL_ID = "pine"


def get_material(material_id: str) -> PalletMaterial:
    return MATERIALS.get(material_id, MATERIALS[DEFAULT_MATERIAL_ID])


def pallet_mass_kg(beams, material_id: str) -> float:
    volume_m3 = sum(beam.size_x * beam.size_y * beam.size_z for beam in beams) / 1_000_000_000
    return volume_m3 * get_material(material_id).density_kg_m3
