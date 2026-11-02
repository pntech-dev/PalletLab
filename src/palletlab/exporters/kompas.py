"""Export the calculated pallet to native KOMPAS-3D parts and an assembly."""

from __future__ import annotations

from collections import defaultdict
import json
import logging
import math
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palletlab.core.models import Beam3D, PalletResult
from palletlab.core.materials import PalletMaterial, get_material
from palletlab.exporters.drawings import (
    DrawingExportError,
    DrawingScope,
    DrawingTemplateError,
    SpecificationRow,
    assembly_specification_rows,
)


LOGGER = logging.getLogger(__name__)


_A3_LANDSCAPE_FORMAT = 3
_VIEW_ORIGIN_X = 75.0
# KOMPAS places the main standard view downwards from this point.  Keeping the
# anchor in the upper working area leaves room for the long pallet elevation
# above the bottom frame and title block.
_VIEW_ORIGIN_Y = 245.0
_VIEW_GAP = 25.0
_MAX_VIEW_WIDTH = 260.0
_STANDARD_SCALE_DENOMINATORS = (1, 2, 2.5, 4, 5, 10, 20, 25, 40, 50, 100, 200, 400, 500)
_PALLET_VIEW_MASK = 0x01 | 0x04 | 0x10  # front, top, left
_ASSEMBLY_TECHNICAL_REQUIREMENTS = (
    "*Размеры для справок.",
    "Сварные соединения по ГОСТ 14771-76.",
    "Острые кромки притупить.",
    "Общие допуски по ГОСТ 30893.1: Н14, h14, ±IТ14/2.",
    "Общие допуски формы и расположения — ГОСТ 30893.2—К.",
    "Остальные ТТ по СТБ 1022-96.",
    "Все сварные швы зачистить Rz40.",
)
_KOMPAS_TEXT_ITEM_LIMIT = 100
_SPECIFICATION_LEFT = 250.0
_SPECIFICATION_TOP = 150.0
_SPECIFICATION_ROW_HEIGHT = 7.0
_SPECIFICATION_COLUMNS = (12.0, 35.0, 65.0, 16.0)


class KompasExportError(RuntimeError):
    """A user-facing failure while preparing or exporting a KOMPAS model."""


def create_drawings(
    model_directory: str | Path,
    scope: DrawingScope,
    configured_template: str | Path | None = None,
    pallet_result: PalletResult | None = None,
) -> Path:
    """Create KOMPAS associative standard views from native models."""
    directory = Path(model_directory)
    parts = sorted(directory.glob("*.m3d"))
    assembly = next(iter(directory.glob("*.a3d")), None)
    models = [*parts, *([assembly] if assembly else [])] if scope is DrawingScope.PARTS_AND_ASSEMBLY else ([assembly] if assembly else [])
    if not models:
        raise DrawingExportError("В выбранной папке не найдены модели КОМПАС-3D для создания чертежей.")
    template = Path(configured_template) if configured_template else None
    if template is not None and not template.is_file():
        raise DrawingTemplateError("Указанный шаблон чертежа КОМПАС-3D (.cdt) не найден.")
    api = None
    try:
        api = _load_kompas_api()
        api["pythoncom"].CoInitialize()
        kompas = api["Dispatch"]("KOMPAS.Application.5")
        kompas.Visible = True
        drawings = directory / "Drawings"
        drawings.mkdir(exist_ok=True)
        for model in models:
            _create_drawing(
                kompas,
                api["constants"],
                model,
                drawings / f"{model.stem}.cdw",
                template,
                include_assembly_requirements=model.suffix.casefold() == ".a3d",
                specification_rows=(
                    assembly_specification_rows(pallet_result)
                    if model.suffix.casefold() == ".a3d" and pallet_result
                    else _stored_specification_rows(directory) if model.suffix.casefold() == ".a3d" else ()
                ),
                overall_dimensions=_overall_dimensions(model, directory, pallet_result),
            )
        return drawings
    except (DrawingExportError, DrawingTemplateError):
        raise
    except Exception as exc:
        raise DrawingExportError(f"Не удалось создать чертёж КОМПАС-3D: {exc}") from exc
    finally:
        if api is not None:
            api["pythoncom"].CoUninitialize()


