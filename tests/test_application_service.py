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
    assert response["snapshot"]["project"]["pallet"]["length"]["rounding_step"] == 50
    assert response["snapshot"]["project"]["pallet"]["length"]["round_pallet_size"] is True


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


def test_changing_layer_section_preserves_manual_and_individually_edited_beams() -> None:
    service = ApplicationService()
    project = service.default_project()
    changed = service.change_beam_sections(project, {"width": [1]}, {"height": 90, "width": 60})
    assert changed["ok"], changed
    created = service.add_manual_beam(
        changed["snapshot"]["project"],
        [{"layerId": "length", "layerIndex": 1}, {"layerId": "length", "layerIndex": 2}],
        {"distance": 100, "section": {"height": 70, "width": 50}},
    )
    assert created["ok"], created
    project = created["snapshot"]["project"]
    layer = next(layer for layer in project["pallet"]["layers"] if layer["id"] == "width")
    layer["direction"].update({"beam_height": 100, "beam_width": 80})
    result = service.calculate(project)
    assert result["ok"], result
    beams = result["snapshot"]["pallet"]["beams"]
    edited = next(b for b in beams if b["layerId"] == "width" and b["layerIndex"] == 1)
    regular = next(b for b in beams if b["layerId"] == "width" and b["layerIndex"] == 2)
    manual = next(b for b in beams if b["layerId"] == "manual-1")
    def section(beam):
        return (beam["size"][1 if beam["orientation"] == "length" else 0], beam["size"][2])

    assert section(edited) == (60, 90)
    assert section(regular) == (80, 100)
    assert section(manual) == (50, 70)


def test_add_centered_manual_beam_round_trips_and_uses_base_dimension() -> None:
    service = ApplicationService()
    project = service.default_project()
    result = service.add_manual_beam(project,
        [{"layerId": "length", "layerIndex": 0}, {"layerId": "length", "layerIndex": 1}],
        {"distance": 0, "section": {"height": 70, "width": 50},
         "reference": {"layerId": "width", "layerIndex": 0}, "referenceFace": "y_max",
         "secondReference": {"layerId": "width", "layerIndex": 1}, "secondReferenceFace": "y_min"})
    assert result["ok"], result
    saved = result["snapshot"]["project"]
    assert saved["pallet"]["manual_beams"][0]["second_reference"] == ["width", 1]
    recalculated = service.calculate(saved)
    assert recalculated["ok"]
    beam = next(item for item in recalculated["snapshot"]["pallet"]["beams"] if item["layerId"] == "manual-1")
    dimension = next(item for item in recalculated["snapshot"]["pallet"]["dimensions"] if item["layerId"] == "manual-1")
    assert dimension["start"][1] == 0
    assert dimension["value"] == abs(beam["center"][1] - beam["size"][1] / 2)
    assert dimension["editable"] is False


def test_add_manual_beam_keeps_the_first_viewport_point() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())

    response = service.add_manual_beam(
        calculated["snapshot"]["project"],
        [{"layerId": "length", "layerIndex": 1}, {"layerId": "length", "layerIndex": 2}],
        {"distance": 100, "section": {"height": 70, "width": 50}, "startPoint": [100, 200, 70]},
    )

    assert response["ok"] is True
    assert response["snapshot"]["project"]["pallet"]["manual_beams"][0]["start_point"] == [100.0, 200.0, 70.0]


def test_add_manual_beam_rejects_supports_from_different_layers() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())

    response = service.add_manual_beam(
        calculated["snapshot"]["project"],
        [{"layerId": "length", "layerIndex": 1}, {"layerId": "layer-1", "layerIndex": 2}],
        {"distance": 100, "section": {"height": 70, "width": 50}},
    )

    assert response["ok"] is False


def test_manual_beam_can_support_beam_in_next_layer_after_reload() -> None:
    service = ApplicationService()
    project = service.default_project()
    options = {"distance": 100, "section": {"height": 70, "width": 50}}
    first = service.add_manual_beam(project, [
        {"layerId": "length", "layerIndex": 1},
        {"layerId": "length", "layerIndex": 2},
    ], options)
    assert first["ok"] is True
    manual = next(beam for beam in first["snapshot"]["pallet"]["beams"] if beam["layerId"] == "manual-1")
    assert manual["physicalLayerId"] == "width"
    second = service.add_manual_beam(first["snapshot"]["project"], [
        {"layerId": "manual-1", "layerIndex": 0},
        {"layerId": "width", "layerIndex": 1},
    ], options)
    assert second["ok"] is True
    restored = service.calculate(second["snapshot"]["project"])
    assert restored["ok"] is True
    assert next(beam for beam in restored["snapshot"]["pallet"]["beams"] if beam["layerId"] == "manual-2")["physicalLayerId"] == "layer-1"


