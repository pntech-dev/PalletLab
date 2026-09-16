"""Shared display formatting that does not depend on Qt or PyVista."""


def format_mm(value: float) -> str:
    """Show stable, human-friendly millimetres without floating point noise."""
    rounded = round(value, 2)
    return f"{rounded:.2f}".rstrip("0").rstrip(".")
