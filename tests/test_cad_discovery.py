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
                      "materialLibrary": str(library), "materials": ["Pine", "Oak"]}


def test_existing_valid_path_and_solidworks_default_take_priority(tmp_path):
    data, files = tmp_path / "data", tmp_path / "files"
    own_part, default_part, default_assembly = tmp_path / "custom.prtdot", tmp_path / "default.prtdot", tmp_path / "custom.asmdot"
    for path in (own_part, default_part, default_assembly):
        path.touch()
    result = discover_solidworks_paths({"partTemplate": str(own_part)}, program_data=data, program_files=files,
        defaults={"partTemplate": str(default_part), "assemblyTemplate": str(default_assembly)}, registry_defaults={})
    assert result["partTemplate"] == str(own_part)
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
                      "materialLibrary": None, "materials": []}


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
    assert discover_solidworks_paths({"drawingTemplate": str(standard)}, **args)["drawingTemplate"] == str(standard)


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


def test_registry_paths_precede_standard_folders_but_do_not_override_explicit_or_running(tmp_path):
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
    assert discover_solidworks_paths({"partTemplate": str(selected)}, **args)["partTemplate"] == str(selected)
    args["defaults"] = {"partTemplate": str(running)}
    assert discover_solidworks_paths({}, **args)["partTemplate"] == str(running)
    args["defaults"] = {}
    registered.unlink()
    assert discover_solidworks_paths({}, **args)["partTemplate"] == str(standard)