def test_add_manual_beam_rejects_a_manual_beam_as_its_layer() -> None:
    service = ApplicationService()
    calculated = service.calculate(service.default_project())
    created = service.add_manual_beam(
        calculated["snapshot"]["project"],
        [{"layerId": "length", "layerIndex": 1}, {"layerId": "length", "layerIndex": 2}],
        {"distance": 100, "section": {"height": 70, "width": 50}},
    )
    manual = next(beam for beam in created["snapshot"]["pallet"]["beams"] if beam["layerId"].startswith("manual-"))

    response = service.add_manual_beam(
        created["snapshot"]["project"],
        [{"layerId": manual["layerId"], "layerIndex": 0}, {"layerId": manual["layerId"], "layerIndex": 0}],
        {"distance": 100, "section": {"height": 70, "width": 50}},
    )

    assert response["ok"] is False
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


def test_kompas_export_recalculates_the_project_before_calling_the_exporter(tmp_path, monkeypatch) -> None:
    service = ApplicationService()
    output = tmp_path / "pallet"
    captured = {}

    def export(result, parent, material_id):
        captured.update(result=result, parent=parent, material_id=material_id)
        return output

    monkeypatch.setattr("palletlab.application.service.export_kompas_pallet", export)

    response = service.export_kompas(service.default_project(), str(tmp_path))

    assert response == {"ok": True, "output": str(output)}
    assert captured["parent"] == tmp_path
    assert captured["material_id"] == "pine"
    assert captured["result"].beams_3d


def test_solidworks_export_passes_explicit_web_resources(tmp_path, monkeypatch) -> None:
    service = ApplicationService()
    part = tmp_path / "part.prtdot"
    assembly = tmp_path / "assembly.asmdot"
    library = tmp_path / "materials.sldmat"
    for path in (part, assembly, library):
        path.touch()
    output = tmp_path / "pallet"
    captured = {}

    def export(result, parent, templates, material_id, material_library, material_name):
        captured.update(
            result=result,
            parent=parent,
            templates=templates,
            material_id=material_id,
            material_library=material_library,
            material_name=material_name,
        )
        return output

    monkeypatch.setattr("palletlab.application.service.export_solidworks_pallet", export)

    response = service.export_solidworks(
        service.default_project(),
        str(tmp_path),
        {
            "partTemplate": str(part),
            "assemblyTemplate": str(assembly),
            "materialLibrary": str(library),
            "materialName": "Pine",
        },
    )

    assert response == {"ok": True, "output": str(output)}
    assert captured["templates"] == (str(part), str(assembly))
    assert captured["material_library"] == str(library)
    assert captured["material_name"] == "Pine"
    assert captured["result"].beams_3d


def test_solidworks_export_rejects_missing_web_resources(tmp_path) -> None:
    response = ApplicationService().export_solidworks(
        ApplicationService().default_project(),
        str(tmp_path),
        {},
    )

    assert response == {
        "ok": False,
        "error": "Выберите шаблоны и материал SolidWorks перед экспортом.",
    }


def test_create_solidworks_drawings_uses_the_current_calculation(tmp_path, monkeypatch) -> None:
    service = ApplicationService()
    output = tmp_path / "Drawings"
    captured = {}

    def create(directory, scope, template, result):
        captured.update(directory=directory, scope=scope, template=template, result=result)
        return output

    monkeypatch.setattr("palletlab.application.service.create_solidworks_drawings", create)

    response = service.create_drawings(
        service.default_project(), "solidworks", "parts_and_assembly", str(tmp_path), r"C:\templates\drawing.drwdot"
    )

    assert response == {"ok": True, "output": str(output)}
    assert captured["directory"] == tmp_path
    assert captured["scope"].value == "parts_and_assembly"
    assert captured["template"] == r"C:\templates\drawing.drwdot"
    assert captured["result"].beams_3d


def test_create_drawings_rejects_invalid_web_options(tmp_path) -> None:
    response = ApplicationService().create_drawings(
        ApplicationService().default_project(), "unknown", "assembly", str(tmp_path), None
    )

    assert response == {"ok": False, "error": "Выберите CAD-систему для создания чертежей."}


