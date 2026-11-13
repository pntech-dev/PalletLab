"""Export the calculated pallet to native KOMPAS-3D parts and an assembly."""

from __future__ import annotations

from collections import defaultdict
import json
import logging
import math
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Sequence

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
from palletlab.exporters.naming import beam_display_name


LOGGER = logging.getLogger(__name__)

_LOAD_FORMAT_STEP = -3


_A3_LANDSCAPE_FORMAT = 3
_VIEW_ORIGIN_X = 75.0
# KOMPAS places the main standard view downwards from this point.  Keeping the
# anchor in the upper working area leaves room for the long pallet elevation
# above the bottom frame and title block.
_VIEW_ORIGIN_Y = 245.0
_VIEW_GAP = 25.0
_MAX_VIEW_WIDTH = 260.0
# A3 landscape sheet. The main view grows upward from its insertion point;
# the plan view grows downward below it, separated by the projection gap.
_PACKAGING_BOTTOM_CLEARANCE = 60.0
_PACKAGING_TOP_LIMIT = 282.0
_PACKAGING_ELEVATION_BOTTOM = 135.0
_PACKAGING_ELEVATION_X = 55.0
_PACKAGING_AVAILABLE_WIDTH = 275.0
_STANDARD_SCALE_DENOMINATORS = (1, 2, 2.5, 4, 5, 10, 20, 25, 40, 50, 100, 200, 400, 500)
# Front, top and left are the three orthogonal projections.  Including both
# left and right produces duplicate opposing side views in KOMPAS.
_PALLET_VIEW_MASK = 0x01 | 0x04 | 0x10
_ASSEMBLY_TECHNICAL_REQUIREMENTS = (
    "*Размеры для справок.",
    "Сварные соединения по ГОСТ 14771-76.",
    "Острые кромки притупить.",
    "Общие допуски по ГОСТ 30893.1: Н14, h14, ±IТ14/2.",
    "Общие допуски формы и расположения — ГОСТ 30893.2—К.",
    "Остальные ТТ по СТБ 1022-96.",
    "Все сварные швы зачистить Rz40.",
)
_PART_TECHNICAL_REQUIREMENTS = (
    "*Размеры для справок.",
    "Острые кромки притупить.",
    "Общие допуски по ГОСТ 30893.1: Н14, h14, ±IТ14/2.",
    "Общие допуски формы и расположения - ГОСТ 30893.2-К.",
    "Остальные ТТ по СТБ 1014-95.",
)
_KOMPAS_TEXT_ITEM_LIMIT = 100
# The main title block of an A3 landscape sheet is 185×55 mm, aligned to the
# bottom-right frame.  The specification is joined to its upper edge.
_TITLE_BLOCK_LEFT = 230.0
_TITLE_BLOCK_TOP = 60.0
_SPECIFICATION_LEFT = _TITLE_BLOCK_LEFT
_SPECIFICATION_BOTTOM = _TITLE_BLOCK_TOP
_SPECIFICATION_COLUMNS = (7.0, 7.0, 9.0, 64.0, 58.0, 10.0, 30.0)
_SPECIFICATION_HEADER_HEIGHT = 12.0
_SPECIFICATION_ROW_HEIGHT = 8.0
_SPECIFICATION_LINE_STYLE = 1
_TECHNICAL_REQUIREMENTS_LEFT = 25.0
_TECHNICAL_REQUIREMENTS_BOTTOM = 10.0
_TECHNICAL_REQUIREMENTS_LINE_HEIGHT = 5.0
_TECHNICAL_REQUIREMENTS_TEXT_HEIGHT = 3.5


class KompasExportError(RuntimeError):
    """A user-facing failure while preparing or exporting a KOMPAS model."""


