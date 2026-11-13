from __future__ import annotations

from pathlib import Path

import pytest

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.exporters.solidworks import (
    SolidWorksTemplateError,
    _apply_material,
    _active_configuration_name,
    _create_drawing,
    _ensure_material_library_is_configured,
    available_materials,
    _part_document,
    _matrix,
    _metres,
    _new_document,
    _resolve_templates,
    _solidworks_step_component_transform,
    create_output_directory,
)
from palletlab.core.materials import get_material
from palletlab.exporters.drawings import SpecificationRow


def _result():
    length = DirectionInput(70, 50, (1000,), 100, 100, 100, 100)
    width = DirectionInput(80, 60, (800,), 100, 100, 100, 100)
    return build_pallet(calculate_direction(length), calculate_direction(width))


def test_export_directory_is_created_inside_chosen_parent_and_does_not_overwrite(tmp_path):
    first = create_output_directory(tmp_path, _result())
    second = create_output_directory(tmp_path, _result())

    assert first.parent == tmp_path
    assert first.is_dir()
    assert first.name.startswith("Поддон_")
    assert first.name.endswith("_SolidWorks")
    assert second.is_dir()
    assert second.name == f"{first.name}_2"


def test_export_uses_russian_names_for_solidworks_parts_and_assembly(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from palletlab.exporters import solidworks
    from palletlab.exporters.naming import beam_display_name

    created_parts = []
    created_assemblies = []
    monkeypatch.setattr(
        solidworks,
        "_resolve_templates",
        lambda *_args: SimpleNamespace(part=tmp_path / "part.prtdot", assembly=tmp_path / "assembly.asmdot"),
    )
    monkeypatch.setattr(solidworks, "_ensure_material_library_is_configured", lambda *_args: None)
    monkeypatch.setattr(
        solidworks,
        "_create_beam",
        lambda *args: created_parts.append((args[-4], args[-3], args[-2], args[-1])),
    )
    monkeypatch.setattr(solidworks, "_create_assembly", lambda *args: created_assemblies.append(args[-1]))

    output = solidworks._export(
        {"SldWorks": lambda: SimpleNamespace()},
        _result(),
        tmp_path,
        (None, None),
        get_material("pine"),
        tmp_path / "materials.sldmat",
        "Сосна",
    )

    assert output.name.startswith("Поддон_")
    assert output.name.endswith("_SolidWorks")
    assert created_parts
    for length, width, height, filename in created_parts:
        assert filename.name == f"{beam_display_name(length, width, height).replace(' ', '_')}.SLDPRT"
        assert " " not in filename.name
        assert filename.name.startswith(("Брус_", "Доска_"))
    assert created_assemblies[0].name.startswith("Поддон_")
    assert " " not in created_assemblies[0].name


def test_drawing_preserves_exported_assembly_metadata(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from palletlab.exporters import solidworks
    from palletlab.exporters.drawings import DrawingScope

    assembly = tmp_path / "Pallet.SLDASM"
    assembly.touch()
    (tmp_path / "Модель_экспорта.SLDASM").touch()
    (tmp_path / "~$Pallet.SLDASM").touch()
    metadata = tmp_path / ".palletlab-drawing.json"
    metadata.write_text('{"pallet": {"length": 1234}}', encoding="utf-8")
    captured = []
    pythoncom = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    monkeypatch.setattr(solidworks, "_load_solidworks_api", lambda: {
        "pythoncom": pythoncom, "SldWorks": lambda: SimpleNamespace(Visible=False),
    })
    monkeypatch.setattr(solidworks, "_resolve_drawing_template", lambda *_args: tmp_path / "drawing.drwdot")
    monkeypatch.setattr(solidworks, "_create_drawing_with_helper", lambda *args: captured.append(args))

    solidworks.create_drawings(tmp_path, DrawingScope.ASSEMBLY_ONLY, None, _result())

    assert captured[0][1] == assembly
    assert captured[0][0] == tmp_path / "drawing.drwdot"
    assert captured[0][3] == metadata
    assert captured[0][2].parent.name == "Чертежи"
    assert metadata.read_text(encoding="utf-8") == '{"pallet": {"length": 1234}}'


def test_packaging_drawing_targets_explicit_assembly_and_uses_its_specification(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from palletlab.exporters import solidworks
    from palletlab.exporters.drawings import DrawingScope

    assembly = tmp_path / "Модель_экспорта.SLDASM"
    assembly.touch()
    captured = []
    pythoncom = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    monkeypatch.setattr(solidworks, "_load_solidworks_api", lambda: {
        "pythoncom": pythoncom, "SldWorks": lambda: SimpleNamespace(Visible=False),
    })
    monkeypatch.setattr(solidworks, "_resolve_drawing_template", lambda *_args: tmp_path / "drawing.drwdot")
    monkeypatch.setattr(solidworks, "_create_drawing_with_helper", lambda *args: captured.append(args))
    rows = (SpecificationRow(1, "Поддон", "1200×800×210", 1, "Поддон"),)

    solidworks.create_drawings(tmp_path, DrawingScope.ASSEMBLY_ONLY, model_path=assembly, specification_rows=rows)

    metadata = captured[0][3]
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    assert captured[0][1] == assembly
    assert payload["specification"][0]["name"] == "Поддон"
    assert "pallet" not in payload


def test_step_component_transform_maps_pallet_coordinates_to_solidworks_axes():
    matrix = (
        (0.0, -1.0, 0.0, 100.0),
        (1.0, 0.0, 0.0, 200.0),
        (0.0, 0.0, 1.0, 300.0),
        (0.0, 0.0, 0.0, 1.0),
    )

    assert _solidworks_step_component_transform(matrix) == (
        0.0, 0.0, 1.0,
        -1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        0.1, 0.3, 0.2,
        1.0, 0.0, 0.0, 0.0,
    )


@pytest.mark.parametrize(("document_type", "suffix"), [(1, ".SLDPRT"), (2, ".SLDASM")])
def test_step_import_uses_solidworks_neutral_file_import_api(tmp_path, monkeypatch, document_type, suffix):
    from types import SimpleNamespace

    from palletlab.exporters import solidworks

    step_path = tmp_path / "equipment.step"
    step_path.touch()
    native_part = tmp_path / "equipment.SLDPRT"
    import_data = SimpleNamespace(MapConfigurationData=True)
    imported_document = SimpleNamespace(GetType=lambda: document_type)
    calls = []

    class _Variant:
        def __init__(self, _variant_type, value):
            self.value = value

    class _Application:
        def __init__(self):
            self.toggles = {111: False, 112: True, 113: True}

        def GetUserPreferenceStringValue(self, preference):
            calls.append(("get_string", preference))
            return "previous-template"

        def GetUserPreferenceToggle(self, preference):
            calls.append(("get_toggle", preference))
            return self.toggles[preference]

        def SetUserPreferenceStringValue(self, preference, value):
            calls.append(("set_string", preference, value))
            return True

        def SetUserPreferenceToggle(self, preference, value):
            calls.append(("set_toggle", preference, value))
            self.toggles[preference] = value
            return value

        def GetImportFileData(self, path):
            calls.append(("import_data", path))
            return import_data

        def LoadFile4(self, path, options, data, errors):
            calls.append(("load", path, options, data, errors))
            return imported_document

    saved = []
    monkeypatch.setattr(solidworks, "_save", lambda _api, document, path: saved.append((document, path)))
    api = {
        "pythoncom": SimpleNamespace(VT_BYREF=1, VT_I4=3),
        "win32": SimpleNamespace(VARIANT=_Variant),
        "const": {
            "user_preferences": SimpleNamespace(swDefaultTemplatePart=8, swDefaultTemplateAssembly=9),
            "user_preference_toggles": SimpleNamespace(swAlwaysUseDefaultTemplates=111, swMultiCAD_Enable3DInterconnect=112, swImportMultBodyAsPartData=113),
        },
    }

    application = _Application()
    result = solidworks._import_step_model(api, application, step_path, native_part, tmp_path / "part.prtdot", tmp_path / "assembly.asmdot")

    load_call = next(call for call in calls if call[0] == "load")
    assert ("import_data", str(step_path)) in calls
    assert load_call[:4] == ("load", str(step_path), "r", import_data)
    assert load_call[4].value == 0
    assert ("set_string", 9, str(tmp_path / "assembly.asmdot")) in calls
    assert ("set_string", 9, "previous-template") in calls
    assert import_data.MapConfigurationData is False
    assert ("set_string", 8, str(tmp_path / "part.prtdot")) in calls
    assert ("set_string", 8, "previous-template") in calls
    assert ("set_toggle", 111, False) in calls
    assert application.toggles == {111: False, 112: True, 113: True}
    assert ("set_toggle", 112, False) in calls
    assert ("set_toggle", 112, True) in calls
    assert result == native_part.with_suffix(suffix)
    assert saved == [(imported_document, result)]


def test_export_assembly_imports_step_before_adding_native_component(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from palletlab.exporters import solidworks

    pallet = tmp_path / "pallet.SLDASM"
    pallet.touch()
    step_model = tmp_path / "equipment.step"
    step_model.write_text("step", encoding="utf-8")
    imported_document = SimpleNamespace(GetType=lambda: 1)
    load_calls = []
    saved = []

    class _Variant:
        def __init__(self, _variant_type, value):
            self.value = value

    class _Assembly:
        def AddComponents3(self, names, _matrices, _coordinate_systems):
            self.component_names = names.value
            return True

        def EditRebuild3(self):
            pass

        def ShowNamedView2(self, *_args):
            pass

        def ViewZoomtofit2(self):
            pass

    assembly = _Assembly()

    class _Application:
        ActiveDoc = assembly

        def __init__(self):
            self.toggles = {111: False, 112: True, 113: True}

        def GetUserPreferenceStringValue(self, _preference):
            return ""

        def GetUserPreferenceToggle(self, preference):
            return self.toggles[preference]

        def SetUserPreferenceStringValue(self, *_args):
            return True

        def SetUserPreferenceToggle(self, preference, value):
            self.toggles[preference] = value
            return value

        def GetImportFileData(self, _path):
            return SimpleNamespace(MapConfigurationData=True)

        def LoadFile4(self, path, options, data, errors):
            load_calls.append((path, options, data))
            return imported_document

    application = _Application()
    api = {
        "pythoncom": SimpleNamespace(
            VT_BYREF=1, VT_I4=3, VT_ARRAY=0x2000, VT_BSTR=8, VT_R8=5,
        ),
        "win32": SimpleNamespace(
            VARIANT=_Variant,
            GetActiveObject=lambda _name: application,
        ),
        "Convert": SimpleNamespace(ToInt32=int),
        "const": {
            "views": SimpleNamespace(swIsometricView=3),
            "user_preferences": SimpleNamespace(swDefaultTemplatePart=8, swDefaultTemplateAssembly=9),
            "user_preference_toggles": SimpleNamespace(swAlwaysUseDefaultTemplates=111, swMultiCAD_Enable3DInterconnect=112, swImportMultBodyAsPartData=113),
        },
    }

    def save(_api, document, path):
        saved.append((document, path))
        Path(path).touch()

    monkeypatch.setattr(solidworks, "_save", save)
    monkeypatch.setattr(solidworks, "_new_document", lambda *_args: None)
    monkeypatch.setattr(solidworks, "_flag_methods", lambda *_args: None)
    filename = tmp_path / "Модель_экспорта.SLDASM"

    solidworks._create_export_assembly(
        api,
        object(),
        tmp_path / "assembly.asmdot",
        tmp_path / "part.prtdot",
        pallet,
        step_model,
        ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
        filename,
    )

    native_part = tmp_path / "Модель_экспорта" / "equipment.SLDPRT"
    copied_step = tmp_path / "Модель_экспорта" / "equipment.step"
    assert load_calls[0][:2] == (str(copied_step), "r")
    assert load_calls[0][2].MapConfigurationData is False
    assert assembly.component_names == (str(pallet), str(native_part))
    assert saved == [(imported_document, native_part), (assembly, filename)]


def test_export_can_create_parts_without_an_assembly(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from palletlab.exporters import solidworks
    from palletlab.exporters.solidworks import TemplatePaths

    assemblies = []
    monkeypatch.setattr(
        solidworks,
        "_resolve_templates",
        lambda *_args: TemplatePaths(tmp_path / "part.prtdot", None),
    )
    monkeypatch.setattr(solidworks, "_ensure_material_library_is_configured", lambda *_args: None)
    monkeypatch.setattr(solidworks, "_create_beam", lambda *_args: None)
    monkeypatch.setattr(solidworks, "_create_assembly", lambda *args: assemblies.append(args))

    output = solidworks._export(
        {"SldWorks": lambda: SimpleNamespace()},
        _result(),
        tmp_path,
        (None, None),
        get_material("pine"),
        tmp_path / "materials.sldmat",
        "Сосна",
        include_assembly=False,
    )

    assert output.is_dir()
    assert assemblies == []
    assert not (output / ".palletlab-drawing.json").exists()


def test_parts_only_drawing_scope_excludes_assembly(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from palletlab.exporters import solidworks
    from palletlab.exporters.drawings import DrawingScope

    part = tmp_path / "Part.SLDPRT"
    assembly = tmp_path / "Pallet.SLDASM"
    part.touch()
    assembly.touch()
    captured = []
    pythoncom = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    monkeypatch.setattr(solidworks, "_load_solidworks_api", lambda: {
        "pythoncom": pythoncom, "SldWorks": lambda: SimpleNamespace(Visible=False),
    })
    monkeypatch.setattr(solidworks, "_resolve_drawing_template", lambda *_args: tmp_path / "drawing.drwdot")
    monkeypatch.setattr(solidworks, "_create_drawing_with_helper", lambda _template, model, *_args: captured.append(model))

    solidworks.create_drawings(tmp_path, DrawingScope.PARTS_ONLY)

    assert captured == [part]


def test_drawing_helper_runs_without_opening_a_console(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from palletlab.exporters import solidworks

    helper = tmp_path / "SolidWorksDrawingHelper.exe"
    helper.touch()
    calls = []
    monkeypatch.setattr(solidworks, "DRAWING_HELPER", helper)
    monkeypatch.setattr(solidworks.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(solidworks.subprocess, "run", lambda args, **kwargs: (
        calls.append((args, kwargs)) or SimpleNamespace(returncode=0)
    ))

    solidworks._create_drawing_with_helper(tmp_path / "drawing.drwdot", tmp_path / "pallet.SLDASM", tmp_path / "drawing.SLDDRW")

    assert calls[0][1]["creationflags"] == 0x08000000


def test_new_document_uses_the_active_solidworks_document():
    document = object()

    class _SolidWorks:
        IActiveDoc2 = document

        def NewDocument(self, *_args):
            return document

    assert _new_document(_SolidWorks(), Path(__file__), "detail") is document


def test_drawing_uses_a3_paper_size_from_solidworks_template(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from palletlab.exporters import solidworks

    calls = []

    class _Drawing:
        def Create3rdAngleViews2(self, _model):
            return True

        def NewDocument(self, *args):
            calls.append(args)
            return object()

    drawing = _Drawing()

    class _Application:
        ActiveDoc = drawing

    class _Win32:
        def GetActiveObject(self, _name):
            return _Application()

    monkeypatch.setattr(solidworks, "_open_model_for_drawing", lambda *_args: tmp_path / "model.SLDASM")
    monkeypatch.setattr(solidworks, "_use_sheet_scale_and_fit", lambda *_args: None)
    monkeypatch.setattr(solidworks, "_remove_surface_finish_symbols", lambda *_args: None)
    monkeypatch.setattr(solidworks, "_save_drawing", lambda *_args: None)

    class _SolidWorks:
        @property
        def IActiveDoc2(self):
            return drawing

        def NewDocument(self, *args):
            calls.append(args)
            return drawing

    _create_drawing(
        {"win32": _Win32(), "const": {"paper_sizes": SimpleNamespace(swDwgPaperA3size=8)}},
        _SolidWorks(),
        tmp_path / "drawing.drwdot",
        tmp_path / "model.SLDASM",
        tmp_path / "drawing.SLDDRW",
    )

    assert calls[0][1] == 8


def test_solidworks_coordinates_are_floats_for_com():
    assert isinstance(_metres(0), float)
    assert isinstance(-_metres(50) / 2.0, float)


def test_transform_converts_palletlab_height_and_width_to_solidworks_axes():
    beam = Beam3D(1000, 2000, 150, 50, 3000, 70, "width")

    matrix = _matrix(beam)

    assert matrix[9:12] == (1.0, 0.15, 0.0)
    # A width beam's long local Z axis grows from the shared origin in +Z.
    assert matrix[6:9] == (0.0, 0.0, 1.0)


def test_lengthwise_beam_starts_at_the_shared_pallet_corner():
    beam = Beam3D(1500, 2000, 35, 4000, 50, 70, "length")

    matrix = _matrix(beam)

    assert matrix[9:12] == (0.0, 0.035, 2.0)
    assert matrix[0:3] == (0.0, 0.0, 1.0)


def test_templates_are_read_from_solidworks_preferences(tmp_path):
    part = tmp_path / "part.prtdot"
    part.write_text("part")
    assembly = tmp_path / "assembly.asmdot"
    assembly.write_text("assembly")

    class _Preferences:
        swDefaultTemplatePart = "part"
        swDefaultTemplateAssembly = "assembly"

    class _SolidWorks:
        def GetUserPreferenceStringValue(self, preference):
            return str(part if preference == "part" else assembly)

    templates = _resolve_templates({"const": {"user_preferences": _Preferences}}, _SolidWorks(), (None, None))

    assert templates.part == part
    assert templates.assembly == assembly


def test_missing_templates_request_user_selection(tmp_path):
    class _Preferences:
        swDefaultTemplatePart = "part"
        swDefaultTemplateAssembly = "assembly"

    class _SolidWorks:
        def GetUserPreferenceStringValue(self, _preference):
            return ""

    with pytest.raises(SolidWorksTemplateError) as error:
        _resolve_templates({"const": {"user_preferences": _Preferences}}, _SolidWorks(), (None, None))

    assert error.value.missing == ("part", "assembly")


def test_parts_only_export_does_not_require_an_assembly_template(tmp_path):
    part = tmp_path / "part.prtdot"
    part.touch()

    class _Preferences:
        swDefaultTemplatePart = "part"
        swDefaultTemplateAssembly = "assembly"

    class _SolidWorks:
        def GetUserPreferenceStringValue(self, preference):
            return str(part) if preference == "part" else ""

    templates = _resolve_templates(
        {"const": {"user_preferences": _Preferences}},
        _SolidWorks(),
        (None, None),
        include_assembly=False,
    )

    assert templates.part == part
    assert templates.assembly is None


def test_solidworks_material_is_assigned_through_part_document_api():
    class _Manager:
        def Add2(self, *_args):
            return True

    class _Extension:
        def CustomPropertyManager(self, _configuration):
            return _Manager()

    class _PartDocument:
        Extension = _Extension()

        def __init__(self):
            self.calls = []
            self.ConfigurationManager = type(
                "Manager", (), {"ActiveConfiguration": type("Configuration", (), {"Name": "Default"})()}
            )()
            self.assigned_material = ""

        def _FlagAsMethod(self, name):
            self.calls.append(("flag", name))

        def SetMaterialPropertyName2(self, configuration, database, name):
            self.calls.append((configuration, database, name))
            self.assigned_material = name

    document = _PartDocument()
    _apply_material(document, get_material("pine"), Path("company.sldmat"), "Сосна")

    assert ("Default", "company.sldmat", "Сосна") in document.calls


def test_solidworks_reads_material_names_from_selected_library(tmp_path):
    library = tmp_path / "company.sldmat"
    library.write_text('<materials><material name="Сосна"/><material name="Берёза"/></materials>', encoding="utf-8")

    assert available_materials(library) == ("Сосна", "Берёза")


def test_solidworks_requires_library_folder_to_be_registered(tmp_path):
    library_folder = tmp_path / "corporate"
    library_folder.mkdir()
    library = library_folder / "company.sldmat"
    library.write_text("library")

    class _SolidWorks:
        def GetMaterialDatabases(self):
            return (str(tmp_path / "other.sldmat"),)

    sw = _SolidWorks()
    with pytest.raises(Exception, match="не подключена"):
        _ensure_material_library_is_configured({}, sw, library)


def test_solidworks_material_targets_the_active_configuration():
    model = type(
        "Model",
        (),
        {
            "ConfigurationManager": type(
                "Manager", (), {"ActiveConfiguration": type("Configuration", (), {"Name": "Конфигурация1"})()}
            )()
        },
    )()

    assert _active_configuration_name(model) == "Конфигурация1"


def test_solidworks_part_document_is_obtained_through_dispatch():
    part = object()

    class _Application:
        ActiveDoc = part

    class _Win32:
        def GetActiveObject(self, name):
            assert name == "SldWorks.Application"
            return _Application()

    assert _part_document({"win32": _Win32()}, object()) is part


def test_drawing_uses_the_automation_drawing_document(monkeypatch, tmp_path):
    from types import SimpleNamespace

    class _Drawing:
        def __init__(self):
            self.created = []
            self.Extension = type("Extension", (), {"SelectByID2": lambda *_args: True})()

        def GetCurrentSheet(self):
            return type("Sheet", (), {"GetScale": lambda *_args: (1, 10), "SetScale": lambda *_args: None})()

        def GetFirstView(self):
            return type("SheetView", (), {"GetNextView": lambda *_args: None})()

        def ClearSelection2(self, _value):
            pass

        def ActivateView(self, _name):
            return True

        def _FlagAsMethod(self, _name):
            pass

        def Create3rdAngleViews2(self, model):
            self.created.append(model)
            return True

        def AutoDimension(self, *_args):
            return 0

        def ForceRebuild3(self, _value):
            pass

        def ViewZoomtofit2(self):
            pass

    drawing = _Drawing()

    class _Application:
        ActiveDoc = drawing

    class _Win32:
        def GetActiveObject(self, _name):
            return _Application()

    class _SolidWorks:
        IActiveDoc2 = object()

        def NewDocument(self, *_args):
            return object()

    monkeypatch.setattr("palletlab.exporters.solidworks._save_drawing", lambda *_args: None)
    model = tmp_path / "part.SLDPRT"
    monkeypatch.setattr("palletlab.exporters.solidworks._open_model_for_drawing", lambda *_args: model)
    _create_drawing(
        {"win32": _Win32(), "const": {"paper_sizes": SimpleNamespace(swDwgPaperA3size=8)}},
        _SolidWorks(),
        Path(__file__),
        model,
        tmp_path / "part.SLDDRW",
    )

    assert drawing.created == [str(model)]


def test_step_import_restores_solidworks_preferences_on_failure(tmp_path):
    from types import SimpleNamespace
    from palletlab.exporters.solidworks import SolidWorksExportError, _import_step_model

    class App:
        def __init__(self):
            self.paths = {8: "old-part", 9: "old-assembly"}
            self.toggles = {111: False, 112: True, 113: True}
        def GetUserPreferenceStringValue(self, key): return self.paths[key]
        def SetUserPreferenceStringValue(self, key, value): self.paths[key] = value; return True
        def GetUserPreferenceToggle(self, key): return self.toggles[key]
        def SetUserPreferenceToggle(self, key, value): self.toggles[key] = value; return True
        def GetImportFileData(self, _path): return None

    app = App()
    api = {"const": {"user_preferences": SimpleNamespace(swDefaultTemplatePart=8, swDefaultTemplateAssembly=9),
                     "user_preference_toggles": SimpleNamespace(swAlwaysUseDefaultTemplates=111, swMultiCAD_Enable3DInterconnect=112, swImportMultBodyAsPartData=113)}}
    with pytest.raises(SolidWorksExportError, match="параметры импорта"):
        _import_step_model(api, app, tmp_path / "source.step", tmp_path / "model.SLDPRT",
                           tmp_path / "part.prtdot", tmp_path / "assembly.asmdot")
    assert app.paths == {8: "old-part", 9: "old-assembly"}
    assert app.toggles == {111: False, 112: True, 113: True}


def test_step_import_retries_incompatible_source_with_converted_geometry(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from palletlab.exporters import solidworks
    calls = []
    document = SimpleNamespace(GetType=lambda: 2)
    class Variant:
        def __init__(self, _kind, value): self.value = value
    class App:
        def __init__(self): self.paths = {8: "part", 9: "assembly"}; self.flags = {111: False, 112: True, 113: True}
        def GetUserPreferenceStringValue(self, key): return self.paths[key]
        def SetUserPreferenceStringValue(self, key, value): self.paths[key] = value; return True
        def GetUserPreferenceToggle(self, key): return self.flags[key]
        def SetUserPreferenceToggle(self, key, value): self.flags[key] = value; return True
        def GetImportFileData(self, path): calls.append(("data", Path(path))); return SimpleNamespace()
        def LoadFile4(self, path, _mode, _data, errors):
            calls.append(("load", Path(path)))
            if len([call for call in calls if call[0] == "load"]) == 1:
                errors.value = 1
                return None
            return document
    api = {"pythoncom": SimpleNamespace(VT_BYREF=1, VT_I4=3), "win32": SimpleNamespace(VARIANT=Variant),
           "const": {"user_preferences": SimpleNamespace(swDefaultTemplatePart=8, swDefaultTemplateAssembly=9),
                     "user_preference_toggles": SimpleNamespace(swAlwaysUseDefaultTemplates=111, swMultiCAD_Enable3DInterconnect=112, swImportMultBodyAsPartData=113)}}
    source = tmp_path / "source.step"
    converted = tmp_path / "palletlab-compatible.step"
    saved = []
    monkeypatch.setattr(solidworks, "_write_compatible_step", lambda src, dst: calls.append(("convert", src, dst)))
    monkeypatch.setattr(solidworks, "_save", lambda _api, obj, path: saved.append((obj, path)))
    result = solidworks._import_step_model(api, App(), source, tmp_path / "model.SLDPRT", tmp_path / "p.prtdot", tmp_path / "a.asmdot")
    assert ("convert", source, converted) in calls
    assert ("load", converted) in calls
    assert saved == [(document, result)]
    assert result.suffix == ".SLDASM"


def test_compatible_step_preserves_solids_without_expanding_assembly(tmp_path):
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound
    from palletlab.exporters.solidworks import _write_compatible_step

    shape = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(shape)
    builder.Add(shape, BRepPrimAPI_MakeBox(10, 20, 30).Shape())
    builder.Add(shape, BRepPrimAPI_MakeBox(gp_Pnt(50, 0, 0), 10, 20, 30).Shape())
    source, target = tmp_path / "source.step", tmp_path / "compatible.step"
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(str(source))
    previous = Interface_Static.IVal_s("write.step.assembly")
    _write_compatible_step(source, target)
    assert Interface_Static.IVal_s("write.step.assembly") == previous
    assert b"NEXT_ASSEMBLY_USAGE_OCCURRENCE" not in target.read_bytes()
    reader = STEPControl_Reader()
    reader.ReadFile(str(target))
    reader.TransferRoots()
    explorer = TopExp_Explorer(reader.OneShape(), TopAbs_SOLID)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    assert count == 2
