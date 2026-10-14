"""Single source of truth for the editable pallet project.

The state deliberately contains no Qt or PyVista objects.  Controllers can
therefore update it independently from the form and the 3D viewport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .models import BeamKey, BeamSection, DirectionInput, InsertionSlot, LayerBeamKey, LayerInput, ManualBeamInput, PalletAxis, PalletResult
from .materials import DEFAULT_MATERIAL_ID


CameraMode = Literal["isometric", "top", "front", "side"]
ToolMode = Literal["none", "insertion", "deletion", "distance_editing", "section_editing"]


@dataclass
class ProjectState:
    """All mutable data that defines the current pallet project and its view."""

    length_input: DirectionInput | None = None
    width_input: DirectionInput | None = None
    upper_layer: Literal["length", "width"] = "width"
    rounding_step: Literal[0, 5, 50] = 50
    material_id: str = DEFAULT_MATERIAL_ID
    result: PalletResult | None = None

    active_tool: ToolMode = "none"
    pending_insertion: InsertionSlot | None = None
    pending_distance: tuple[str, int] | None = None
    selected_for_deletion: dict[str, set[int]] = field(
        default_factory=lambda: {"length": set(), "width": set()}
    )
    selected_for_section: dict[str, set[int]] = field(
        default_factory=lambda: {"length": set(), "width": set()}
    )
    # Per-beam sections deliberately live beside the direction inputs: the
    # latter describe the coordinate grid, while these overrides describe the
    # physical timber mounted on that grid.
    beam_sections: dict[BeamKey, BeamSection] = field(default_factory=dict)
    # The canonical source for the upcoming multilayer editor.  The legacy
    # length/width inputs remain while the current two-panel UI is retained.
    layers: list[LayerInput] = field(default_factory=list)
    layer_sections: dict[LayerBeamKey, BeamSection] = field(default_factory=dict)
    manual_beams: list[ManualBeamInput] = field(default_factory=list)
    multi_layer_mode: bool = False

    camera: CameraMode = "isometric"
    show_length_dimensions: bool = True
    show_width_dimensions: bool = True

    def input_for(self, axis: PalletAxis) -> DirectionInput | None:
        """Return the editable input associated with an axis."""
        return self.length_input if axis == "length" else self.width_input

    def set_input(self, axis: PalletAxis, data: DirectionInput) -> None:
        """Replace one direction's input without touching the other project data."""
        if axis == "length":
            self.length_input = data
        else:
            self.width_input = data

    def set_layers(self, layers: list[LayerInput]) -> None:
        """Replace the ordered layer stack and discard sections for removed layers."""
        layer_ids = {layer.layer_id for layer in layers}
        self.layers = layers
        self.layer_sections = {
            key: section for key, section in self.layer_sections.items() if key[0] in layer_ids
        }
