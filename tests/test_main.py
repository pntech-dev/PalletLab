"""Entrypoint behaviour that must also work in a frozen executable."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest


def test_smoke_test_mode_imports_the_3d_viewport(monkeypatch, tmp_path):
    main_path = Path(__file__).parents[1] / "src" / "main.py"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(main_path), "--smoke-test"])

    with pytest.raises(SystemExit) as result:
        runpy.run_path(main_path, run_name="__main__")

    assert result.value.code == 0


def test_web_smoke_test_validates_the_built_frontend(monkeypatch, tmp_path):
    main_path = Path(__file__).parents[1] / "src" / "web_main.py"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(main_path), "--smoke-test"])

    with pytest.raises(SystemExit) as result:
        runpy.run_path(main_path, run_name="__main__")

    assert result.value.code == 0


def test_web_entrypoint_preserves_the_step_worker_mode(monkeypatch, tmp_path) -> None:
    main_path = Path(__file__).parents[1] / "src" / "web_main.py"
    imported = {}

    def fake_main(path: str) -> int:
        imported["path"] = path
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(main_path), "--step-import", "model.step"])
    monkeypatch.setattr("palletlab.importers.step_import_worker.main", fake_main)

    with pytest.raises(SystemExit) as result:
        runpy.run_path(main_path, run_name="__main__")

    assert result.value.code == 0
    assert imported == {"path": "model.step"}