def create_drawings(
    model_directory: str | Path,
    scope: DrawingScope,
    configured_template: str | Path | None = None,
    pallet_result: PalletResult | None = None,
    model_path: str | Path | None = None,
    specification_rows: tuple[SpecificationRow, ...] | None = None,
) -> Path:
    """Create KOMPAS associative standard views from native models."""
    directory = Path(model_directory)
    parts = sorted(directory.glob("*.m3d"))
    assembly = next(
        (model for model in sorted(directory.glob("*.a3d")) if model.stem not in ("Модель_экспорта", "УЧ-Поддон")),
        None,
    )
    if model_path is not None:
        selected_model = Path(model_path)
        if not selected_model.is_file():
            raise DrawingExportError(f"Модель для чертежа не найдена: {selected_model}")
        models = [selected_model]
    elif scope is DrawingScope.PARTS_AND_ASSEMBLY:
        models = [*parts, *([assembly] if assembly else [])]
    elif scope is DrawingScope.PARTS_ONLY:
        models = parts
    else:
        models = [assembly] if assembly else []
    if not models:
        raise DrawingExportError("В выбранной папке не найдены модели КОМПАС-3D для создания чертежей.")
    template = Path(configured_template) if configured_template else None
    if template is not None and not template.is_file():
        raise DrawingTemplateError("Указанный шаблон чертежа КОМПАС-3D (.cdt) не найден.")
    stored_rows = _stored_specification_rows(directory)
    api = None
    try:
        api = _load_kompas_api()
        api["pythoncom"].CoInitialize()
        kompas = api["Dispatch"]("KOMPAS.Application.5")
        kompas.Visible = True
        drawings = directory / "Чертежи"
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
                    (
                        specification_rows
                        if specification_rows is not None
                        else stored_rows or (assembly_specification_rows(pallet_result) if pallet_result else ())
                    )
                    if model.suffix.casefold() == ".a3d" else ()
                ),
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
    # KOMPAS exposes saved standard model views with a ``#`` prefix.  The
    # pallet's long elevation is the model's left view; using it as the source
    # projection makes that elevation primary and builds the plan from it.
    parameters.projectionName = "#Слева"
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
    packaging = _is_packaging_model(model)
    view_parameters.x = _PACKAGING_ELEVATION_X if packaging else _VIEW_ORIGIN_X
    scale = _drawing_scale(model)
    view_parameters.y = _packaging_origin_y(model, scale) if packaging else _VIEW_ORIGIN_Y
    view_parameters.scale_ = scale
    view_mask = 0x01 | 0x10 if packaging else _PALLET_VIEW_MASK
    if not document.ksCreateSheetStandartViews(parameters, view_mask, _VIEW_GAP, _VIEW_GAP):
        raise DrawingExportError(f"КОМПАС-3D не создал стандартные виды для {model.name}.")
    if packaging:
        _add_packaging_plan_sheet(kompas, document, parameters, view_parameters, model, scale)
    # Standard views are inserted as associative objects.  KOMPAS creates
    # their nodes first and calculates the visible geometry on rebuild; saving
    # before this step leaves warning-marked, empty views in the drawing tree.
    if not document.ksRebuildDocument():
        raise DrawingExportError(f"КОМПАС-3D не перестроил ассоциативные виды для {model.name}.")
    # ksCreateSheetStandartViews makes the last associative view current.  All
    # annotations below use sheet coordinates, so they must be created in the
    # system view (number 0), rather than in that view's local coordinate
    # system.  Without this switch, TT and the specification grid are visibly
    # displaced from their intended sheet positions.
    # ``ksOpenView`` returns a view reference.  The system view itself has
    # number 0 and some KOMPAS builds also return 0 for its reference, so the
    # return value cannot be interpreted as a failure here.
    document.ksOpenView(0)
    if include_assembly_requirements:
        _add_assembly_technical_requirements(document, kompas, constants)
        _add_assembly_specification(document, specification_rows)
    elif model.suffix.casefold() == ".m3d":
        _add_part_technical_requirements(document)
    if not document.ksSaveDocument(str(filename)):
        raise DrawingExportError(f"КОМПАС-3D не сохранил {filename.name}.")


def _add_assembly_technical_requirements(document, kompas, constants) -> None:
    """Place requirements at the fixed lower-left ESKD sheet position."""
    _add_technical_requirements(document, _ASSEMBLY_TECHNICAL_REQUIREMENTS)


def _add_part_technical_requirements(document) -> None:
    """Place part requirements at the fixed lower-left ESKD sheet position."""
    _add_technical_requirements(document, _PART_TECHNICAL_REQUIREMENTS)


