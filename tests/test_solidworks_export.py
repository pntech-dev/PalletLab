from __future__ import annotations

from pathlib import Path

import pytest

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.exporters.solidworks import (
    SolidWorksTemplateError,
    _apply_material,
    _active_configuration_name,
    _ensure_material_library_is_configured,
    available_materials,
    _part_document,
    _matrix,
    _metres,
    _new_document,
    _resolve_templates,
    create_output_directory,
)
from palletlab.core.materials import get_material


def _result():
    length = DirectionInput(70, 50, (1000,), 100, 100, 100, 100)
    width = DirectionInput(80, 60, (800,), 100, 100, 100, 100)
    return build_pallet(calculate_direction(length), calculate_direction(width))


def test_export_directory_is_created_inside_chosen_parent_and_does_not_overwrite(tmp_path):
    first = create_output_directory(tmp_path, _result())
    second = create_output_directory(tmp_path, _result())

    assert first.parent == tmp_path
    assert first.is_dir()
    assert second.is_dir()
    assert second.name == f"{first.name}_2"


def test_new_document_uses_the_active_solidworks_document():
    document = object()

    class _SolidWorks:
        IActiveDoc2 = document

        def NewDocument(self, *_args):
            return document

    assert _new_document(_SolidWorks(), Path(__file__), "detail") is document


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
