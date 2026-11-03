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
