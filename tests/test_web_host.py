from palletlab.desktop.web_host import WebApplicationApi


def test_web_application_api_reports_compatible_snapshot_version() -> None:
    status = WebApplicationApi().status()

    assert status["application"] == "PalletLab"
    assert status["snapshotVersion"] == 1


def test_web_api_uses_a_native_folder_choice_for_kompas_export(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    project = {"project": "payload"}
    monkeypatch.setattr(api, "_choose_directory", lambda _title: str(tmp_path))
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.export_kompas",
        lambda _service, received_project, directory: {"ok": True, "project": received_project, "directory": directory},
    )

    response = api.export_kompas(project)

    assert response == {"ok": True, "project": project, "directory": str(tmp_path)}


def test_web_api_returns_one_solidworks_template_path(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    part = tmp_path / "part.prtdot"
    monkeypatch.setattr(api, "_choose_file", lambda mode: str(part) if mode == "solidworks_part" else None)

    response = api.select_solidworks_template("part")

    assert response == {"ok": True, "path": str(part)}


def test_web_api_rejects_an_unknown_solidworks_template_type() -> None:
    assert WebApplicationApi().select_solidworks_template("drawing") == {
        "ok": False,
        "error": "Некорректный тип шаблона SolidWorks.",
    }