def _add_technical_requirements(document, requirements: tuple[str, ...]) -> None:
    lines = tuple(
        f"{number}. {requirement.replace('—', '-')}"
        for number, requirement in enumerate(requirements, start=1)
    )
    for line_index, text in enumerate(reversed(lines)):
        y = _TECHNICAL_REQUIREMENTS_BOTTOM + line_index * _TECHNICAL_REQUIREMENTS_LINE_HEIGHT
        if not document.ksText(
            _TECHNICAL_REQUIREMENTS_LEFT, y, 0.0, _TECHNICAL_REQUIREMENTS_TEXT_HEIGHT, 1.0, 0, text
        ):
            raise DrawingExportError("КОМПАС-3D не создал текст технических требований.")


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
    """Create the ESKD-style specification joined to the main title block."""
    if not rows:
        return
    width = sum(_SPECIFICATION_COLUMNS)
    table_rows: list[tuple[float, tuple[str, ...], bool]] = [
        (_SPECIFICATION_HEADER_HEIGHT, ("Формат", "Зона", "Поз.", "Обозначение детали", "Наименование", "Кол.", "Приме-\nчание"), True),
        (_SPECIFICATION_ROW_HEIGHT, ("", "", "", "", "", "", ""), False),
        (_SPECIFICATION_ROW_HEIGHT, ("", "", "", "", "Прочие изделия", "", ""), False),
        (_SPECIFICATION_ROW_HEIGHT, ("", "", "", "", "", "", ""), False),
        *(
            (_SPECIFICATION_ROW_HEIGHT, (
                "", "", str(row.position), row.designation,
                " ".join(part for part in (row.name, row.dimensions.replace("×", "x")) if part), str(row.quantity), "",
            ), False)
            for row in rows
        ),
    ]
    height = sum(row_height for row_height, _, _ in table_rows)
    top = _SPECIFICATION_BOTTOM + height
    # ksTable enters KOMPAS's table-editing mode.  API5 then rejects ordinary
    # line segments, which caused the real export to stop at its first row.
    # A specification grid consists of normal thin drawing lines, so create
    # them directly in the system view instead.
    y = top
    if not document.ksLineSeg(_SPECIFICATION_LEFT, y, _SPECIFICATION_LEFT + width, y, _SPECIFICATION_LINE_STYLE):
        raise DrawingExportError("КОМПАС-3D не создал строку таблицы спецификации.")
    for row_height, _, _ in table_rows:
        y -= row_height
        if not document.ksLineSeg(_SPECIFICATION_LEFT, y, _SPECIFICATION_LEFT + width, y, _SPECIFICATION_LINE_STYLE):
            raise DrawingExportError("КОМПАС-3D не создал строку таблицы спецификации.")
    x = _SPECIFICATION_LEFT
    for column_width in _SPECIFICATION_COLUMNS:
        if not document.ksLineSeg(x, top, x, _SPECIFICATION_BOTTOM, _SPECIFICATION_LINE_STYLE):
            raise DrawingExportError("КОМПАС-3D не создал столбец таблицы спецификации.")
        x += column_width
    if not document.ksLineSeg(x, top, x, _SPECIFICATION_BOTTOM, _SPECIFICATION_LINE_STYLE):
        raise DrawingExportError("КОМПАС-3D не завершил рамку таблицы спецификации.")
    y = top
    for row_height, values_in_row, is_header in table_rows:
        x = _SPECIFICATION_LEFT
        for column_index, (column_width, value) in enumerate(zip(_SPECIFICATION_COLUMNS, values_in_row, strict=True)):
            if value:
                _add_specification_cell_text(document, x, y, column_width, row_height, value, is_header, column_index)
            x += column_width
        y -= row_height


