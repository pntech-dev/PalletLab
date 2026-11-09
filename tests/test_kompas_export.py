from __future__ import annotations

from pathlib import Path

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.core.materials import get_material
from types import SimpleNamespace

from palletlab.exporters.kompas import (
    _add_assembly_specification,
    _add_assembly_technical_requirements,
    _assembly_requirement_text_chunks,
    _apply_material,
    _apply_wood_appearance,
    _create_drawing,
    _drawing_scale,
    _placement,
    create_output_directory,
)
from palletlab.exporters.drawings import SpecificationRow


def _result():
    length = DirectionInput(70, 50, (1000,), 100, 100, 100, 100)
    width = DirectionInput(80, 60, (800,), 100, 100, 100, 100)
    return build_pallet(calculate_direction(length), calculate_direction(width))


def test_kompas_export_directory_is_created_inside_chosen_parent_without_overwrite(tmp_path):
    first = create_output_directory(tmp_path, _result())
    second = create_output_directory(tmp_path, _result())

    assert first.parent == tmp_path
    assert first.is_dir()
    assert second.name == f"{first.name}_2"


def test_drawing_uses_specification_saved_with_export(tmp_path, monkeypatch):
    import json
    from palletlab.exporters import kompas
    from palletlab.exporters.drawings import DrawingScope

    (tmp_path / "Pallet.a3d").touch()
    (tmp_path / ".palletlab-drawing.json").write_text(json.dumps({"specification": [
        {"position": 1, "name": "Stored part", "dimensions": "1 × 2 × 3", "quantity": 42},
    ]}), encoding="utf-8")
    captured = []
    pythoncom = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    monkeypatch.setattr(kompas, "_load_kompas_api", lambda: {
        "pythoncom": pythoncom, "Dispatch": lambda _name: SimpleNamespace(Visible=False), "constants": object(),
    })
    monkeypatch.setattr(kompas, "_create_drawing", lambda *_args, **kwargs: captured.append(kwargs))

    kompas.create_drawings(tmp_path, DrawingScope.ASSEMBLY_ONLY, None, _result())

    assert captured[0]["specification_rows"][0].name == "Stored part"
    assert captured[0]["specification_rows"][0].quantity == 42


def test_legacy_specification_finds_actual_part_names_by_dimensions(tmp_path):
    import json
    from palletlab.exporters.kompas import _stored_specification_rows

    (tmp_path / "Beam_1_4200x50x70.m3d").touch()
    (tmp_path / "Beam_2_1950x50x70.m3d").touch()
    (tmp_path / ".palletlab-drawing.json").write_text(json.dumps({"specification": [
        {"position": 1, "name": "Брус", "dimensions": "1950×50×70", "quantity": 14},
        {"position": 2, "name": "Брус", "dimensions": "4200×50×70", "quantity": 5},
    ]}), encoding="utf-8")

    rows = _stored_specification_rows(tmp_path)

    assert [row.designation for row in rows] == ["Beam_2_1950x50x70", "Beam_1_4200x50x70"]


def test_exported_specification_records_actual_part_and_quantity(tmp_path):
    from palletlab.exporters.kompas import _stored_specification_rows, _write_drawing_metadata

    beam = Beam3D(0, 0, 0, 4200, 50, 70, "length")
    key = ("length", 4200, 50, 70)
    _write_drawing_metadata(tmp_path, _result(), {key: tmp_path / "Beam_7_4200x50x70.m3d"}, {key: [beam, beam]})
    rows = _stored_specification_rows(tmp_path)
    assert [(row.designation, row.dimensions, row.quantity) for row in rows] == [
        ("Beam_7_4200x50x70", "4200×50×70", 2),
    ]


def test_kompas_placements_share_the_pallet_origin():
    lengthwise = Beam3D(1500, 2000, 105, 3000, 50, 70, "length")
    widthwise = Beam3D(1500, 2000, 35, 50, 3000, 70, "width")

    assert _placement(lengthwise) == (0.0, 1975.0, 70.0, False)
    assert _placement(widthwise) == (1525.0, 0.0, 0.0, True)


