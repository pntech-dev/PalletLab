import base64

import numpy as np

from palletlab.application.step_import_service import (
    StepImportService,
    _model_pallet_layers,
    _snapshot_from_cached_model,
    _viewport_transform,
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


def test_step_snapshot_keeps_triangle_to_cad_face_mapping():
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
        mesh = Mesh()
        edges = Edges()
        faces = (Face(),)

    snapshot = _snapshot_from_cached_model(Model())

    assert snapshot["encoding"] == "typed-buffer-v1"
    assert np.frombuffer(base64.b64decode(snapshot["positions"]), dtype="<f4").tolist() == [
        0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 200.0, 300.0,
    ]
    assert np.frombuffer(base64.b64decode(snapshot["indices"]), dtype="<u4").tolist() == [0, 1, 2]
    assert np.frombuffer(base64.b64decode(snapshot["triangleFaceIds"]), dtype="<i4").tolist() == [7]
    assert snapshot["selectableFaceIds"] == [7]
    assert np.frombuffer(base64.b64decode(snapshot["edgePoints"]), dtype="<f4").tolist() == [
        0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 200.0, 300.0,
    ]
    assert np.frombuffer(base64.b64decode(snapshot["edgeCells"]), dtype="<u4").tolist() == [3, 0, 1, 2]
    assert snapshot["bounds"] == [0.0, 100.0, 0.0, 200.0, 0.0, 300.0]


def test_step_pallet_layers_match_the_desktop_three_layer_construction():
    length = DirectionInput(70, 50, (1000,), 200, 200, 100, 100)
    width = DirectionInput(70, 50, (500,), 200, 200, 100, 100)

    layers, sections = _model_pallet_layers(length, width)

    assert [layer.layer_id for layer in layers] == ["length", "width", "layer-1"]
    assert [layer.axis for layer in layers] == ["length", "width", "length"]
    assert sections[("layer-1", 0)].height == 25
    assert sections[("layer-1", 0)].width == 100


def test_viewport_transform_preserves_the_existing_xzy_axis_mapping():
    placement = np.eye(4)
    placement[:3, 3] = (10, 20, 30)

    transform = _viewport_transform(placement)

    assert transform[12:] == [0.01, 0.03, 0.02, 1.0]