def _add_specification_cell_text(
    document, x: float, top: float, width: float, height: float, value: str, is_header: bool, column_index: int,
) -> None:
    """Draw a cell caption centred within its cell without text overflow."""
    if is_header and column_index in {0, 1, 2, 5}:
        reference = document.ksText(x + width / 2.0, top - height / 2.0, 90.0, 2.5, 1.0, 0, value)
        if reference:
            document.ksSetTextAlign(reference, 1)
        return
    if is_header and column_index == 6:
        for line_index, line in enumerate(value.splitlines()):
            reference = document.ksText(x + width / 2.0, top - height * (0.42 + line_index * 0.32), 0.0, 2.5, 1.0, 0, line)
            if reference:
                document.ksSetTextAlign(reference, 1)
        return
    size = 2.5 if is_header else 3.5
    reference = document.ksText(x + width / 2.0, top - height * 0.67, 0.0, size, 1.0, 0, value)
    if reference:
        document.ksSetTextAlign(reference, 1)


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
        rows = tuple(
            SpecificationRow(
                position=int(row["position"]),
                name=str(row["name"]),
                dimensions=str(row["dimensions"]),
                quantity=int(row["quantity"]),
                designation=str(row.get("designation", "")),
            )
            for row in payload.get("specification", ())
        )
        # Older exports did not persist the designation. Recover it from the
        # actual part filenames, never from a synthetic row number: export order
        # can differ from the dimension-sorted specification order.
        parts = sorted(directory.glob("*.m3d"))
        resolved = []
        for row in rows:
            if row.designation:
                resolved.append(row)
                continue
            try:
                dimensions = tuple(float(value.strip()) for value in row.dimensions.replace("×", "x").split("x"))
            except ValueError:
                dimensions = ()
            matches = [part.stem for part in parts if tuple(_dimensions_from_model_name(part)) == dimensions]
            resolved.append(SpecificationRow(row.position, row.name, row.dimensions, row.quantity, ", ".join(matches)))
        return tuple(resolved)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _is_packaging_model(model: Path) -> bool:
    return model.stem in ("УЧ-Поддон", "Модель_экспорта")


def _packaging_dimensions(model: Path) -> tuple[float, float, float]:
    try:
        values = json.loads(model.with_name(".palletlab-packaging-bounds.json").read_text(encoding="utf-8"))["dimensions"]
        if len(values) != 3:
            raise ValueError("invalid dimensions")
        dimensions = tuple(map(float, values))
        if not all(math.isfinite(value) and value > 0 for value in dimensions):
            raise ValueError("invalid dimensions")
        return dimensions
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise DrawingExportError("Не удалось определить габариты упаковочной сборки для выбора масштаба.") from exc


def _packaging_origin_y(model: Path, scale: float) -> float:
    _, _, height = _packaging_dimensions(model)
    working_height = _PACKAGING_TOP_LIMIT - _PACKAGING_ELEVATION_BOTTOM
    return _PACKAGING_ELEVATION_BOTTOM + (working_height - height * scale) / 2.0


def _add_packaging_plan_sheet(kompas, document, parameters, view_parameters, model: Path, scale: float) -> None:
    """Put an independent associative plan on the smallest suitable sheet."""
    try:
        # KOMPAS displays sheets side by side in document coordinates.
        sheets = kompas.ksGetApplication7.ActiveDocument.LayoutSheets
        first_format = sheets.Item(0).Format
        if sheets.Count != 1 or first_format.Format != 3 or first_format.VerticalOrientation:
            raise RuntimeError("нужен шаблон с одним горизонтальным листом A3")
        sheet = sheets.Add()
        length, width, _ = _packaging_dimensions(model)
        # In the #Сверху projection the view grows rightwards and downwards
        # from its insertion point, with model width along the sheet X axis.
        plan_width, plan_height = width * scale, length * scale
        if plan_width <= 180.0 and plan_height <= 217.0:
            sheet_width, sheet_height, use_a4, vertical = 210.0, 297.0, True, True
        elif plan_width <= 267.0 and plan_height <= 130.0:
            sheet_width, sheet_height, use_a4, vertical = 297.0, 210.0, True, False
        else:
            sheet_width, sheet_height, use_a4, vertical = 420.0, 297.0, False, False
        sheet_format = sheet.Format
        sheet_format.Format = 4 if use_a4 else 3  # A4 or A3
        sheet_format.FormatMultiplicity = 1
        sheet_format.VerticalOrientation = vertical
        # Some KOMPAS versions return False even when the format is applied.
        sheet.Update()
        if sheet.Format.Format != (4 if use_a4 else 3) or bool(sheet.Format.VerticalOrientation) != vertical:
            raise RuntimeError("не удалось настроить формат второго листа")
        document.ksOpenView(0)
        parameters.projectionName = "#Сверху"
        view_parameters.x = 420.0 + 20.0 + (sheet_width - 30.0 - plan_width) / 2.0
        working_height = sheet_height - 15.0 - _PACKAGING_BOTTOM_CLEARANCE
        view_parameters.y = _PACKAGING_BOTTOM_CLEARANCE + (working_height - plan_height) / 2.0 + plan_height
        if not document.ksCreateSheetStandartViews(parameters, 0x01, _VIEW_GAP, _VIEW_GAP):
            raise RuntimeError("не удалось создать вид сверху")
    except Exception as exc:
        raise DrawingExportError(f"КОМПАС-3D не создал второй лист упаковочного чертежа: {exc}") from exc