def test_kompas_material_is_assigned_to_the_part_in_grams_per_cm3():
    class _Part:
        def __init__(self):
            self.calls = []

        def SetMaterial(self, name, density):
            self.calls.append(("material", name, density))
            return True

        def Update(self):
            self.calls.append(("update",))

    part = _Part()
    _apply_material(part, get_material("pine"))

    assert part.calls == [("material", "Сосна", 0.5), ("update",)]


def test_kompas_beam_gets_a_light_wood_appearance_when_supported():
    class _Part:
        def __init__(self):
            self.calls = []

        def SetAdvancedColor(self, *args):
            self.calls.append(("colour", args))

        def Update(self):
            self.calls.append(("update",))

    part = _Part()
    _apply_wood_appearance(part)

    assert part.useColor == 0
    assert part.calls == [("colour", (0x70ADDE, 0.35, 0.80, 0.15, 0.10, 1.0, 0.0)), ("update",)]


def test_kompas_drawing_uses_api5_methods_for_a_standard_sheet(tmp_path):
    class _SheetParameters:
        def __init__(self):
            self.initialized = False

        def Init(self):
            self.initialized = True

    class _LayoutParameters:
        def __init__(self):
            self.initialized = False
            self.sheet = _SheetParameters()

        def Init(self):
            self.initialized = True

        def GetSheetParam(self):
            return self.sheet

    class _Parameters:
        def __init__(self):
            self.initialized = False
            self.layout = _LayoutParameters()

        def Init(self):
            self.initialized = True

        def GetLayoutParam(self):
            return self.layout

        def GetViewParam(self):
            return self

    class _Document:
        def __init__(self):
            self.calls = []

        def ksCreateDocument(self, parameters):
            self.calls.append(("create", parameters))
            return True

        def ksCreateSheetStandartViews(self, parameters, view_type, x, y):
            self.calls.append(("views", parameters, view_type, x, y))
            return True

        def ksRebuildDocument(self):
            self.calls.append(("rebuild",))
            return True

        def ksOpenView(self, number):
            self.calls.append(("open-view", number))
            return True

        def ksSaveDocument(self, filename):
            self.calls.append(("save", filename))
            return True

    class _Kompas:
        def __init__(self):
            self.Document2D = _Document()
            self.document_parameters = _Parameters()
            self.view_parameters = _Parameters()

        def GetParamStruct(self, parameter_type):
            return self.document_parameters if parameter_type == "document" else self.view_parameters

    kompas = _Kompas()
    constants = SimpleNamespace(
        ko_DocumentParam="document",
        ko_AssociationViewParam="association-view",
        lt_DocSheetStandart=1,
    )
    model = tmp_path / "Pallet.a3d"
    output = tmp_path / "Pallet.cdw"

    _create_drawing(kompas, constants, model, output, None)

    assert kompas.document_parameters.initialized
    assert kompas.document_parameters.type == 1
    assert kompas.document_parameters.layout.initialized
    assert kompas.document_parameters.layout.sheet.initialized
    assert kompas.document_parameters.layout.sheet.format == 3
    assert kompas.document_parameters.layout.sheet.multiply == 1
    assert kompas.document_parameters.layout.sheet.direct == 1
    assert kompas.view_parameters.initialized
    assert kompas.view_parameters.fileName == str(model)
    assert kompas.view_parameters.projectionName == "#Слева"
    assert kompas.view_parameters.projBodies == 1
    assert kompas.view_parameters.projSurfaces == 1
    assert kompas.view_parameters.projectionLink == 1
    assert kompas.view_parameters.x == 75.0
    assert kompas.view_parameters.y == 245.0
    assert kompas.view_parameters.scale_ == 1 / 4
    assert kompas.Document2D.calls == [
        ("create", kompas.document_parameters),
        ("views", kompas.view_parameters, 21, 25.0, 25.0),
        ("rebuild",),
        ("open-view", 0),
        ("save", str(output)),
    ]


