"""Single source of truth for the editable pallet project.

The state deliberately contains no Qt or PyVista objects.  Controllers can
therefore update it independently from the form and the 3D viewport.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields
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


@dataclass
class ProjectHistory:
    """Bounded undo/redo history for editable project data only."""

    limit: int = 50
    undo_stack: list[ProjectState] = field(default_factory=list)
    redo_stack: list[ProjectState] = field(default_factory=list)

    @staticmethod
    def snapshot(state: ProjectState) -> ProjectState:
        """Copy persistent edit data without viewport results or tool state."""
        copied = deepcopy(state)
        copied.result = None
        copied.active_tool = "none"
        copied.pending_insertion = None
        copied.pending_distance = None
        copied.selected_for_deletion = {"length": set(), "width": set()}
        copied.selected_for_section = {"length": set(), "width": set()}
        return copied

    @staticmethod
    def _restore(state: ProjectState, snapshot: ProjectState) -> None:
        for item in fields(ProjectState):
            setattr(state, item.name, deepcopy(getattr(snapshot, item.name)))

    def record(self, snapshot: ProjectState) -> None:
        """Record the state from immediately before one completed action."""
        if self.undo_stack and self.undo_stack[-1] == snapshot:
            return
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self, state: ProjectState) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot(state))
        self._restore(state, self.undo_stack.pop())
        return True

    def redo(self, state: ProjectState) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot(state))
        self._restore(state, self.redo_stack.pop())
        return True

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()
