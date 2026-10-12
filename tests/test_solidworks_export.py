from __future__ import annotations

from pathlib import Path

import pytest

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.exporters.solidworks import (
    SolidWorksTemplateError,
    _matrix,
    _metres,
    _new_document,
    _resolve_templates,
    create_output_directory,
)


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
    # A width beam's long local Z axis is the template's negative Z axis.
    assert matrix[6:9] == (0.0, 0.0, -1.0)


def test_lengthwise_beam_starts_at_the_shared_pallet_corner():
    beam = Beam3D(1500, 2000, 35, 4000, 50, 70, "length")

    matrix = _matrix(beam)

    assert matrix[9:12] == (0.0, 0.035, -2.0)


def test_templates_are_read_from_solidworks_preferences(tmp_path):
    part = tmp_path / "part.prtdot"; part.write_text("part")
    assembly = tmp_path / "assembly.asmdot"; assembly.write_text("assembly")

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
