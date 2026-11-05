import json
from pathlib import Path

import numpy as np

from palletlab.application.step_import_service import (
    StepImportService,
    _cached_web_asset,
    _model_bearing_height,
    _model_pallet_layers,
    _viewport_transform,
    _write_model_asset,
)
from palletlab.core.models import DirectionInput


def test_step_import_rejects_non_step_files_without_starting_a_worker(tmp_path):
    source = tmp_path / "model.txt"
    source.write_text("not a STEP file", encoding="utf-8")

    response = StepImportService().start(source)

    assert response == {
        "ok": False,
        "error": "Выберите STEP-модель с расширением .step или .stp.",
    }


def test_step_import_uses_existing_web_asset_without_starting_a_worker(tmp_path, monkeypatch):
    source = tmp_path / "model.step"
    source.write_text("STEP", encoding="utf-8")
    asset = tmp_path / "model.bin"
    asset.write_bytes(b"PLSTEP01")
    monkeypatch.setattr("palletlab.application.step_import_service._cached_web_asset", lambda _path: asset)

    response = StepImportService().start(source)

    assert response["state"] == "completed"
    assert response["progress"] == 100
    assert response["label"] == "STEP-модель загружена из web-кэша."


def test_step_import_status_and_cancel_reject_unknown_operation_ids():
    service = StepImportService()

    assert service.status("missing") == {
        "ok": False,
        "error": "Импорт STEP-модели не найден.",
    }
    assert service.cancel("missing") == {
        "ok": False,
        "error": "Импорт STEP-модели не найден.",
    }


def test_step_asset_keeps_triangle_to_cad_face_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    class Mesh:
        faces = [3, 0, 1, 2]
        points = [(0, 0, 0), (100, 0, 0), (0, 200, 300)]
        cell_data = {"step_face_index": [7]}
        bounds = (0, 100, 0, 200, 0, 300)

    class Face:
        index = 7
        point = object()
        normal = object()

    class Edges:
        lines = [3, 0, 1, 2]
        points = [(0, 0, 0), (100, 0, 0), (0, 200, 300)]

    class Model:
        mesh, edges, faces = Mesh(), Edges(), (Face(),)
        source_path = tmp_path / "model.step"

    Model.source_path.write_text("STEP", encoding="utf-8")
    asset = _write_model_asset(Model())
    raw = Path(asset["path"]).read_bytes()
    header_length = int.from_bytes(raw[8:12], "little")
    header = json.loads(raw[12:12 + header_length])
    data_start = 12 + header_length + ((4 - (header_length % 4)) % 4)

    def values(name, dtype):
        item = header["buffers"][name]
        return np.frombuffer(raw, dtype=dtype, count=item["byteLength"] // 4, offset=data_start + item["offset"]).tolist()

    assert raw[:8] == b"PLSTEP01"
    assert values("positions", "<f4") == [
        0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 200.0, 300.0,
    ]
    assert values("indices", "<u4") == [0, 1, 2]
    assert values("triangleFaceIds", "<i4") == [7]
    assert values("selectableFaceIds", "<i4") == [7]
    assert values("edgePoints", "<f4") == [
        0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 200.0, 300.0,
    ]
    assert values("edgeCells", "<u4") == [3, 0, 1, 2]
    assert header["bounds"] == [0.0, 100.0, 0.0, 200.0, 0.0, 300.0]
    assert _cached_web_asset(Model.source_path) == Path(asset["path"])


def test_step_pallet_layers_keep_every_machine_support_on_one_bearing_plane():
    length = DirectionInput(70, 50, (1000,), 200, 200, 100, 100)
    width = DirectionInput(70, 50, (500,), 200, 200, 100, 100)

    layers, sections = _model_pallet_layers(length, width)

    assert [layer.layer_id for layer in layers] == ["length", "width", "layer-1"]
    assert [layer.axis for layer in layers] == ["length", "width", "length"]
    assert sections == {}


def test_model_bearing_height_rejects_an_uneven_support_layer():
    class Beam:
        def __init__(self, z, height):
            self.layer_id = "layer-1"
            self.z = z
            self.size_z = height

    class Result:
        beams_3d = (Beam(175, 70), Beam(152.5, 25))

    with np.testing.assert_raises_regex(Exception, "разной высоте"):
        _model_bearing_height(Result())


def test_model_bearing_height_uses_the_calculated_top_of_support_beams():
    class Beam:
        layer_id = "layer-1"
        z = 175
        size_z = 70

    class Result:
        beams_3d = (Beam(), Beam())

    assert _model_bearing_height(Result()) == 210


def test_viewport_transform_preserves_the_existing_xzy_axis_mapping():
    placement = np.eye(4)
    placement[:3, 3] = (10, 20, 30)

    transform = _viewport_transform(placement)

    assert transform[12:] == [0.01, 0.03, 0.02, 1.0]
