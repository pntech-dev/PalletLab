from pathlib import Path
from urllib.request import urlopen

from palletlab.desktop.web_host import WebApplicationApi, _StepAssetServer, _WebSettings, _frontend_content_type


def test_frontend_mime_types_do_not_depend_on_windows_registry(monkeypatch) -> None:
    monkeypatch.setattr("palletlab.desktop.web_host.mimetypes.guess_type", lambda _name: ("text/plain", None))
    assert _frontend_content_type(Path("index.html")) == "text/html"
    assert _frontend_content_type(Path("index.js")) == "text/javascript"
    assert _frontend_content_type(Path("module.MJS")) == "text/javascript"
    assert _frontend_content_type(Path("style.css")) == "text/css"
    assert _frontend_content_type(Path("other.bin")) == "text/plain"


def test_asset_server_forbids_webview_caching_of_frontend_and_step_files(tmp_path) -> None:
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    step = tmp_path / "model.step"
    step.write_text("ISO-10303-21;", encoding="utf-8")

    server = _StepAssetServer()
    base_url = server.set_frontend_root(root)
    step_url = server.register(step)
    try:
        with urlopen(base_url) as frontend:  # noqa: S310 - loopback URL built by the server under test
            assert frontend.headers["Cache-Control"] == "no-store"
        with urlopen(step_url) as served_step:  # noqa: S310 - loopback URL built by the server under test
            assert served_step.headers["Cache-Control"] == "no-store"
    finally:
        server._server.shutdown()
        server._server.server_close()


def test_web_application_api_reports_compatible_snapshot_version() -> None:
    status = WebApplicationApi().status()

    assert status["application"] == "PalletLab"
    assert status["snapshotVersion"] == 1


def test_restore_step_uses_import_service_and_reports_missing_path(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    source = str(tmp_path / "model.step")
    monkeypatch.setattr(api._step_imports, "start", lambda path: {"ok": True, "path": path})
    assert api.restore_step_model(source) == {"ok": True, "path": source}
    assert not api.restore_step_model("")["ok"]


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


def test_web_settings_persist_solidworks_options(tmp_path) -> None:
    path = tmp_path / "web_settings.json"
    options = {
        "partTemplate": r"C:\templates\part.prtdot",
        "assemblyTemplate": r"C:\templates\assembly.asmdot",
        "materialLibrary": r"C:\materials\solidworks materials.sldmat",
        "materialName": "Pine",
    }

    assert _WebSettings(path).save_solidworks_options(options) is True
    assert _WebSettings(path).solidworks_options() == options


def test_web_settings_persist_drawing_templates(tmp_path) -> None:
    path = tmp_path / "web_settings.json"
    settings = _WebSettings(path)

    assert settings.save_drawing_template("solidworks", r"C:\templates\drawing.drwdot") is True
    assert settings.save_drawing_template("kompas", r"C:\templates\drawing.cdt") is True
    assert _WebSettings(path).drawing_templates() == {
        "solidworks": r"C:\templates\drawing.drwdot",
        "kompas": r"C:\templates\drawing.cdt",
    }


def test_web_api_returns_drawing_template_path(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    template = tmp_path / "drawing.cdt"
    monkeypatch.setattr(api, "_choose_file", lambda mode: str(template) if mode == "kompas_drawing" else None)

    assert api.select_drawing_template("kompas") == {"ok": True, "path": str(template)}


def test_web_api_creates_drawings_from_a_native_folder_choice(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    project = {"project": "payload"}
    monkeypatch.setattr(api, "_choose_directory", lambda _title: str(tmp_path))
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.create_drawings",
        lambda _service, *args: {"ok": True, "args": args},
    )

    response = api.create_drawings(project, "kompas", "assembly", None)

    assert response == {"ok": True, "args": (project, "kompas", "assembly", str(tmp_path), None)}
