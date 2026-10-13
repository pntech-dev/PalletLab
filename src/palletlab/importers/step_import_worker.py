"""Isolated STEP import entry point, used by the desktop UI's QProcess."""

from __future__ import annotations

import json
import sys


def _emit(kind: str, **payload) -> None:
    # QProcess may inherit a legacy Windows code page.  ASCII JSON keeps the
    # progress protocol unambiguous; json.loads restores Russian text in UI.
    print(json.dumps({"kind": kind, **payload}, ensure_ascii=True), flush=True)


def main(path: str) -> int:
    try:
        from palletlab.importers.step_model import load_cached_step_model, load_step_model

        def progress(value: int, label: str) -> None:
            _emit("progress", value=value, label=label)

        load_step_model(path, progress)
        if load_cached_step_model(path) is None:
            raise RuntimeError("Не удалось сохранить кэш импортированной модели.")
    except Exception as exc:
        _emit("error", message=str(exc))
        return 1
    _emit("done")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Expected one STEP file path.")
    raise SystemExit(main(sys.argv[1]))