def test_create_drawings_requests_a_template_when_the_cad_default_is_missing(tmp_path, monkeypatch) -> None:
    from palletlab.exporters.drawings import DrawingTemplateError

    monkeypatch.setattr(
        "palletlab.application.service.create_solidworks_drawings",
        lambda *_args: (_ for _ in ()).throw(DrawingTemplateError("Не найден шаблон.")),
    )

    response = ApplicationService().create_drawings(
        ApplicationService().default_project(), "solidworks", "assembly", str(tmp_path), None
    )

    assert response == {"ok": False, "error": "Не найден шаблон.", "needsTemplate": True}


def test_locked_layers_reject_viewport_edits_and_allow_other_layers() -> None:
    service = ApplicationService()
    initial = service.calculate(service.default_project())["snapshot"]
    project = initial["project"]
    project["view"]["locked_layer_ids"] = ["length"]
    selection = {"length": [1]}
    assert not service.delete_beams(project, selection)["ok"]
    assert not service.change_beam_sections(project, selection, {"height": 100, "width": 75})["ok"]
    dimension = next(item for item in initial["pallet"]["dimensions"] if item["editable"])
    project["view"]["locked_layer_ids"] = [dimension["layerId"]]
    assert not service.change_beam_distance(project, {"layerId": dimension["layerId"], "beamIndex": dimension["index"]}, dimension["value"] + 100)["ok"]
    project["view"]["locked_layer_ids"] = ["length"]
    slot = next(item["slot"] for item in initial["pallet"]["insertionMarkers"] if item["slot"]["layerId"] == "length")
    assert not service.insert_beam(project, slot, slot["suggestedClearGap"])["ok"]
    assert service.change_beam_sections(project, {"width": [1]}, {"height": 100, "width": 75})["ok"]


def test_locked_physical_layer_rejects_manual_beam_insertion_and_edit() -> None:
    service = ApplicationService()
    project = service.default_project()
    supports = [{"layerId": "length", "layerIndex": 1}, {"layerId": "length", "layerIndex": 2}]
    options = {"distance": 100, "section": {"height": 70, "width": 50}}
    project["view"]["locked_layer_ids"] = ["width"]
    assert not service.add_manual_beam(project, supports, options)["ok"]
    project["view"]["locked_layer_ids"] = []
    created = service.add_manual_beam(project, supports, options)["snapshot"]
    beam = next(item for item in created["pallet"]["beams"] if item["layerId"].startswith("manual-"))
    created["project"]["view"]["locked_layer_ids"] = ["width"]
    assert not service.change_beam_sections(created["project"], {beam["layerId"]: [beam["layerIndex"]]}, {"height": 100, "width": 75})["ok"]


def test_duplicate_copies_grid_sections_visibility_and_first_layer_alignment() -> None:
    service = ApplicationService()
    project = service.default_project()
    changed = service.change_beam_sections(project, {"length": [1]}, {"height": 40, "width": 45})
    assert changed["ok"]
    project = changed["snapshot"]["project"]
    project["view"]["hidden_layer_ids"] = ["length"]
    project["view"]["locked_layer_ids"] = ["length"]
    response = service.duplicate_layer(project, "length")
    assert response["ok"], response
    snapshot = response["snapshot"]
    new_id = response["layerId"]
    layers = snapshot["project"]["pallet"]["layers"]
    assert [layer["id"] for layer in layers][:2] == ["length", new_id]
    assert layers[0]["direction"] == layers[1]["direction"]
    assert new_id in snapshot["project"]["view"]["hidden_layer_ids"]
    assert new_id in snapshot["project"]["view"]["locked_layer_ids"]
    beams = snapshot["pallet"]["beams"]
    source = [beam for beam in beams if beam["layerId"] == "length"]
    copied = [beam for beam in beams if beam["layerId"] == new_id]
    assert len(source) == len(copied)
    delta = snapshot["pallet"]["layers"][1]["baseZ"]
    for original, duplicate in zip(source, copied):
        assert original["size"] == duplicate["size"]
        assert original["center"][:2] == duplicate["center"][:2]
        assert duplicate["center"][2] == original["center"][2] + delta
    assert service.calculate(snapshot["project"])["ok"]