def _create_drawing(
    kompas,
    constants,
    model: Path,
    filename: Path,
    template: Path | None,
    include_assembly_requirements: bool = False,
    specification_rows: tuple[SpecificationRow, ...] = (),
    overall_dimensions: tuple[float, float, float] | None = None,
) -> None:
    """Create a drawing through the KOMPAS API5 ``ksDocument2D`` interface.

    ``KOMPAS.Application.5.Document2D`` is an API5 object.  It deliberately
    does not expose the API7-style ``Create``, ``Open`` and ``SaveAs`` methods
    used by 3D documents.  Keeping all three calls in the API5 family avoids
    version-dependent Automation errors and is required for KOMPAS 3D v22+.
    """
    document = kompas.Document2D
    if template is not None:
        if not document.ksOpenDocument(str(template), False):
            raise DrawingTemplateError(f"КОМПАС-3D не открыл шаблон {template.name}.")
    else:
        document_parameters = kompas.GetParamStruct(constants.ko_DocumentParam)
        document_parameters.Init()
        # lt_DocSheetStandart is the API5 type for a standard drawing sheet.
        # The numeric fallback keeps the export compatible with older type
        # libraries that do not publish this named constant to pywin32.
        document_parameters.type = getattr(constants, "lt_DocSheetStandart", 1)
        _configure_standard_sheet(document_parameters, constants)
        if not document.ksCreateDocument(document_parameters):
            raise DrawingExportError("КОМПАС-3D не создал документ чертежа по стандартному шаблону.")
    parameters = kompas.GetParamStruct(constants.ko_AssociationViewParam)
    parameters.Init()
    parameters.fileName = str(model)
    # Init() clears every association option.  With projBodies left at zero,
    # KOMPAS creates the view nodes but deliberately projects no solid bodies,
    # yielding the "Вид не содержит изображения модели" diagnostic.  Include
    # both solids and surfaces so parts and assemblies are handled alike.
    parameters.projBodies = 1
    parameters.projSurfaces = 1
    # The standard-view group must retain its projection relation; otherwise
    # KOMPAS treats its views as independent and does not align them.
    parameters.projectionLink = 1
    view_parameters = parameters.GetViewParam()
    view_parameters.Init()
    view_parameters.x = _VIEW_ORIGIN_X
    view_parameters.y = _VIEW_ORIGIN_Y
    view_parameters.scale_ = _drawing_scale(model)
    if not document.ksCreateSheetStandartViews(parameters, _PALLET_VIEW_MASK, _VIEW_GAP, _VIEW_GAP):
        raise DrawingExportError(f"КОМПАС-3D не создал стандартные виды для {model.name}.")
    # Standard views are inserted as associative objects.  KOMPAS creates
    # their nodes first and calculates the visible geometry on rebuild; saving
    # before this step leaves warning-marked, empty views in the drawing tree.
    if not document.ksRebuildDocument():
        raise DrawingExportError(f"КОМПАС-3D не перестроил ассоциативные виды для {model.name}.")
    if overall_dimensions is not None:
        _add_overall_dimensions(document, kompas, constants, model, overall_dimensions)
    if include_assembly_requirements:
        _add_assembly_technical_requirements(document, kompas, constants)
        _add_assembly_specification(document, specification_rows)
    if not document.ksSaveDocument(str(filename)):
        raise DrawingExportError(f"КОМПАС-3D не сохранил {filename.name}.")


def _add_overall_dimensions(
    document, kompas, constants, model: Path, dimensions: tuple[float, float, float],
) -> None:
    """Create exactly three native linear reference dimensions with arrows."""
    length, width, height = dimensions
    scale = _drawing_scale(model)
    side_width, side_height = length * scale, height * scale
    end_width = width * scale
    side_left, side_bottom = _VIEW_ORIGIN_X - side_width / 2.0, _VIEW_ORIGIN_Y - side_height / 2.0
    end_left = _VIEW_ORIGIN_X + side_width / 2.0 + _VIEW_GAP

    _add_reference_linear_dimension(
        document, kompas, constants,
        side_left, side_bottom, side_left + side_width, side_bottom,
        length, 0, 0.0, -15.0,
    )
    _add_reference_linear_dimension(
        document, kompas, constants,
        end_left, side_bottom, end_left + end_width, side_bottom,
        width, 0, 0.0, -15.0,
    )
    _add_reference_linear_dimension(
        document, kompas, constants,
        end_left + end_width, side_bottom, end_left + end_width, side_bottom + side_height,
        height, 1, 15.0, 0.0,
    )


