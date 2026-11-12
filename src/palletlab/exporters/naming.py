"""Shared Russian names for exported pallet beam models."""

from __future__ import annotations


def beam_display_name(length: float, width: float, height: float) -> str:
    section_name = "Доска" if height < width else "Брус"
    return (
        f"{section_name} {_format_measure(height)}x{_format_measure(width)} "
        f"L={_format_measure(length)}"
    )


def _format_measure(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}"