def test_duplicate_preserves_manual_beams_in_both_original_and_copy() -> None:
    service = ApplicationService()
    project = service.default_project()
    supports = [{"layerId": "length", "layerIndex": 1}, {"layerId": "length", "layerIndex": 2}]
    response = service.add_manual_beam(project, supports, {"distance": 100, "section": {"height": 70, "width": 50}})
    assert response["ok"], response
    before = response["snapshot"]
    original = next(beam for beam in before["pallet"]["beams"] if beam["layerId"].startswith("manual-"))
    assert original["physicalLayerId"] == "width"
    response = service.duplicate_layer(before["project"], "width")
    assert response["ok"], response
    after = response["snapshot"]
    manual = [beam for beam in after["pallet"]["beams"] if beam["layerId"].startswith("manual-")]
    assert len(manual) == 2
    assert manual[0]["physicalLayerId"] == "width"
    assert manual[1]["physicalLayerId"] == response["layerId"]
    assert manual[0]["center"] == original["center"]
    assert manual[0]["size"] == manual[1]["size"] == original["size"]
    assert manual[0]["center"][:2] == manual[1]["center"][:2]
    assert manual[1]["center"][2] > manual[0]["center"][2]
    reloaded = service.calculate(after["project"])
    assert reloaded["ok"]
    assert [beam for beam in reloaded["snapshot"]["pallet"]["beams"] if beam["layerId"].startswith("manual-")] == manual
    edited = service.change_beam_sections(after["project"], {manual[1]["layerId"]: [0]}, {"height": 90, "width": 60})
    assert edited["ok"], edited
    updated = [beam for beam in edited["snapshot"]["pallet"]["beams"] if beam["layerId"].startswith("manual-")]
    assert updated[0]["size"] == manual[0]["size"]
    assert updated[1]["size"] != manual[1]["size"]


def test_duplicate_below_manual_beam_keeps_it_in_original_layer() -> None:
    service = ApplicationService()
    supports = [{"layerId": "length", "layerIndex": 1}, {"layerId": "length", "layerIndex": 2}]
    created = service.add_manual_beam(service.default_project(), supports, {"distance": 100, "section": {"height": 70, "width": 50}})
    response = service.duplicate_layer(created["snapshot"]["project"], "length")
    assert response["ok"], response
    manual = next(beam for beam in response["snapshot"]["pallet"]["beams"] if beam["layerId"].startswith("manual-"))
    assert manual["physicalLayerId"] == "width"
    assert manual["center"][2] > next(beam for beam in created["snapshot"]["pallet"]["beams"] if beam["layerId"] == manual["layerId"])["center"][2]


def test_duplicate_preserves_inserted_and_deleted_beams_and_can_be_repeated() -> None:
    service = ApplicationService()
    snapshot = service.calculate(service.default_project())["snapshot"]
    slot = next(item["slot"] for item in snapshot["pallet"]["insertionMarkers"] if item["slot"]["layerId"] == "length")
    inserted = service.insert_beam(snapshot["project"], slot, slot["suggestedClearGap"])
    assert inserted["ok"], inserted
    deleted = service.delete_beams(inserted["snapshot"]["project"], {"length": [1]})
    assert deleted["ok"], deleted
    copied = service.duplicate_layer(deleted["snapshot"]["project"], "length")
    assert copied["ok"], copied
    beams = copied["snapshot"]["pallet"]["beams"]
    source = [beam for beam in beams if beam["layerId"] == "length"]
    duplicate = [beam for beam in beams if beam["layerId"] == copied["layerId"]]
    assert [(b["layerIndex"], b["size"], b["center"][:2]) for b in source] == [
        (b["layerIndex"], b["size"], b["center"][:2]) for b in duplicate]
    again = service.duplicate_layer(copied["snapshot"]["project"], copied["layerId"])
    assert again["ok"], again
    assert again["layerId"] != copied["layerId"]


def test_duplicate_legacy_two_layer_project_switches_to_layer_stack() -> None:
    service = ApplicationService()
    state = ProjectState(
        length_input=DirectionInput(100, 80, (700,), 100, 100, 50, 50),
        width_input=DirectionInput(80, 60, (500,), 80, 80, 40, 40),
    )
    result = service.duplicate_layer(project_to_dict(state), "length")
    assert result["ok"], result
    assert len(result["snapshot"]["pallet"]["layers"]) == 3


def test_duplicate_rebinds_manual_beam_references_to_copied_layer() -> None:
    service = ApplicationService()
    created = service.add_manual_beam(service.default_project(),
        [{"layerId": "length", "layerIndex": 0}, {"layerId": "length", "layerIndex": 1}],
        {"distance": 0, "section": {"height": 70, "width": 50},
         "reference": {"layerId": "width", "layerIndex": 0}, "referenceFace": "y_max",
         "secondReference": {"layerId": "width", "layerIndex": 1}, "secondReferenceFace": "y_min"})
    assert created["ok"], created
    copied = service.duplicate_layer(created["snapshot"]["project"], "width")
    assert copied["ok"], copied
    manuals = copied["snapshot"]["project"]["pallet"]["manual_beams"]
    assert manuals[0]["reference"][0] == "width"
    assert manuals[1]["reference"][0] == copied["layerId"]
    assert manuals[1]["second_reference"][0] == copied["layerId"]
