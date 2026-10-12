"""Application release version read from the single project VERSION file."""

from __future__ import annotations

import sys
from pathlib import Path


def _version_file() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "VERSION"
    return Path(__file__).resolve().parents[2] / "VERSION"


__version__ = _version_file().read_text(encoding="utf-8").strip()
