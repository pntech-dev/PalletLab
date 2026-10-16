"""Typed value objects shared by calculation and visualization layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


LayerDirection = Literal["length", "width"]
PalletAxis = Literal["length", "width"]
BeamKey = tuple[PalletAxis, int]
LayerBeamKey = tuple[str, int]


@dataclass(frozen=True)
class BeamSection:
    """Cross-section of one beam, expressed as height × width in millimetres."""

    height: float
    width: float


@dataclass(frozen=True)
class DirectionInput:
    """All measurements for one coordinate direction, expressed in millimetres."""

    beam_height: float
    beam_width: float
    support_distances: tuple[float, ...]
    first_edge_to_support: float
    last_support_to_edge: float
    margin_start: float
    margin_end: float
    round_pallet_size: bool = False
    rounding_step: Literal[5, 50] = 5
    # Interactive deletion can leave no support beams between the two edge
    # beams.  In that case distances alone are not enough to encode the
    # layout, so the UI keeps the exact remaining support centres here.
    support_positions: tuple[float, ...] | None = None
    # Edge beams can be removed while preserving the calculated pallet
    # envelope. Indices refer to the stable beam-centre sequence.
    hidden_beam_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class LayerInput:
    """Editable grid and direction of one layer in a multilayer pallet."""

    layer_id: str
    axis: PalletAxis
    direction: DirectionInput


@dataclass(frozen=True)
class ManualBeamInput:
    """A beam bridged between the outer edges of two selected pallet beams."""

    beam_id: str
    first_support: LayerBeamKey
    second_support: LayerBeamKey
    distance: float
    section: BeamSection
    reference_support: LayerBeamKey | None = None
    reference_face: str | None = None
    first_face: Literal["top", "bottom"] = "top"
    second_face: Literal["top", "bottom"] = "top"


@dataclass(frozen=True)
class DirectionResult:
    machine_size: float
    raw_pallet_size: float
    pallet_size: float
    rounding_applied: bool
    beam_width: float
    beam_height: float
    support_positions: tuple[float, ...]
    beam_centers: tuple[float, ...]
    gaps: tuple[float, ...]
    hidden_beam_indices: tuple[int, ...] = ()

    @property
    def support_count(self) -> int:
        return len(self.support_positions)

    @property
    def beam_count(self) -> int:
        return len(self.beam_centers)


@dataclass(frozen=True)
class LayerDefinition:
    """One pallet layer, listed in physical order from bottom to top."""

    layer_id: str
    axis: PalletAxis
    direction: DirectionResult
    # An empty tuple means that every beam uses the section from ``direction``.
    sections: tuple[BeamSection, ...] = ()


@dataclass(frozen=True)
class LayerResult:
    """Calculated vertical placement and beam range for one pallet layer."""

    layer_id: str
    axis: PalletAxis
    base_z: float
    top_z: float
    beam_start_index: int
    beam_count: int


@dataclass(frozen=True)
class InsertionSlot:
    """A valid place to insert a same-section beam after an existing beam."""

    axis: PalletAxis
    after_beam_index: int
    maximum_clear_gap: float
    suggested_clear_gap: float
    # The legacy two-layer pallet uses ``length``/``width`` as ids.  A real
    # layer id keeps an insertion unambiguous in a stack containing several
    # layers in the same direction.
    layer_id: str = ""


@dataclass(frozen=True)
class Beam3D:
    """Axis-aligned beam defined by its centre and physical dimensions."""

    x: float
    y: float
    z: float
    size_x: float
    size_y: float
    size_z: float
    orientation: LayerDirection
    layer_id: str = ""
    layer_index: int = 0


@dataclass(frozen=True)
class PalletResult:
    length_result: DirectionResult
    width_result: DirectionResult
    pallet_length: float
    pallet_width: float
    pallet_height: float
    upper_layer: LayerDirection
    beams_3d: tuple[Beam3D, ...]
    layers: tuple[LayerResult, ...] = ()