def _drawing_scale(model: Path) -> float:
    """Select a conventional reduction scale that keeps the model on an A3 sheet."""
    if _is_packaging_model(model):
        length, width, height = _packaging_dimensions(model)
        required = max(
            (length + width) / _PACKAGING_AVAILABLE_WIDTH,
            height / (_PACKAGING_TOP_LIMIT - _PACKAGING_ELEVATION_BOTTOM),
            max(length, width) / (_PACKAGING_TOP_LIMIT - _PACKAGING_BOTTOM_CLEARANCE),
            1.0,
        )
    else:
        dimensions = _dimensions_from_model_name(model)
        required = max(1.0, max(dimensions, default=1000.0) / _MAX_VIEW_WIDTH)
    denominator = next(
        (candidate for candidate in _STANDARD_SCALE_DENOMINATORS if candidate >= required),
        math.ceil(required / 100.0) * 100.0,
    )
    return 1.0 / denominator


def _dimensions_from_model_name(model: Path) -> list[float]:
    """Recover dimensions from the native-model names produced by this exporter."""
    stem = model.stem
    dimensions_text = ""
    if stem.startswith("Поддон_"):
        dimensions_text = stem.removeprefix("Поддон_")
    elif stem.startswith("Pallet_"):
        dimensions_text = stem.removeprefix("Pallet_")
    elif stem.startswith(("Брус_", "Доска_")):
        _, beam_name = stem.split("_", 1)
        if "_L=" in beam_name:
            section, length = beam_name.split("_L=", 1)
            length = length.split("_", 1)[0]
            section_dimensions = section.split("x")
            dimensions_text = (
                f"{length}x{section_dimensions[1]}x{section_dimensions[0]}"
                if len(section_dimensions) == 2 else ""
            )
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
    base_name = "Поддон_{}x{}_КОМПАС".format(
        _format_number(result.pallet_length), _format_number(result.pallet_width)
    )
    output = parent_path / base_name
    suffix = 2
    while output.exists():
        output = parent_path / f"{base_name}_{suffix}"
        suffix += 1
    output.mkdir(parents=True)
    return output


def export_pallet(
    result: PalletResult,
    parent_directory: str | Path,
    material_id: str = "pine",
    include_assembly: bool = True,
    step_model_path: str | Path | None = None,
    placement_matrix: Sequence[Sequence[float]] | None = None,
) -> Path:
    """Create KOMPAS M3D parts and optionally an A3D assembly."""
    if (step_model_path is None) != (placement_matrix is None):
        raise KompasExportError("Для модели экспорта нужны STEP-файл и матрица размещения.")
    if step_model_path is not None and not include_assembly:
        raise KompasExportError("Модель упаковки требует включённую модель поддона.")
    api = _load_kompas_api()
    output = create_output_directory(parent_directory, result)
    api["pythoncom"].CoInitialize()
    try:
        return _export(
            api, result, output, get_material(material_id), include_assembly, step_model_path, placement_matrix
        )
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


