"""Common types used by the native drawing exporters.

The template remains the authority for ESKD/GOST formatting: sheet format,
title block, fonts, dimension style, tolerances and other enterprise rules.
The generators below only create associative model views and annotations; they
never try to replace a certified company drawing template.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


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

