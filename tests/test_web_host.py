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


def test_web_api_returns_solidworks_template_paths(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    part = tmp_path / "part.prtdot"
    assembly = tmp_path / "assembly.asmdot"
    choices = iter((str(part), str(assembly)))
    monkeypatch.setattr(api, "_choose_file", lambda _mode: next(choices))

    response = api.select_solidworks_templates()

    assert response == {"ok": True, "partTemplate": str(part), "assemblyTemplate": str(assembly)}