def _add_reference_linear_dimension(
    document, kompas, constants, x1: float, y1: float, x2: float, y2: float,
    value: float, orientation: int, dx: float, dy: float,
) -> None:
    """Create one native KOMPAS linear dimension with a ``*`` suffix."""
    dimension = kompas.GetParamStruct(constants.ko_LDimParam)
    drawing = dimension.GetDPar()
    source = dimension.GetSPar()
    text = dimension.GetTPar()
    drawing.Init()
    source.Init()
    source.ps = orientation
    source.x1, source.y1, source.x2, source.y2 = x1, y1, x2, y2
    source.dx, source.dy, source.basePoint = dx, dy, 1
    text.Init(False)
    text.SetBitFlagValue(constants._SUFFIX, True)
    text_array = text.GetTextArr()
    for value_text in (_format_dimension(value), "*"):
        item = kompas.GetParamStruct(constants.ko_Char255)
        item.str = value_text
        text_array.ksAddArrayItem(-1, item)
    if not document.ksLinDimension(dimension):
        raise DrawingExportError("КОМПАС-3D не добавил общий габаритный размер.")


def _add_assembly_technical_requirements(document, kompas, constants) -> None:
    """Insert the enterprise assembly requirements as KOMPAS's native TT object."""
    if not document.ksOpenTechnicalDemand(None, 0):
        raise DrawingExportError("КОМПАС-3D не открыл объект технических требований.")
    try:
        # API5 truncates the ``s`` field of a text item on some KOMPAS builds.
        # Keep every item well below that limit, but retain explicit line feeds:
        # the requirements stay a single native TT block and every item starts
        # on the following visible line.
        for text in _assembly_requirement_text_chunks():
            item = kompas.GetParamStruct(constants.ko_TextItemParam)
            item.Init()
            item.s = text
            if not document.ksTextLine(item):
                raise DrawingExportError("КОМПАС-3D не создал текст технических требований.")
    except Exception:
        document.ksCloseTechnicalDemand()
        raise
    if not document.ksCloseTechnicalDemand():
        raise DrawingExportError("КОМПАС-3D не завершил создание технических требований.")


def _assembly_requirement_text_chunks() -> tuple[str, ...]:
    """Split TT text into API5-safe items without losing visible line breaks."""
    lines = tuple(
        f"{number}. {requirement}"
        for number, requirement in enumerate(_ASSEMBLY_TECHNICAL_REQUIREMENTS, start=1)
    )
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > _KOMPAS_TEXT_ITEM_LIMIT:
            chunks.append(f"{current}\n")
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks)


def _add_assembly_specification(document, rows: tuple[SpecificationRow, ...]) -> None:
    """Create an editable native KOMPAS table with the assembly composition."""
    if not rows:
        return
    row_count = len(rows) + 1
    width = sum(_SPECIFICATION_COLUMNS)
    height = row_count * _SPECIFICATION_ROW_HEIGHT
    if not document.ksTable():
        raise DrawingExportError("КОМПАС-3D не начал создание таблицы спецификации.")
    try:
        for row in range(row_count + 1):
            y = _SPECIFICATION_TOP - row * _SPECIFICATION_ROW_HEIGHT
            if not document.ksLineSeg(_SPECIFICATION_LEFT, y, _SPECIFICATION_LEFT + width, y, 2):
                raise DrawingExportError("КОМПАС-3D не создал строку таблицы спецификации.")
        x = _SPECIFICATION_LEFT
        for column_width in _SPECIFICATION_COLUMNS:
            if not document.ksLineSeg(x, _SPECIFICATION_TOP, x, _SPECIFICATION_TOP - height, 2):
                raise DrawingExportError("КОМПАС-3D не создал столбец таблицы спецификации.")
            x += column_width
        if not document.ksLineSeg(x, _SPECIFICATION_TOP, x, _SPECIFICATION_TOP - height, 2):
            raise DrawingExportError("КОМПАС-3D не завершил рамку таблицы спецификации.")
    except Exception:
        document.ksEndObj()
        raise
    if not document.ksEndObj():
        raise DrawingExportError("КОМПАС-3D не завершил создание таблицы спецификации.")
    # API5 permits the table grid to be built as a compound object, but on
    # recent KOMPAS versions rejects text creation while that object is open.
    # Add ordinary editable drawing texts immediately after closing the grid.
    values = (("Поз.", "Наименование", "Размеры, мм", "Кол."), *(
        (str(row.position), row.name, row.dimensions, str(row.quantity)) for row in rows
    ))
    for row_index, values_in_row in enumerate(values):
        x = _SPECIFICATION_LEFT
        y = _SPECIFICATION_TOP - (row_index + 0.72) * _SPECIFICATION_ROW_HEIGHT
        for column_width, value in zip(_SPECIFICATION_COLUMNS, values_in_row, strict=True):
            document.ksText(x + 1.5, y, 0.0, 3.5, 1, 0, value)
            x += column_width


