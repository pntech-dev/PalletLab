"""User-readable validation errors for the framework-independent model."""

from __future__ import annotations


class CalculationError(ValueError):
    """An entered pallet geometry cannot physically be constructed."""