def _export(
    api: dict[str, object],
    result: PalletResult,
    output: Path,
    material: PalletMaterial,
    include_assembly: bool = True,
    step_model_path: str | Path | None = None,
    placement_matrix: Sequence[Sequence[float]] | None = None,
) -> Path:
    if (step_model_path is None) != (placement_matrix is None):
        raise KompasExportError("Для модели экспорта нужны STEP-файл и матрица размещения.")
    if step_model_path is not None and not include_assembly:
        raise KompasExportError("Модель упаковки требует включённую модель поддона.")
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
    part_name_counts: dict[str, int] = {}
    for key in groups:
        orientation, size_x, size_y, size_z = key
        length, width = (size_x, size_y) if orientation == "length" else (size_y, size_x)
        part_name = beam_display_name(length, width, size_z)
        filename_stem = part_name.replace(" ", "_")
        part_name_counts[filename_stem] = part_name_counts.get(filename_stem, 0) + 1
        if part_name_counts[filename_stem] > 1:
            filename_stem += f"_{part_name_counts[filename_stem]}"
        filename = output / f"{filename_stem}.m3d"
        _create_beam(kompas, constants3d, material, length, width, size_z, part_name, filename)
        parts[key] = filename

    if include_assembly:
        assembly_file = output / f"Поддон_{_format_number(result.pallet_length)}x{_format_number(result.pallet_width)}.a3d"
        _create_assembly(kompas, constants3d, result, parts, assembly_file)
        _write_drawing_metadata(output, result, parts, groups)
        if step_model_path is not None:
            if placement_matrix is None:
                raise KompasExportError("Для модели экспорта не задана матрица размещения STEP-модели.")
            _create_export_assembly(
                kompas,
                constants3d,
                assembly_file,
                Path(step_model_path),
                placement_matrix,
                output / "УЧ-Поддон.a3d",
            )
    return output


def _write_drawing_metadata(
    directory: Path, result: PalletResult,
    parts: dict[tuple[str, float, float, float], Path],
    groups: dict[tuple[str, float, float, float], list[Beam3D]],
) -> None:
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
                "position": index,
                "name": beam_display_name(
                    size_x if orientation == "length" else size_y,
                    size_y if orientation == "length" else size_x,
                    size_z,
                ),
                "dimensions": "",
                "quantity": len(groups[key]),
                "designation": path.stem,
            }
            for index, (key, path) in enumerate(parts.items(), start=1)
            for orientation, size_x, size_y, size_z in (key,)
        ],
    }
    (directory / ".palletlab-drawing.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def _create_beam(
    kompas, constants3d, material: PalletMaterial, length: float, width: float, height: float,
    part_name: str, filename: Path,
) -> None:
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
    _apply_part_name(part, part_name)
    if not document.SaveAs(str(filename)):
        raise KompasExportError(f"Не удалось сохранить {filename.name}.")


def _apply_part_name(part, name: str) -> None:
    """Set and verify the actual KOMPAS part name, not just its file name."""
    try:
        part.name = name
        updated = part.Update()
        actual_name = part.name
    except Exception as exc:
        raise KompasExportError(f"Не удалось задать наименование детали КОМПАС-3D «{name}».") from exc
    if updated is False or actual_name != name:
        raise KompasExportError(f"КОМПАС-3D не сохранил наименование детали «{name}».")


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
        return 0.0, beam.y - beam.size_y / 2.0, bottom_z, False
    # After a 90° rotation local X runs along pallet Y and local Y along -X.
    return beam.x + beam.size_x / 2.0, 0.0, bottom_z, True