def _configure_standard_sheet(document_parameters, constants) -> None:
    """Prepare an A3 landscape sheet with KOMPAS's native frame and stamp."""
    layout_parameters = document_parameters.GetLayoutParam()
    layout_parameters.Init()
    sheet_parameters = layout_parameters.GetSheetParam()
    sheet_parameters.Init()
    sheet_parameters.format = getattr(constants, "ksFormatA3", _A3_LANDSCAPE_FORMAT)
    sheet_parameters.multiply = 1
    # In the API5 standard-sheet parameters this selects the long-side layout.
    sheet_parameters.direct = 1


def _stored_specification_rows(directory: Path) -> tuple[SpecificationRow, ...]:
    """Read the composition persisted beside the native assembly export."""
    metadata = directory / ".palletlab-drawing.json"
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        return tuple(
            SpecificationRow(
                position=int(row["position"]),
                name=str(row["name"]),
                dimensions=str(row["dimensions"]),
                quantity=int(row["quantity"]),
            )
            for row in payload.get("specification", ())
        )
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _overall_dimensions(
    model: Path, directory: Path, pallet_result: PalletResult | None,
) -> tuple[float, float, float] | None:
    """Return the length, width and height of the document's own envelope."""
    model_dimensions = _dimensions_from_model_name(model)
    if len(model_dimensions) == 3:
        return (model_dimensions[0], model_dimensions[1], model_dimensions[2])
    if model.suffix.casefold() != ".a3d" or len(model_dimensions) != 2:
        return None
    if pallet_result is not None:
        return (pallet_result.pallet_length, pallet_result.pallet_width, pallet_result.pallet_height)
    try:
        payload = json.loads((directory / ".palletlab-drawing.json").read_text(encoding="utf-8"))
        pallet = payload["pallet"]
        return (float(pallet["length"]), float(pallet["width"]), float(pallet["height"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _format_dimension(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _drawing_scale(model: Path) -> float:
    """Select a conventional reduction scale that keeps the model on an A3 sheet."""
    dimensions = _dimensions_from_model_name(model)
    largest_dimension = max(dimensions, default=1000.0)
    required_denominator = max(1.0, largest_dimension / _MAX_VIEW_WIDTH)
    denominator = next(
        (candidate for candidate in _STANDARD_SCALE_DENOMINATORS if candidate >= required_denominator),
        math.ceil(required_denominator / 100.0) * 100.0,
    )
    return 1.0 / denominator


def _dimensions_from_model_name(model: Path) -> list[float]:
    """Recover dimensions from the native-model names produced by this exporter."""
    stem = model.stem
    if stem.startswith("Pallet_"):
        dimensions_text = stem.removeprefix("Pallet_")
    elif stem.startswith("Beam_"):
        parts = stem.split("_", 2)
        dimensions_text = parts[2] if len(parts) == 3 else ""
    else:
        dimensions_text = ""
    try:
        return [float(value.replace("_", ".")) for value in dimensions_text.split("x")]
    except ValueError:
        return []


def _format_number(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}".replace(".", "_")


def create_output_directory(parent: str | Path, result: PalletResult) -> Path:
    """Create a new non-conflicting folder for one KOMPAS pallet export."""
    parent_path = Path(parent)
    base_name = "KOMPAS_Pallet_{}x{}".format(
        _format_number(result.pallet_length), _format_number(result.pallet_width)
    )
    output = parent_path / base_name
    suffix = 2
    while output.exists():
        output = parent_path / f"{base_name}_{suffix}"
        suffix += 1
    output.mkdir(parents=True)
    return output


def export_pallet(result: PalletResult, parent_directory: str | Path, material_id: str = "pine") -> Path:
    """Create KOMPAS M3D parts and an A3D assembly from the current pallet."""
    api = _load_kompas_api()
    output = create_output_directory(parent_directory, result)
    api["pythoncom"].CoInitialize()
    try:
        return _export(api, result, output, get_material(material_id))
    except Exception as exc:
        shutil.rmtree(output, ignore_errors=True)
        raise KompasExportError(str(exc)) from exc
    finally:
        api["pythoncom"].CoUninitialize()


def _load_kompas_api() -> dict[str, object]:
    try:
        import pythoncom
        from win32com.client import Dispatch, gencache

        constants = gencache.EnsureModule(
            "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}", 0, 1, 0
        ).constants
        constants3d = gencache.EnsureModule(
            "{2CAF168C-7961-4B90-9DA2-701419BEEFE3}", 0, 1, 0
        ).constants
        gencache.EnsureModule("{0422828C-F174-495E-AC5D-D31014DBBE87}", 0, 1, 0)
    except (ImportError, OSError) as exc:
        raise KompasExportError("Не удалось подключить API КОМПАС-3D. Проверьте установку КОМПАС-3D и pywin32.") from exc
    return {"pythoncom": pythoncom, "Dispatch": Dispatch, "constants": constants, "constants3d": constants3d}


def _export(api: dict[str, object], result: PalletResult, output: Path, material: PalletMaterial) -> Path:
    try:
        kompas = api["Dispatch"]("KOMPAS.Application.5")
        kompas.Visible = True
    except Exception as exc:
        raise KompasExportError("Не удалось запустить КОМПАС-3D. Проверьте, что программа установлена и зарегистрирована в Windows.") from exc

    constants3d = api["constants3d"]
    groups: dict[tuple[str, float, float, float], list[Beam3D]] = defaultdict(list)
    for beam in result.beams_3d:
        groups[(beam.orientation, beam.size_x, beam.size_y, beam.size_z)].append(beam)

    parts: dict[tuple[str, float, float, float], Path] = {}
    for index, key in enumerate(groups, start=1):
        orientation, size_x, size_y, size_z = key
        length, width = (size_x, size_y) if orientation == "length" else (size_y, size_x)
        filename = output / f"Beam_{index}_{_format_number(length)}x{_format_number(width)}x{_format_number(size_z)}.m3d"
        _create_beam(kompas, constants3d, material, length, width, size_z, filename)
        parts[key] = filename

    assembly_file = output / f"Pallet_{_format_number(result.pallet_length)}x{_format_number(result.pallet_width)}.a3d"
    _create_assembly(kompas, constants3d, result, parts, assembly_file)
    _write_drawing_metadata(output, result)
    return output


def _write_drawing_metadata(directory: Path, result: PalletResult) -> None:
    """Persist assembly composition so drawings can be generated after restart."""
    payload = {
        "schema": 2,
        "pallet": {
            "length": result.pallet_length,
            "width": result.pallet_width,
            "height": result.pallet_height,
        },
        "specification": [
            {
                "position": row.position,
                "name": row.name,
                "dimensions": row.dimensions,
                "quantity": row.quantity,
            }
            for row in assembly_specification_rows(result)
        ],
    }
    (directory / ".palletlab-drawing.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def _create_beam(kompas, constants3d, material: PalletMaterial, length: float, width: float, height: float, filename: Path) -> None:
    document = kompas.Document3D
    if not document.Create(False, True):
        raise KompasExportError(f"Не удалось создать деталь {filename.name}.")
    part = document.GetPart(constants3d.pTop_Part)
    if part is None:
        raise KompasExportError("Не удалось получить корневую деталь КОМПАС.")
    sketch = part.NewEntity(constants3d.o3d_sketch)
    sketch_definition = sketch.GetDefinition() if sketch is not None else None
    plane_xy = part.GetDefaultEntity(constants3d.o3d_planeXOY)
    if sketch_definition is None or plane_xy is None:
        raise KompasExportError("Не удалось подготовить эскиз детали КОМПАС.")
    sketch_definition.SetPlane(plane_xy)
    if not sketch.Create():
        raise KompasExportError("Не удалось создать эскиз детали КОМПАС.")
    sketch_2d = sketch_definition.BeginEdit()
    if sketch_2d is None:
        raise KompasExportError("Не удалось открыть эскиз детали КОМПАС.")
    sketch_2d.ksLineSeg(0.0, 0.0, length, 0.0, 1)
    sketch_2d.ksLineSeg(length, 0.0, length, width, 1)
    sketch_2d.ksLineSeg(length, width, 0.0, width, 1)
    sketch_2d.ksLineSeg(0.0, width, 0.0, 0.0, 1)
    sketch_definition.EndEdit()
    extrusion = part.NewEntity(constants3d.o3d_baseExtrusion)
    definition = extrusion.GetDefinition() if extrusion is not None else None
    if definition is None:
        raise KompasExportError("Не удалось создать выдавливание детали КОМПАС.")
    definition.SetSketch(sketch)
    parameters = definition.ExtrusionParam()
    parameters.direction = constants3d.dtNormal
    parameters.depthNormal = height
    if not extrusion.Create():
        raise KompasExportError("Не удалось выполнить выдавливание детали КОМПАС.")
    _apply_material(part, material)
    _apply_wood_appearance(part)
    if not document.SaveAs(str(filename)):
        raise KompasExportError(f"Не удалось сохранить {filename.name}.")


def _apply_material(part, material: PalletMaterial) -> None:
    """Set KOMPAS's native material on a part and rebuild its properties.

    KOMPAS exposes ``Material`` as a read-only property.  ``SetMaterial`` is
    the API that updates the material shown in the model tree and it expects
    density in g/cm³, rather than kg/m³.
    """
    density_g_cm3 = material.density_kg_m3 / 1000.0
    try:
        assigned = part.SetMaterial(material.kompas_name, density_g_cm3)
    except Exception as exc:
        raise KompasExportError(f"Не удалось назначить материал '{material.name}' детали КОМПАС-3D.") from exc
    if assigned is False:
        raise KompasExportError(f"КОМПАС-3D не назначил материал '{material.name}' детали.")
    try:
        part.Update()
    except Exception as exc:
        raise KompasExportError("КОМПАС-3D не обновил деталь после назначения материала.") from exc


def _apply_wood_appearance(part) -> None:
    """Give exported wooden beams a light, recognisable wood colour.

    Appearance is intentionally optional: older KOMPAS versions may not
    expose visual properties through Automation, but the material itself must
    still be exported successfully.
    """
    try:
        # COLORREF is BGR in memory; this produces a light warm wood RGB
        # colour (222, 173, 112).
        light_wood = 222 | (173 << 8) | (112 << 16)
        part.useColor = 0  # useColorOur
        part.SetAdvancedColor(light_wood, 0.35, 0.80, 0.15, 0.10, 1.0, 0.0)
        part.Update()
    except Exception:
        LOGGER.debug("KOMPAS does not expose optional appearance properties.", exc_info=True)


def _placement(beam: Beam3D) -> tuple[float, float, float, bool]:
    """Return origin and rotation in KOMPAS's X=length, Y=width, Z=height axes."""
    bottom_z = beam.z - beam.size_z / 2.0
    if beam.orientation == "length":
        # Part local X coincides with the pallet X axis.
        return 0.0, beam.y - beam.size_y / 2.0, bottom_z, False
    # After a 90° rotation local X runs along pallet Y and local Y along -X.
    return beam.x + beam.size_x / 2.0, 0.0, bottom_z, True


def _insert_component(assembly, constants3d, filename: Path, beam: Beam3D) -> None:
    part = assembly.GetPart(constants3d.pNew_Part)
    if part is None or not assembly.SetPartFromFile(str(filename), part, True):
        raise KompasExportError(f"Не удалось вставить {filename.name} в сборку.")
    placement = part.GetPlacement()
    if placement is None:
        raise KompasExportError(f"Не удалось получить координаты компонента {filename.name}.")
    x, y, z, rotate_90 = _placement(beam)
    if not placement.SetOrigin(x, y, z):
        raise KompasExportError(f"Не удалось задать координаты компонента {filename.name}.")
    axes = (0.0, 1.0, 0.0, -1.0, 0.0, 0.0) if rotate_90 else (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    if not placement.SetAxes(*axes) or not part.UpdatePlacement():
        raise KompasExportError(f"Не удалось ориентировать компонент {filename.name}.")


def _create_assembly(kompas, constants3d, result: PalletResult, parts, filename: Path) -> None:
    assembly = kompas.Document3D
    if not assembly.Create(False, False):
        raise KompasExportError("Не удалось создать сборку КОМПАС.")
    for beam in result.beams_3d:
        key = (beam.orientation, beam.size_x, beam.size_y, beam.size_z)
        _insert_component(assembly, constants3d, parts[key], beam)
    assembly.RebuildDocument()
    if not assembly.SaveAs(str(filename)):
        raise KompasExportError(f"Не удалось сохранить {filename.name}.")
    try:
        assembly.ZoomPrevNextOrAll(0)
    except Exception:
        LOGGER.debug("KOMPAS does not support optional assembly zoom.", exc_info=True)
