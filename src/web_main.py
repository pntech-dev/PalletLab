"""Entrypoint for the React/pywebview PalletLab desktop application."""

import importlib
import sys
import traceback
from pathlib import Path

from palletlab.desktop.web_host import run_web_application


def _smoke_test() -> int:
    """Validate the frozen web entrypoint without opening a native window."""
    try:
        importlib.import_module("webview")
        from palletlab.desktop.web_host import frontend_entrypoint

        frontend_entrypoint()
    except BaseException:
        Path("palletlab-smoke-test-error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--smoke-test":
        raise SystemExit(_smoke_test())
    run_web_application()