def _insert_component(assembly, constants3d, filename: Path, beam: Beam3D) -> None:
    x, y, z, rotate_90 = _placement(beam)
    axes = (0.0, 1.0, 0.0, -1.0, 0.0, 0.0) if rotate_90 else (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    _insert_component_at(assembly, constants3d, filename, (x, y, z), axes)


def _insert_component_at(assembly, constants3d, filename: Path, origin, axes) -> None:
    part = assembly.GetPart(constants3d.pNew_Part)
    if part is None or not assembly.SetPartFromFile(str(filename), part, True):
        raise KompasExportError(f"Не удалось вставить {filename.name} в сборку.")
    placement = part.GetPlacement()
    if placement is None:
        raise KompasExportError(f"Не удалось получить координаты компонента {filename.name}.")
    if not placement.SetOrigin(*origin):
        raise KompasExportError(f"Не удалось задать координаты компонента {filename.name}.")
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


def _create_export_assembly(
    kompas,
    constants3d,
    pallet_assembly: Path,
    step_model_path: Path,
    placement_matrix: Sequence[Sequence[float]],
    filename: Path,
) -> None:
    """Create a package assembly from the pallet and placed imported model."""
    if len(placement_matrix) != 4 or any(len(row) != 4 for row in placement_matrix):
        raise KompasExportError("Матрица размещения STEP-модели должна иметь размер 4×4.")
    if not step_model_path.is_file():
        raise KompasExportError(f"Исходная STEP-модель не найдена: {step_model_path}")
    if not pallet_assembly.is_file():
        raise KompasExportError(f"Модель поддона не найдена: {pallet_assembly}")

    model_directory = filename.parent / "Модель_экспорта"
    model_directory.mkdir(exist_ok=True)
    copied_model = model_directory / step_model_path.name
    try:
        shutil.copy2(step_model_path, copied_model)
    except OSError as exc:
        raise KompasExportError(f"Не удалось скопировать STEP-модель в папку экспорта: {exc}") from exc

    native_model = model_directory / f"{step_model_path.stem}.m3d"
    native_model = _import_step_model(kompas, constants3d, copied_model, native_model)

    assembly = kompas.Document3D
    if not assembly.Create(False, False):
        raise KompasExportError("Не удалось создать сборку модели экспорта КОМПАС.")
    _insert_component_at(assembly, constants3d, pallet_assembly, (0.0, 0.0, 0.0),
                         (1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    origin = tuple(float(placement_matrix[index][3]) for index in range(3))
    axes = tuple(
        float(placement_matrix[row][column])
        for column in range(2)
        for row in range(3)
    )
    _insert_component_at(assembly, constants3d, native_model, origin, axes)
    assembly.RebuildDocument()
    root = assembly.GetPart(constants3d.pTop_Part)
    if root is None:
        raise KompasExportError("Не удалось получить свойства упаковочной сборки КОМПАС.")
    _apply_part_name(root, "УЧ-Поддон")
    bounds = root.GetGabarit(True, True, 0., 0., 0., 0., 0., 0.)
    if not isinstance(bounds, tuple) or len(bounds) != 7 or not bounds[0]:
        raise KompasExportError("Не удалось определить габариты упаковочной сборки КОМПАС.")
    dimensions = [abs(float(bounds[index + 4]) - float(bounds[index + 1])) for index in range(3)]
    if not all(math.isfinite(value) and value > 0 for value in dimensions):
        raise KompasExportError("КОМПАС вернул некорректные габариты упаковочной сборки.")
    if not assembly.SaveAs(str(filename)):
        raise KompasExportError(f"Не удалось сохранить {filename.name}.")
    filename.with_name(".palletlab-packaging-bounds.json").write_text(
        json.dumps({"dimensions": dimensions}), encoding="utf-8"
    )
    try:
        assembly.ZoomPrevNextOrAll(0)
    except Exception:
        LOGGER.debug("KOMPAS does not support optional package-assembly zoom.", exc_info=True)


def _import_step_model(kompas, constants3d, step_path: Path, native_model: Path) -> Path:
    """Import STEP into a native KOMPAS part before inserting it into an assembly."""
    part = kompas.Document3D
    if not part.Create(False, True):
        raise KompasExportError("Не удалось создать деталь для импорта STEP-модели КОМПАС.")
    parameters = part.AdditionFormatParam()
    if parameters is None:
        raise KompasExportError("КОМПАС не предоставил параметры импорта STEP-модели.")
    parameters.Init()
    parameters.format = _LOAD_FORMAT_STEP
    # Init() does not enable geometry options on every KOMPAS installation.
    if not parameters.SetObjectsOptions(0, True) or not parameters.SetObjectsOptions(2, True):
        raise KompasExportError("Не удалось включить импорт тел и поверхностей в КОМПАС.")
    if not part.LoadFromAdditionFormat(str(step_path), parameters):
        raise KompasExportError(f"КОМПАС не импортировал STEP-модель {step_path.name}.")
    part.RebuildDocument()
    root = part.GetPart(constants3d.pTop_Part)
    bodies = root.BodyCollection() if root is not None else None
    if bodies is None or bodies.GetCount() == 0:
        # For STEP assemblies KOMPAS creates a separate A3D and its component
        # files beside the source, leaving the target part empty.
        imported_assembly = step_path.with_suffix(".a3d")
        if imported_assembly.is_file():
            return imported_assembly
        raise KompasExportError(
            f"КОМПАС импортировал STEP-модель {step_path.name} без геометрических тел. "
            "Проверьте исходный файл или настройки импорта КОМПАС."
        )
    if not part.SaveAs(str(native_model)):
        raise KompasExportError(f"Не удалось сохранить импортированную STEP-модель {native_model.name}.")
    return native_model
