"""Common types used by the native drawing exporters.

The template remains the authority for ESKD/GOST formatting: sheet format,
title block, fonts, dimension style, tolerances and other enterprise rules.
The generators below only create associative model views and annotations; they
never try to replace a certified company drawing template.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palletlab.core.models import PalletResult


class DrawingScope(str, Enum):
    """Which documents receive drawings in one export run."""

    ASSEMBLY_ONLY = "assembly"
    PARTS_AND_ASSEMBLY = "parts_and_assembly"


class DrawingExportError(RuntimeError):
    """A user-facing failure while generating native drawings."""


class DrawingTemplateError(DrawingExportError):
    """A requested CAD system has neither a custom nor default template."""


@dataclass(frozen=True)
class DrawingRequest:
    """CAD-independent options collected by the drawing dialog."""

    scope: DrawingScope
    template: Path | None = None


@dataclass(frozen=True)
class SpecificationRow:
    """One grouped beam item in an assembly drawing specification."""

    position: int
    name: str
    dimensions: str
    quantity: int


def assembly_specification_rows(result: PalletResult) -> tuple[SpecificationRow, ...]:
    """Group identical pallet beams into the rows shown on an assembly sheet."""
    groups: dict[tuple[float, float, float], int] = defaultdict(int)
    for beam in result.beams_3d:
        length, width = (beam.size_y, beam.size_x) if beam.orientation == "width" else (beam.size_x, beam.size_y)
        groups[(length, width, beam.size_z)] += 1

    def number(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:g}"

    return tuple(
        SpecificationRow(
            position=index,
            name="Брус",
            dimensions="×".join(number(value) for value in dimensions),
            quantity=quantity,
        )
        for index, (dimensions, quantity) in enumerate(sorted(groups.items()), start=1)
    )

