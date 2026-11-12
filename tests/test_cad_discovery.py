from pathlib import Path

from palletlab.application.cad_discovery import discover_solidworks_paths


def _material(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<materials><material name="Pine" /><material name="Oak" /></materials>', encoding="utf-8")


def test_finds_standard_templates_and_material_library(tmp_path):
    data, files = tmp_path / "ProgramData", tmp_path / "Program Files"
    templates = data / "SOLIDWORKS" / "SOLIDWORKS 2025" / "templates"
    templates.mkdir(parents=True)
    part, assembly = templates / "Part.prtdot", templates / "Assembly.asmdot"
    part.touch()
    assembly.touch()
    library = files / "SOLIDWORKS Corp" / "SOLIDWORKS" / "lang" / "russian" / "sldmaterials" / "solidworks materials.sldmat"
    _material(library)
    result = discover_solidworks_paths({}, program_data=data, program_files=files, defaults={}, registry_defaults={})
    assert result == {"partTemplate": str(part), "assemblyTemplate": str(assembly), "drawingTemplate": None,
                      "materialLibrary": str(library), "materials": ["Pine", "Oak"],
                      "sources": {"partTemplate": "standard", "assemblyTemplate": "standard", "drawingTemplate": "not_found"}, "configuredPaths": {}}


def test_solidworks_default_takes_priority_over_saved_path(tmp_path):
    data, files = tmp_path / "data", tmp_path / "files"
    own_part, default_part, default_assembly = tmp_path / "custom.prtdot", tmp_path / "default.prtdot", tmp_path / "custom.asmdot"
    for path in (own_part, default_part, default_assembly):
        path.touch()
    result = discover_solidworks_paths({"partTemplate": str(own_part)}, program_data=data, program_files=files,
        defaults={"partTemplate": str(default_part), "assemblyTemplate": str(default_assembly)}, registry_defaults={})
    assert result["partTemplate"] == str(default_part)
    assert result["assemblyTemplate"] == str(default_assembly)
    assert result["drawingTemplate"] is None
    assert result["materialLibrary"] is None


def test_missing_invalid_and_ambiguous_files_are_not_guessed(tmp_path):
    data, files = tmp_path / "data", tmp_path / "files"
    folder = data / "SOLIDWORKS" / "SOLIDWORKS 2025" / "templates"
    folder.mkdir(parents=True)
    (folder / "custom1.prtdot").touch()
    (folder / "custom2.prtdot").touch()
    invalid = files / "SOLIDWORKS Corp" / "SOLIDWORKS" / "lang" / "russian" / "sldmaterials" / "solidworks materials.sldmat"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("not xml", encoding="utf-8")
    result = discover_solidworks_paths({"partTemplate": str(folder / "missing.prtdot"),
        "assemblyTemplate": str(folder / "custom1.prtdot")}, program_data=data, program_files=files, defaults={}, registry_defaults={})
    assert result == {"partTemplate": None, "assemblyTemplate": None, "drawingTemplate": None,
                      "materialLibrary": None, "materials": [],
                      "sources": {"partTemplate": "not_found", "assemblyTemplate": "not_found", "drawingTemplate": "not_found"}, "configuredPaths": {}}


def test_falls_back_to_english_library_and_newest_version(tmp_path):
    data, files = tmp_path / "data", tmp_path / "files"
    for year in (2024, 2025):
        folder = data / "SOLIDWORKS" / f"SOLIDWORKS {year}" / "templates"
        folder.mkdir(parents=True)
        (folder / "Part.prtdot").touch()
    library = files / "SOLIDWORKS Corp" / "SOLIDWORKS" / "lang" / "english" / "sldmaterials" / "solidworks materials.sldmat"
    _material(library)
    result = discover_solidworks_paths({}, program_data=data, program_files=files, defaults={}, registry_defaults={})
    assert "2025" in result["partTemplate"]
    assert result["materialLibrary"] == str(library)


def test_discovers_drawing_template_from_default_or_standard_folder(tmp_path):
    data = tmp_path / "data"
    folder = data / "SOLIDWORKS" / "SOLIDWORKS 2025" / "templates"
    folder.mkdir(parents=True)
    standard = folder / "Drawing.drwdot"
    default = tmp_path / "default.drwdot"
    standard.touch()
    default.touch()
    args = {"program_data": data, "program_files": tmp_path / "files", "defaults": {},
            "registry_defaults": {}}
    assert discover_solidworks_paths({}, **args)["drawingTemplate"] == str(standard)
    args["defaults"] = {"drawingTemplate": str(default)}
    assert discover_solidworks_paths({}, **args)["drawingTemplate"] == str(default)
    assert discover_solidworks_paths({"drawingTemplate": str(standard)}, **args)["drawingTemplate"] == str(default)


def test_registry_reads_latest_version_read_only_and_skips_missing_values(monkeypatch):
    import sys
    from types import SimpleNamespace
    from palletlab.application.cad_discovery import _registry_solidworks_templates

    class Key:
        def __init__(self, name):
            self.name = name
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
    names = ["SOLIDWORKS 2023", "Other", "SolidWorks 2025", "SOLIDWORKS 2024"]
    opened = []
    def open_key(root, path, reserved, access):
        opened.append((path, access))
        return Key(path)
    def query_value(key, name):
        if name == "Default Part Template":
            return (r"D:\templates\part.prtdot", 1)
        raise FileNotFoundError(name)
    fake = SimpleNamespace(HKEY_CURRENT_USER=object(), KEY_READ=0x20019, REG_SZ=1, REG_EXPAND_SZ=2,
                           OpenKey=open_key, QueryInfoKey=lambda _key: (len(names), 0, 0),
                           EnumKey=lambda _key, index: names[index], QueryValueEx=query_value)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert _registry_solidworks_templates() == {"partTemplate": r"D:\templates\part.prtdot"}
    assert opened == [(r"Software\SolidWorks", fake.KEY_READ), (r"SolidWorks 2025\Document Templates", fake.KEY_READ)]


def test_registry_access_denied_falls_back_gracefully(monkeypatch):
    import sys
    from types import SimpleNamespace
    from palletlab.application.cad_discovery import _registry_solidworks_templates
    def fail(*_args):
        raise PermissionError("not accessible")
    fake = SimpleNamespace(HKEY_CURRENT_USER=object(), KEY_READ=0x20019, OpenKey=fail)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert _registry_solidworks_templates() == {}


def test_registry_paths_precede_saved_and_standard_but_not_running(tmp_path):
    data = tmp_path / "data"
    folder = data / "SOLIDWORKS" / "SOLIDWORKS 2025" / "templates"
    folder.mkdir(parents=True)
    standard = folder / "Part.prtdot"
    registered, running, selected = (tmp_path / "reg.prtdot", tmp_path / "active.prtdot", tmp_path / "selected.prtdot")
    for file in (standard, registered, running, selected):
        file.touch()
    args = {"program_data": data, "program_files": tmp_path / "files", "defaults": {},
            "registry_defaults": {"partTemplate": str(registered)}}
    assert discover_solidworks_paths({}, **args)["partTemplate"] == str(registered)
    assert discover_solidworks_paths({"partTemplate": str(selected)}, **args)["partTemplate"] == str(registered)
    args["defaults"] = {"partTemplate": str(running)}
    assert discover_solidworks_paths({}, **args)["partTemplate"] == str(running)
    args["defaults"] = {}
    registered.unlink()
    result = discover_solidworks_paths({}, **args)
    assert result["partTemplate"] is None
    assert result["sources"]["partTemplate"] == "invalid_default"


def test_updated_solidworks_defaults_replace_existing_paths_and_missing_is_not_masked(tmp_path):
    old = {field: tmp_path / f"old{ext}" for field, ext in (("partTemplate", ".prtdot"), ("assemblyTemplate", ".asmdot"), ("drawingTemplate", ".drwdot"))}
    new = {field: tmp_path / f"new{path.suffix}" for field, path in old.items()}
    for path in (*old.values(), *new.values()):
        path.touch()
    current = {field: str(path) for field, path in old.items()}
    defaults = {field: str(path) for field, path in new.items()}
    args = {"program_data": tmp_path / "data", "program_files": tmp_path / "files", "registry_defaults": {}}
    result = discover_solidworks_paths(current, defaults=defaults, **args)
    assert {field: result[field] for field in new} == defaults
    assert all(result["sources"][field] == "solidworks" for field in new)
    new["drawingTemplate"].unlink()
    result = discover_solidworks_paths(current, defaults=defaults, **args)
    assert result["drawingTemplate"] is None
    assert result["sources"]["drawingTemplate"] == "invalid_default"
    assert result["configuredPaths"]["drawingTemplate"] == str(new["drawingTemplate"])
    defaults["partTemplate"] = ""
    result = discover_solidworks_paths(current, defaults=defaults, **args)
    assert result["partTemplate"] is None


def test_running_solidworks_reads_each_preference_without_installed_interop(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace
    from palletlab.application.cad_discovery import _running_solidworks_templates

    calls = []
    class App:
        def _FlagAsMethod(self, name):
            calls.append(("method", name))
        def GetUserPreferenceStringValue(self, preference):
            calls.append(("preference", preference))
            if preference == 9:
                raise RuntimeError("unavailable")
            return {8: "part.prtdot", 10: "drawing.drwdot"}[preference]
    pythoncom = SimpleNamespace(CoInitialize=lambda: calls.append("init"), CoUninitialize=lambda: calls.append("uninit"))
    client = ModuleType("win32com.client")
    client.GetActiveObject = lambda name: App()
    win32com = ModuleType("win32com")
    win32com.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    assert _running_solidworks_templates() == {"partTemplate": "part.prtdot", "drawingTemplate": "drawing.drwdot"}
    assert calls == ["init", ("method", "GetUserPreferenceStringValue"), ("preference", 8),
                     ("preference", 9), ("preference", 10), "uninit"]
