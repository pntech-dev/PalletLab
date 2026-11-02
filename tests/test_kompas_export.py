from __future__ import annotations

from pathlib import Path

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.models import Beam3D, DirectionInput
from palletlab.core.materials import get_material
from types import SimpleNamespace

from palletlab.exporters.kompas import (
    _add_assembly_specification,
    _add_assembly_technical_requirements,
    _add_overall_dimensions,
    _assembly_requirement_text_chunks,
    _apply_material,
    _apply_wood_appearance,
    _create_drawing,
    _drawing_scale,
    _placement,
    _overall_dimensions,
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


def test_kompas_assembly_requirements_are_native_numbered_technical_demands():
    class _Item:
        def Init(self):
            pass

    class _Document:
        def __init__(self):
            self.calls = []
            self.texts = []

        def ksOpenTechnicalDemand(self, bounds, style):
            self.calls.append(("open", bounds, style))
            return True

        def ksTextLine(self, item):
            self.texts.append(item.s)
            return True

        def ksCloseTechnicalDemand(self):
            self.calls.append(("close",))
            return True

    class _Kompas:
        def GetParamStruct(self, _parameter_type):
            return _Item()

    document = _Document()
    constants = SimpleNamespace(ko_TextItemParam="item")

    _add_assembly_technical_requirements(document, _Kompas(), constants)

    assert document.calls == [("open", None, 0), ("close",)]
    assert all(len(text) <= 100 for text in document.texts)
    assert "".join(document.texts).splitlines() == [
        "1. *Размеры для справок.",
        "2. Сварные соединения по ГОСТ 14771-76.",
        "3. Острые кромки притупить.",
        "4. Общие допуски по ГОСТ 30893.1: Н14, h14, ±IТ14/2.",
        "5. Общие допуски формы и расположения — ГОСТ 30893.2—К.",
        "6. Остальные ТТ по СТБ 1022-96.",
        "7. Все сварные швы зачистить Rz40.",
    ]


def test_kompas_technical_requirement_chunks_preserve_every_line_break():
    chunks = _assembly_requirement_text_chunks()

    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks).splitlines()[-1] == "7. Все сварные швы зачистить Rz40."


def test_kompas_assembly_specification_is_an_editable_native_table():
    class _Document:
        def __init__(self):
            self.calls = []

        def ksTable(self):
            self.calls.append(("table",))
            return True

        def ksLineSeg(self, *args):
            self.calls.append(("line", *args))
            return True

        def ksText(self, *args):
            self.calls.append(("text", *args))
            return True

        def ksEndObj(self):
            self.calls.append(("end",))
            return True

    document = _Document()
    _add_assembly_specification(document, (SpecificationRow(1, "Брус", "2000×100×70", 4),))

    assert document.calls[0] == ("table",)
    assert ("end",) in document.calls
    assert [call[-1] for call in document.calls if call[0] == "text"] == [
        "Поз.", "Наименование", "Размеры, мм", "Кол.", "1", "Брус", "2000×100×70", "4",
    ]


def test_kompas_drawing_scale_uses_a_standard_reduction_for_large_models():
    assert _drawing_scale(Path("Pallet_4200x1950.a3d")) == 1 / 20
    assert _drawing_scale(Path("Beam_1_1000x100x70.m3d")) == 1 / 4


def test_kompas_adds_only_three_native_reference_dimensions_with_a_star_suffix(tmp_path):
    class _Drawing:
        def Init(self):
            pass

    class _Source:
        def Init(self):
            pass

    class _TextArray:
        def __init__(self):
            self.items = []

        def ksAddArrayItem(self, _index, item):
            self.items.append(item.str)

    class _Text:
        def __init__(self):
            self.array = _TextArray()

        def Init(self, _manual):
            pass

        def SetBitFlagValue(self, _flag, _enabled):
            pass

        def GetTextArr(self):
            return self.array

    class _Dimension:
        def __init__(self):
            self.drawing = _Drawing()
            self.source = _Source()
            self.text = _Text()

        def GetDPar(self):
            return self.drawing

        def GetSPar(self):
            return self.source

        def GetTPar(self):
            return self.text

    class _Document:
        def __init__(self):
            self.dimensions = []

        def ksLinDimension(self, dimension):
            self.dimensions.append(dimension)
            return True

    class _Kompas:
        def GetParamStruct(self, parameter_type):
            return _Dimension() if parameter_type == "dimension" else type("Char", (), {})()

    document = _Document()
    constants = SimpleNamespace(ko_LDimParam="dimension", ko_Char255="char", _SUFFIX="suffix")
    _add_overall_dimensions(document, _Kompas(), constants, tmp_path / "Pallet_1200x800.a3d", (1200, 800, 145.5))

    assert len(document.dimensions) == 3
    assert [dimension.text.array.items for dimension in document.dimensions] == [
        ["1200", "*"], ["800", "*"], ["145.5", "*"],
    ]


def test_kompas_assembly_dimensions_are_read_from_saved_pallet_envelope(tmp_path):
    (tmp_path / ".palletlab-drawing.json").write_text(
        '{"pallet":{"length":1200,"width":800,"height":145}}', encoding="utf-8"
    )

    assert _overall_dimensions(tmp_path / "Pallet_1200x800.a3d", tmp_path, None) == (1200.0, 800.0, 145.0)
