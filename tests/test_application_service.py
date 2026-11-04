from palletlab.application.service import ApplicationService
from palletlab.core.models import DirectionInput
from palletlab.core.persistence import project_to_dict
from palletlab.core.project_state import ProjectState


def test_calculate_returns_a_fresh_web_snapshot() -> None:
    state = ProjectState(
        length_input=DirectionInput(100, 80, (700,), 100, 100, 50, 50),
        width_input=DirectionInput(80, 60, (500,), 80, 80, 40, 40),
    )

    response = ApplicationService().calculate(project_to_dict(state))

    assert response["ok"] is True
    assert response["snapshot"]["pallet"]["beams"]


def test_calculate_returns_a_user_facing_validation_error() -> None:
    response = ApplicationService().calculate({"format_version": 999})

    assert response["ok"] is False
    assert isinstance(response["error"], str)


def test_default_project_matches_the_current_multilayer_starting_point() -> None:
    service = ApplicationService()

    response = service.calculate(service.default_project())

    assert response["ok"] is True
    assert response["snapshot"]["project"]["pallet"]["multi_layer_mode"] is True
    assert len(response["snapshot"]["pallet"]["layers"]) == 3


def test_delete_beams_uses_rendered_layer_indices_and_returns_updated_snapshot() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())
    pallet = calculated["snapshot"]["pallet"]
    beam = next(item for item in pallet["beams"] if item["layerId"] == "length" and item["layerIndex"] == 1)

    response = service.delete_beams(
        calculated["snapshot"]["project"],
        {beam["layerId"]: [beam["layerIndex"]]},
    )

    assert response["ok"] is True
    updated_pallet = response["snapshot"]["pallet"]
    assert len(updated_pallet["beams"]) == len(pallet["beams"]) - 1
    assert sum(item["layerId"] == "length" for item in updated_pallet["beams"]) == (
        sum(item["layerId"] == "length" for item in pallet["beams"]) - 1
    )


def test_delete_beams_rejects_an_empty_selection() -> None:
    response = ApplicationService().delete_beams(ApplicationService().default_project(), {})

    assert response == {"ok": False, "error": "Выберите хотя бы один брус для удаления."}


def test_delete_an_edge_beam_keeps_the_viewport_snapshot_available() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())

    response = service.delete_beams(calculated["snapshot"]["project"], {"length": [0]})

    assert response["ok"] is True
    assert response["snapshot"]["pallet"] is not None


def test_change_beam_sections_updates_selected_beam_geometry() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())
    pallet = calculated["snapshot"]["pallet"]
    beam = next(item for item in pallet["beams"] if item["layerId"] == "length" and item["layerIndex"] == 1)

    response = service.change_beam_sections(
        calculated["snapshot"]["project"],
        {beam["layerId"]: [beam["layerIndex"]]},
        {"height": 100, "width": 75},
    )

    assert response["ok"] is True
    updated = next(
        item
        for item in response["snapshot"]["pallet"]["beams"]
        if item["layerId"] == beam["layerId"] and item["layerIndex"] == beam["layerIndex"]
    )
    assert updated["size"] == [75.0, beam["size"][1], 100.0]


def test_change_beam_distance_updates_the_selected_dimension() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())
    dimension = next(item for item in calculated["snapshot"]["pallet"]["dimensions"] if item["editable"])

    response = service.change_beam_distance(
        calculated["snapshot"]["project"],
        {"layerId": dimension["layerId"], "beamIndex": dimension["index"]},
        dimension["value"] + 100,
    )

    assert response["ok"] is True
    updated = next(
        item for item in response["snapshot"]["pallet"]["dimensions"]
        if item["layerId"] == dimension["layerId"] and item["index"] == dimension["index"]
    )
    assert updated["value"] == dimension["value"] + 100


def test_change_beam_distance_rejects_invalid_viewport_payloads() -> None:
    service = ApplicationService()

    assert service.change_beam_distance(service.default_project(), {}, 100) == {
        "ok": False,
        "error": "Некорректная размерная линия.",
    }


def test_insert_beam_uses_a_snapshot_insertion_slot() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())
    slot = calculated["snapshot"]["pallet"]["insertionMarkers"][0]["slot"]

    response = service.insert_beam(calculated["snapshot"]["project"], slot, slot["suggestedClearGap"])

    assert response["ok"] is True
    assert len(response["snapshot"]["pallet"]["beams"]) == len(calculated["snapshot"]["pallet"]["beams"]) + 1


def test_add_manual_beam_uses_two_viewport_supports() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())
    supports = [
        {"layerId": "length", "layerIndex": 1},
        {"layerId": "length", "layerIndex": 2},
    ]

    response = service.add_manual_beam(
        calculated["snapshot"]["project"], supports,
        {"distance": 100, "section": {"height": 70, "width": 50}},
    )

    assert response["ok"] is True
    assert any(beam["layerId"].startswith("manual-") for beam in response["snapshot"]["pallet"]["beams"])
    assert service.change_beam_distance(service.default_project(), {"layerId": "length", "beamIndex": 1}, float("inf")) == {
        "ok": False,
        "error": "Расстояние должно быть конечным числом.",
    }


def test_materials_expose_stable_ids_and_names() -> None:
    assert ApplicationService().materials() == [
        {"id": "pine", "name": "Сосна"},
        {"id": "spruce", "name": "Ель"},
    ]


def test_save_and_load_preserve_a_valid_project(tmp_path) -> None:
    service = ApplicationService()
    path = tmp_path / "project.palletlab.json"

    saved = service.save(service.default_project(), str(path))
    loaded = service.load(str(path))

    assert saved == {"ok": True}
    assert loaded["ok"] is True
    assert loaded["project"]["pallet"]["material_id"] == "pine"
