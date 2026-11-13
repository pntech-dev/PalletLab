import json
from pathlib import Path
from urllib.request import urlopen

import pytest

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
        lambda _service, received_project, directory, include_assembly: {
            "ok": True, "project": received_project, "directory": directory, "include_assembly": include_assembly,
        },
    )

    response = api.export_kompas(project)

    assert response == {
        "ok": True, "project": project, "directory": str(tmp_path), "include_assembly": True,
    }


def test_web_api_selects_export_directory(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    monkeypatch.setattr(api, "_choose_directory", lambda _title: str(tmp_path))

    assert api.choose_export_directory() == {"ok": True, "path": str(tmp_path)}


def test_web_api_uses_the_export_directory_from_the_modal(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    project = {"project": "payload"}
    monkeypatch.setattr(api, "_choose_directory", lambda _title: pytest.fail("unexpected directory dialog"))
    received = []
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.export_kompas",
        lambda _service, received_project, directory, include_assembly: received.append(
            (received_project, directory, include_assembly)
        ) or {"ok": True},
    )

    response = api.export_kompas(project, False, str(tmp_path))

    assert response == {"ok": True}
    assert received == [(project, str(tmp_path), False)]


def test_web_api_passes_pallet_model_selection_to_kompas_export(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    monkeypatch.setattr(api, "_choose_directory", lambda _title: str(tmp_path))
    received = []
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.export_kompas",
        lambda _service, _project, _directory, include_assembly: received.append(include_assembly) or {"ok": True},
    )

    response = api.export_kompas({"project": "payload"}, include_assembly=False)

    assert response == {"ok": True}
    assert received == [False]


def test_web_api_passes_pallet_model_selection_to_solidworks_export(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    options = {"partTemplate": "part.prtdot"}
    monkeypatch.setattr(api, "_choose_directory", lambda _title: str(tmp_path))
    received = []
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.export_solidworks",
        lambda _service, _project, _directory, _options, include_assembly: (
            received.append(include_assembly) or {"ok": True}
        ),
    )

    response = api.export_solidworks({"project": "payload"}, options, include_assembly=False)

    assert response == {"ok": True}
    assert received == [False]


def test_web_api_uses_the_modal_directory_for_solidworks(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    project = {"project": "payload"}
    options = {"partTemplate": "part.prtdot"}
    monkeypatch.setattr(api, "_choose_directory", lambda _title: pytest.fail("unexpected directory dialog"))
    received = []
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.export_solidworks",
        lambda _service, received_project, directory, received_options, include_assembly: received.append(
            (received_project, directory, received_options, include_assembly)
        ) or {"ok": True},
    )

    response = api.export_solidworks(project, options, False, str(tmp_path))

    assert response == {"ok": True}
    assert received == [(project, str(tmp_path), options, False)]


def test_web_api_returns_one_solidworks_template_path(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    part = tmp_path / "part.prtdot"
    monkeypatch.setattr(api, "_choose_file", lambda mode: str(part) if mode == "solidworks_part" else None)

    response = api.select_solidworks_template("part")

    assert response == {"ok": True, "path": str(part)}


def test_web_api_returns_solidworks_drawing_template_path(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    drawing = tmp_path / "drawing.drwdot"
    monkeypatch.setattr(api, "_choose_file", lambda mode: str(drawing) if mode == "solidworks_drawing" else None)

    assert api.select_solidworks_template("drawing") == {"ok": True, "path": str(drawing)}


def test_web_api_rejects_an_unknown_solidworks_template_type() -> None:
    assert WebApplicationApi().select_solidworks_template("invalid") == {
        "ok": False,
        "error": "Некорректный тип шаблона SolidWorks.",
    }


def test_web_settings_persist_solidworks_options(tmp_path) -> None:
    path = tmp_path / "web_settings.json"
    options = {
        "partTemplate": r"C:\templates\part.prtdot",
        "assemblyTemplate": r"C:\templates\assembly.asmdot",
        "drawingTemplate": r"C:\templates\drawing.drwdot",
        "materialLibrary": r"C:\materials\solidworks materials.sldmat",
        "materialName": "Pine",
    }

    assert _WebSettings(path).save_solidworks_options(options) is True
    assert _WebSettings(path).solidworks_options() == options


def test_web_settings_migrate_legacy_solidworks_drawing_template(tmp_path) -> None:
    path = tmp_path / "web_settings.json"
    path.write_text(json.dumps({
        "solidworks": {
            "partTemplate": "part.prtdot",
            "assemblyTemplate": "assembly.asmdot",
            "materialLibrary": "materials.sldmat",
            "materialName": "Pine",
        },
        "drawingTemplates": {"solidworks": "drawing.drwdot"},
    }), encoding="utf-8")

    assert _WebSettings(path).solidworks_options() == {
        "partTemplate": "part.prtdot",
        "assemblyTemplate": "assembly.asmdot",
        "drawingTemplate": "drawing.drwdot",
        "materialLibrary": "materials.sldmat",
        "materialName": "Pine",
    }


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

    response = api.create_drawings(project, "kompas", "assembly", "legacy-template.cdt")

    assert response == {"ok": True, "args": (project, "kompas", "assembly", str(tmp_path), None)}


def test_web_api_creates_drawings_in_the_just_exported_folder(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    project = {"project": "payload"}
    choose_directory_calls = []
    monkeypatch.setattr(api, "_choose_directory", lambda title: choose_directory_calls.append(title))
    received = []
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.create_drawings",
        lambda _service, *args: received.append(args) or {"ok": True},
    )

    response = api.create_drawings(project, "kompas", "parts", None, str(tmp_path))

    assert response == {"ok": True}
    assert received == [(project, "kompas", "parts", str(tmp_path), None)]
    assert choose_directory_calls == []


def test_web_api_uses_saved_solidworks_drawing_template(monkeypatch, tmp_path) -> None:
    api = WebApplicationApi()
    options = {
        "partTemplate": "part.prtdot",
        "assemblyTemplate": "assembly.asmdot",
        "drawingTemplate": "drawing.drwdot",
        "materialLibrary": "materials.sldmat",
        "materialName": "Pine",
    }
    assert api._settings.save_solidworks_options(options)
    monkeypatch.setattr(api, "_choose_directory", lambda _title: str(tmp_path))
    received = []
    monkeypatch.setattr(
        "palletlab.desktop.web_host.ApplicationService.create_drawings",
        lambda _service, *args: received.append(args) or {"ok": True},
    )

    response = api.create_drawings({"project": "payload"}, "solidworks", "assembly", None)

    assert response == {"ok": True}
    assert received == [({"project": "payload"}, "solidworks", "assembly", str(tmp_path), "drawing.drwdot")]


def test_application_settings_persist_and_do_not_replace_cad_settings(tmp_path) -> None:
    store = _WebSettings(tmp_path / "settings.json")
    assert store.save_drawing_template("kompas", "drawing.cdt")
    settings = store.application_settings()
    settings.update({"rounding": "5", "autosaveEnabled": False, "autosaveMinutes": 10,
                     "showDimensions": False, "showGrid": False, "camera": "top", "checkUpdates": False})
    assert store.save_application_settings(settings)
    reloaded = _WebSettings(tmp_path / "settings.json")
    assert reloaded.application_settings() == settings
    assert reloaded.drawing_templates() == {"kompas": "drawing.cdt"}
    assert not store.save_application_settings({**settings, "autosaveMinutes": 0})
    assert not store.save_application_settings({**settings, "showGrid": "false"})
    assert store.application_settings() == settings


def test_web_autosave_survives_settings_instances_and_is_clearable(tmp_path) -> None:
    from palletlab.application.service import ApplicationService

    path = tmp_path / "settings.json"
    project = ApplicationService().default_project()
    store = _WebSettings(path)
    assert store.save_recovery_project(project)
    assert _WebSettings(path).recovery_project() == project
    assert not store.save_recovery_project({})
    assert store.recovery_project() == project
    assert store.clear_recovery_project()
    assert store.recovery_project() is None


def test_open_contact_uses_default_application_and_rejects_unsafe_addresses(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr("palletlab.desktop.web_host.webbrowser.open", lambda url: opened.append(url) or True)
    api = WebApplicationApi()
    assert api.open_contact("repository", "https://example.com/project")["ok"]
    assert api.open_contact("email", "user+work@example.com")["ok"]
    assert opened == ["https://example.com/project", "mailto:user%2Bwork@example.com"]
    for kind, value in [("repository", "file:///secret"), ("repository", "https://user@host/"),
                        ("email", "user@example.com?body=hello"), ("email", "user@example.com\nBcc:other@example.com"),
                        ("invalid", "https://example.com")]:
        assert not api.open_contact(kind, value)["ok"]
    monkeypatch.setattr("palletlab.desktop.web_host.webbrowser.open", lambda _url: False)
    assert not api.open_contact("repository", "https://example.com")["ok"]


def test_copy_contact_uses_unicode_clipboard_and_reports_failure(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls = []
    clipboard = SimpleNamespace(
        CF_UNICODETEXT=13,
        OpenClipboard=lambda: calls.append("open"),
        EmptyClipboard=lambda: calls.append("empty"),
        SetClipboardText=lambda value, kind: calls.append((value, kind)),
        CloseClipboard=lambda: calls.append("close"),
    )
    monkeypatch.setitem(sys.modules, "win32clipboard", clipboard)
    api = WebApplicationApi()
    assert api.copy_text("адрес@example.com")["ok"]
    assert calls == ["open", "empty", ("адрес@example.com", 13), "close"]
    assert not api.copy_text("")["ok"]
    def fail(_value, _kind):
        raise OSError("clipboard unavailable")
    clipboard.SetClipboardText = fail
    assert not api.copy_text("test@example.com")["ok"]
    assert calls[-1] == "close"


def test_combined_settings_save_is_atomic_and_preserves_drawing_templates(tmp_path) -> None:
    store = _WebSettings(tmp_path / "settings.json")
    assert store.save_drawing_template("kompas", "drawing.cdt")
    settings = store.application_settings()
    solidworks = {"partTemplate": "part.prtdot", "assemblyTemplate": "assembly.asmdot",
                  "drawingTemplate": "", "materialLibrary": "materials.sldmat", "materialName": "Pine"}
    assert store.save_program_settings(settings, solidworks)
    new_settings = {**settings, "rounding": "5"}
    assert not store.save_program_settings(new_settings, {**solidworks, "materialName": ""})
    assert store.application_settings() == settings
    assert store.solidworks_options() == solidworks
    assert store.save_program_settings(new_settings, None)
    reloaded = _WebSettings(tmp_path / "settings.json")
    assert reloaded.application_settings() == new_settings
    assert reloaded.solidworks_options() == solidworks
    assert reloaded.drawing_templates() == {"kompas": "drawing.cdt"}


def test_solidworks_materials_load_saved_library(monkeypatch) -> None:
    monkeypatch.setattr("palletlab.desktop.web_host.available_materials", lambda path: ("Pine", "Oak"))
    api = WebApplicationApi()
    assert api.solidworks_materials("materials.sldmat") == {"ok": True, "materials": ["Pine", "Oak"]}
    assert not api.solidworks_materials("")["ok"]


def test_normal_exit_discards_recovery_and_rejects_late_autosaves(tmp_path) -> None:
    store = _WebSettings(tmp_path / "settings.json")
    project = WebApplicationApi().default_project()
    assert store.save_recovery_project(project)
    assert store.finish_recovery_session()
    assert not store.save_recovery_project(project)
    assert _WebSettings(tmp_path / "settings.json").recovery_project() is None


def test_web_host_clears_recovery_only_after_normal_exit(monkeypatch, tmp_path) -> None:
    import sys
    from types import SimpleNamespace
    from palletlab.desktop import web_host

    events = []
    class FakeApi:
        def __init__(self):
            self._settings = SimpleNamespace(finish_recovery_session=lambda: events.append("clean"))
        def frontend_url(self, _root):
            return "http://localhost/"
        def attach_window(self, _window):
            pass

    fake_webview = SimpleNamespace(create_window=lambda *_args, **_kwargs: object(), start=lambda: None)
    monkeypatch.setattr(web_host, "WebApplicationApi", FakeApi)
    monkeypatch.setattr(web_host, "frontend_entrypoint", lambda: tmp_path / "index.html")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    web_host.run_web_application()
    assert events == ["clean"]

    events.clear()
    def crash():
        raise RuntimeError("webview failed")
    fake_webview.start = crash
    with pytest.raises(RuntimeError, match="webview failed"):
        web_host.run_web_application()
    assert events == []
