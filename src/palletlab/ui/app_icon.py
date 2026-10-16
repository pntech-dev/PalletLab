"""Application icon shared by the main program and its updater."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt5.QtGui import QIcon


def _application_icon_path() -> Path:
    """Locate the icon in source and frozen builds."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return bundle_root / "icon.ico"


@lru_cache(maxsize=1)
def application_icon() -> QIcon:
    """Return the bundled application icon in source and frozen builds."""
    return QIcon(str(_application_icon_path()))