def test_kompas_drawing_opens_a_template_with_api5_methods(tmp_path):
    class _Parameters:
        def GetViewParam(self):
            return self

        def Init(self):
            pass

    class _Document:
        def __init__(self):
            self.calls = []

        def ksOpenDocument(self, filename, visible):
            self.calls.append(("open", filename, visible))
            return True

        def ksCreateSheetStandartViews(self, parameters, view_type, x, y):
            self.calls.append(("views", parameters, view_type, x, y))
            return True

        def ksRebuildDocument(self):
            self.calls.append(("rebuild",))
            return True

        def ksOpenView(self, number):
            self.calls.append(("open-view", number))
            return True

        def ksSaveDocument(self, filename):
            self.calls.append(("save", filename))
            return True

    class _Kompas:
        def __init__(self):
            self.Document2D = _Document()

        def GetParamStruct(self, _parameter_type):
            return _Parameters()

    kompas = _Kompas()
    constants = SimpleNamespace(ko_AssociationViewParam="association-view")
    template = tmp_path / "Template.cdt"
    output = tmp_path / "Pallet.cdw"

    _create_drawing(kompas, constants, tmp_path / "Pallet.a3d", output, template)

    assert kompas.Document2D.calls[0] == ("open", str(template), False)
    assert kompas.Document2D.calls[-1] == ("save", str(output))


def test_kompas_assembly_requirements_use_the_fixed_lower_left_esqd_position():
    class _Document:
        def __init__(self):
            self.texts = []

        def ksText(self, *args):
            self.texts.append(args)
            return True

    document = _Document()

    _add_assembly_technical_requirements(document, None, None)

    assert [text[0:2] for text in document.texts] == [
        (25.0, 10.0), (25.0, 15.0), (25.0, 20.0), (25.0, 25.0),
        (25.0, 30.0), (25.0, 35.0), (25.0, 40.0),
    ]
    assert document.texts[-1][-1] == "1. *Размеры для справок."
    assert document.texts[0][-1] == "7. Все сварные швы зачистить Rz40."


def test_kompas_technical_requirement_chunks_preserve_every_line_break():
    chunks = _assembly_requirement_text_chunks()

    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks).splitlines()[-1] == "7. Все сварные швы зачистить Rz40."


def test_kompas_assembly_specification_is_drawn_in_the_system_view():
    class _Document:
        def __init__(self):
            self.calls = []

        def ksLineSeg(self, *args):
            self.calls.append(("line", *args))
            return True

        def ksText(self, *args):
            self.calls.append(("text", *args))
            return True

        def ksSetTextAlign(self, *args):
            self.calls.append(("align", *args))
            return True

    document = _Document()
    _add_assembly_specification(document, (SpecificationRow(1, "Брус", "2000×100×70", 4, "Beam_2_2000x100x70"),))

    assert document.calls[0][0] == "line"
    lines = [call for call in document.calls if call[0] == "line"]
    assert ("line", 230.0, 60.0, 415.0, 60.0, 1) in lines
    assert all(call[-1] == 1 for call in lines)
    assert [call[-1] for call in document.calls if call[0] == "text"] == [
        "Формат", "Зона", "Поз.", "Обозначение детали", "Наименование", "Кол.", "Приме-", "чание",
        "Прочие изделия", "1", "Beam_2_2000x100x70", "Брус 2000x100x70", "4",
    ]


def test_kompas_drawing_scale_uses_a_standard_reduction_for_large_models():
    assert _drawing_scale(Path("Pallet_4200x1950.a3d")) == 1 / 20
    assert _drawing_scale(Path("Beam_1_1000x100x70.m3d")) == 1 / 4
