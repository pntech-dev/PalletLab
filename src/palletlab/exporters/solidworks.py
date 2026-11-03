"""Export the calculated pallet to native SolidWorks parts and an assembly.

SolidWorks is deliberately imported lazily.  This keeps the main application
usable on workstations where the CAD system is not installed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING
from xml.etree import ElementTree

if TYPE_CHECKING:
    from palletlab.core.models import Beam3D, PalletResult
from palletlab.core.materials import PalletMaterial, get_material
from palletlab.exporters.drawings import (
    DrawingExportError,
    DrawingScope,
    DrawingTemplateError,
    assembly_specification_rows,
)


LOGGER = logging.getLogger(__name__)

# ГОСТ 2.302-68: permitted reduction scales for a large assembly drawing.
# We deliberately never invent an arbitrary ratio merely to fill a sheet.
GOST_REDUCTION_SCALES: tuple[tuple[int, int], ...] = (
    (1, 1), (1, 2), (1, 5), (1, 10), (1, 15), (1, 20), (1, 25),
    (1, 40), (1, 50), (1, 75), (1, 100), (1, 200), (1, 400),
    (1, 500), (1, 800), (1, 1000),
)


BASE_PLANE_NAME = "Спереди"
SOLIDWORKS_API_DIR = Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist")
_HELPER_RELATIVE_PATH = Path("tools") / "SolidWorksDrawingHelper" / "bin" / "Debug" / "net10.0-windows" / "SolidWorksDrawingHelper.exe"


def _drawing_helper_path() -> Path:
    """Locate the helper both in a source checkout and a PyInstaller build."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / _HELPER_RELATIVE_PATH
    return Path(__file__).resolve().parents[3] / _HELPER_RELATIVE_PATH


DRAWING_HELPER = _drawing_helper_path()

class SolidWorksExportError(RuntimeError):
    """A user-facing failure while preparing or exporting a CAD model."""


class SolidWorksTemplateError(SolidWorksExportError):
    """SolidWorks has no usable part or assembly template configured."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        labels = {"part": "детали (.prtdot)", "assembly": "сборки (.asmdot)"}
        super().__init__("Не найден шаблон " + " и ".join(labels[item] for item in missing) + ".")


class SolidWorksMaterialLibraryError(SolidWorksExportError):
    """SolidWorks material library is absent, invalid, or not configured."""


@dataclass(frozen=True)
class TemplatePaths:
    part: Path
    assembly: Path


def create_drawings(
    model_directory: str | Path,
    scope: DrawingScope,
    configured_template: str | Path | None = None,
    pallet_result: PalletResult | None = None,
) -> Path:
    """Create associative SolidWorks drawings for the exported native models.

    A ``.drwdot`` selected by the operator takes priority.  When it is absent,
    SolidWorks' own default drawing template is used, so an organisation's
    ESKD/GOST styles remain intact.
    """
    directory = Path(model_directory)
    metadata = _write_drawing_metadata(directory, pallet_result) if pallet_result else _drawing_metadata_path(directory)
    models = sorted(directory.glob("*.SLDPRT"))
    assembly = next(iter(directory.glob("*.SLDASM")), None)
    if scope is DrawingScope.PARTS_AND_ASSEMBLY:
        models_to_draw = [*models, *([assembly] if assembly else [])]
    else:
        models_to_draw = [assembly] if assembly else []
    if not models_to_draw:
        raise DrawingExportError("В выбранной папке не найдены модели SolidWorks для создания чертежей.")

    api = None
    try:
        api = _load_solidworks_api()
        api["pythoncom"].CoInitialize()
        sw = api["SldWorks"]()
        if sw is None:
            raise DrawingExportError("Не удалось запустить SolidWorks.")
        sw.Visible = True
        template = _resolve_drawing_template(api, sw, configured_template)
        drawings = directory / "Drawings"
        drawings.mkdir(exist_ok=True)
        for model in models_to_draw:
            _create_drawing_with_helper(
                template, model, drawings / f"{model.stem}.SLDDRW",
                metadata if model.suffix.casefold() == ".sldasm" and metadata.is_file() else None,
            )
        return drawings
    except (DrawingExportError, DrawingTemplateError):
        raise
    except Exception as exc:
        raise DrawingExportError(f"Не удалось создать чертёж SolidWorks: {exc}") from exc
    finally:
        if api is not None:
            api["pythoncom"].CoUninitialize()


def _create_drawing_with_helper(template: Path, model_path: Path, filename: Path, metadata: Path | None = None) -> None:
    """Use strongly typed .NET interop, avoiding pywin32's COM dispatch bugs."""
    if not DRAWING_HELPER.is_file():
        raise DrawingExportError(
            "Не найден модуль создания чертежей SolidWorks. Соберите tools/SolidWorksDrawingHelper."
        )
    completed = subprocess.run(  # noqa: S603 - fixed local helper; arguments are passed without a shell.
        [str(DRAWING_HELPER), str(template), str(model_path), str(filename), *([str(metadata)] if metadata else [])],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"код {completed.returncode}"
        raise DrawingExportError(f"Модуль SolidWorks не создал чертёж {model_path.name}: {detail}")


def _drawing_metadata_path(directory: Path) -> Path:
    return directory / ".palletlab-drawing.json"


def _write_drawing_metadata(directory: Path, result: PalletResult) -> Path:
    """Persist the pallet envelope used to choose the sheet scale and layout."""
    metadata = _drawing_metadata_path(directory)
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
                "designation": row.designation,
            }
            for row in assembly_specification_rows(result)
        ],
    }
    metadata.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return metadata


def _resolve_drawing_template(api: dict[str, object], sw, configured_template: str | Path | None) -> Path:
    configured = Path(configured_template) if configured_template else None
    preferences = api["const"]["user_preferences"]
    default = _solidworks_template(sw, preferences.swDefaultTemplateDrawing)
    template = configured if configured and configured.is_file() else default
    if template is None or not template.is_file():
        raise DrawingTemplateError(
            "Не найден шаблон чертежа SolidWorks (.drwdot). Выберите его или настройте стандартный шаблон чертежа в SolidWorks."
        )
    return template


def _create_drawing(api: dict[str, object], sw, template: Path, model_path: Path, filename: Path) -> None:
    model_path = _open_model_for_drawing(api, model_path)
    try:
        _new_document(sw, template, filename.name)
    except Exception as exc:
        raise DrawingExportError(f"SolidWorks не создал лист чертежа {filename.name}: {exc}") from exc
    # NewDocument returns IModelDoc2 through pythonnet.  Drawing-only methods
    # are exposed by the Automation DrawingDoc interface, so obtain the same
    # active document via pywin32 (as is already done for IAssemblyDoc).
    drawing = api["win32"].GetActiveObject("SldWorks.Application").ActiveDoc
    if drawing is None:
        raise DrawingExportError("Не удалось получить документ чертежа SolidWorks.")
    try:
        _flag_methods(drawing, "Create3rdAngleViews2", "ForceRebuild3", "ViewZoomtofit2")
        created = drawing.Create3rdAngleViews2(str(model_path))
    except Exception as exc:
        raise DrawingExportError(f"SolidWorks не вставил стандартные виды для {model_path.name}: {exc}") from exc
    if not created:
        raise DrawingExportError(f"SolidWorks не создал стандартные виды для {model_path.name}.")
    _use_sheet_scale_and_fit(drawing)
    _remove_surface_finish_symbols(drawing)
    # Standard views are associative.  GOST/ESKD appearance, projection
    # convention and annotation styles are supplied by the .drwdot file.
    for method, args in (("ForceRebuild3", (True,)), ("ViewZoomtofit2", ())):
        try:
            _flag_methods(drawing, method)
            getattr(drawing, method)(*args)
        except Exception:
            LOGGER.debug("SolidWorks does not expose optional drawing method %s.", method, exc_info=True)
    try:
        _save_drawing(api, drawing, filename)
    except Exception as exc:
        raise DrawingExportError(f"SolidWorks не сохранил чертёж {filename.name}: {exc}") from exc


def _open_model_for_drawing(api: dict[str, object], model_path: Path) -> Path:
    """Open the model with correctly typed COM ``out`` parameters.

    ``OpenDoc6`` requires ByRef integer variables for Errors and Warnings.
    Plain Python integers cause DISP_E_TYPEMISMATCH in pywin32.
    """
    document_type = 2 if model_path.suffix.casefold() == ".sldasm" else 1  # swDocASSEMBLY / swDocPART
    try:
        application = api["win32"].GetActiveObject("SldWorks.Application")
        byref_i4 = api["pythoncom"].VT_BYREF | api["pythoncom"].VT_I4
        errors = api["win32"].VARIANT(byref_i4, 0)
        warnings = api["win32"].VARIANT(byref_i4, 0)
        opened = application.OpenDoc6(str(model_path), document_type, 1, "", errors, warnings)
        if isinstance(opened, tuple):
            opened = opened[0]
    except Exception as exc:
        raise DrawingExportError(f"SolidWorks не открыл модель {model_path.name} (OpenDoc6): {exc}") from exc
    if opened is None:
        raise DrawingExportError(
            f"SolidWorks не открыл модель {model_path.name}; код загрузки: {errors.value}, предупреждения: {warnings.value}."
        )
    return model_path


def _save_drawing(api: dict[str, object], drawing, filename: Path) -> None:
    """Save a DrawingDoc without ModelDoc-only calls such as ClearSelection2."""
    version = api["Convert"].ToInt32(api["const"]["save_version"].swSaveAsCurrentVersion)
    options = api["Convert"].ToInt32(api["const"]["save_options"].swSaveAsOptions_Silent)
    try:
        _flag_methods(drawing, "SaveAs3")
        drawing.SaveAs3(str(filename), version, options)
    except Exception:
        extension = drawing.Extension
        _flag_methods(extension, "SaveAs")
        extension.SaveAs(str(filename), version, options, None)
    if not filename.exists():
        raise DrawingExportError(f"SolidWorks не записал файл {filename.name}.")


def _use_sheet_scale_and_fit(drawing) -> None:
    """Use a GOST scale on the sheet and make every model view inherit it."""
    try:
        sheet = drawing.GetCurrentSheet()
        numerator, denominator = _sheet_scale(sheet)
        scale = _nearest_gost_reduction_scale(numerator / denominator)
        _flag_methods(sheet, "SetScale")
        sheet.SetScale(scale[0], scale[1], True, True)
        for view in _model_views(drawing):
            view.UseSheetScale = True
    except Exception:
        # A custom template can expose a limited Sheet interface.  Its existing
        # scale remains valid; do not prevent a drawing from being saved.
        LOGGER.debug("SolidWorks did not expose sheet-scale controls.", exc_info=True)


def _sheet_scale(sheet) -> tuple[int, int]:
    """Read ITableAnnotation-compatible COM variants returned by GetScale."""
    scale = sheet.GetScale()
    if isinstance(scale, (tuple, list)) and len(scale) >= 2:
        return int(scale[0]), int(scale[1])
    raise ValueError("SolidWorks did not return a sheet scale.")


def _nearest_gost_reduction_scale(maximum: float) -> tuple[int, int]:
    """Return the largest permitted GOST scale not exceeding ``maximum``."""
    allowed = [(numerator / denominator, numerator, denominator) for numerator, denominator in GOST_REDUCTION_SCALES]
    return next((numerator, denominator) for value, numerator, denominator in allowed if value <= maximum + 1e-9)


def _model_views(drawing):
    view = drawing.GetFirstView()
    if view is not None:
        view = view.GetNextView()  # the first item is the sheet, not a model view
    while view is not None:
        yield view
        view = view.GetNextView()


def _remove_surface_finish_symbols(drawing) -> None:
    """Remove template-inherited surface-roughness annotations from assemblies."""
    try:
        for view in _model_views(drawing):
            for annotation in view.GetAnnotations() or ():
                specific = annotation.GetSpecificAnnotation()
                # ISFSymbol is the only annotation type with this member set;
                # Delete is intentionally best-effort for older SW releases.
                if specific is not None and specific.__class__.__name__.lower().endswith("sfsymbol"):
                    annotation.Select3(False, None)
                    drawing.Extension.DeleteSelection2(0)
    except Exception:
        LOGGER.debug("SolidWorks did not expose removable surface-finish symbols.", exc_info=True)


def _format_number(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}".replace(".", "_")


def _metres(value_mm: float) -> float:
    return float(value_mm) / 1000.0


def create_output_directory(parent: str | Path, result: PalletResult) -> Path:
    """Create a new non-conflicting folder for one pallet export."""
    parent_path = Path(parent)
    base_name = "SolidWorks_Pallet_{}x{}".format(
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
    configured_templates: tuple[str | Path | None, str | Path | None] = (None, None),
    material_id: str = "pine",
    material_library: str | Path | None = None,
    material_name: str | None = None,
) -> Path:
    """Create the native parts and assembly; return the newly-created folder."""
    api = _load_solidworks_api()
    api["pythoncom"].CoInitialize()
    try:
        material = get_material(material_id)
        library = _validate_material_library(material_library, material_name)
        return _export(api, result, Path(parent_directory), configured_templates, material, library, material_name)
    except SolidWorksExportError:
        raise
    except Exception as exc:
        raise SolidWorksExportError(str(exc)) from exc
    finally:
        api["pythoncom"].CoUninitialize()


def _load_solidworks_api() -> dict[str, object]:
    sldworks_dll = SOLIDWORKS_API_DIR / "SolidWorks.Interop.sldworks.dll"
    swconst_dll = SOLIDWORKS_API_DIR / "SolidWorks.Interop.swconst.dll"
    missing = [str(path) for path in (sldworks_dll, swconst_dll) if not path.exists()]
    if missing:
        raise SolidWorksExportError("Не найдены файлы SolidWorks или шаблоны:\n" + "\n".join(missing))
    try:
        import clr
        import pythoncom
        import win32com.client
        from System import Convert

        clr.AddReference(str(sldworks_dll))
        clr.AddReference(str(swconst_dll))
        from SolidWorks.Interop.sldworks import SldWorks
        from SolidWorks.Interop.swconst import (
            swEndConditions_e,
            swSaveAsOptions_e,
            swSaveAsVersion_e,
            swStandardViews_e,
            swUserPreferenceStringValue_e,
        )
    except (ImportError, OSError) as exc:
        raise SolidWorksExportError("Не удалось подключить API SolidWorks. Переустановите компоненты pythonnet и pywin32 приложения.") from exc
    return {
        "SldWorks": SldWorks,
        "Convert": Convert,
        "const": {
            "end_conditions": swEndConditions_e,
            "save_options": swSaveAsOptions_e,
            "save_version": swSaveAsVersion_e,
            "views": swStandardViews_e,
            "user_preferences": swUserPreferenceStringValue_e,
        },
        "pythoncom": pythoncom,
        "win32": win32com.client,
    }


def _export(api: dict[str, object], result: PalletResult, parent_directory: Path, configured_templates, material: PalletMaterial, material_library: Path, material_name: str) -> Path:
    sw = api["SldWorks"]()
    if sw is None:
        raise SolidWorksExportError("Не удалось запустить SolidWorks.")
    sw.Visible = True
    templates = _resolve_templates(api, sw, configured_templates)
    _ensure_material_library_is_configured(api, sw, material_library)
    output = create_output_directory(parent_directory, result)
    try:
        groups: dict[tuple[str, float, float, float], list[Beam3D]] = defaultdict(list)
        for beam in result.beams_3d:
            groups[(beam.orientation, beam.size_x, beam.size_y, beam.size_z)].append(beam)

        parts: dict[tuple[str, float, float, float], Path] = {}
        for index, (key, beams) in enumerate(groups.items(), start=1):
            orientation, size_x, size_y, size_z = key
            length, cross_width = (size_y, size_x) if orientation == "width" else (size_x, size_y)
            filename = output / f"Beam_{index}_{_format_number(length)}x{_format_number(cross_width)}x{_format_number(size_z)}.SLDPRT"
            _create_beam(api, sw, templates.part, material, material_library, material_name, length, cross_width, size_z, filename)
            parts[key] = filename

        assembly_file = output / f"Pallet_{_format_number(result.pallet_length)}x{_format_number(result.pallet_width)}.SLDASM"
        _create_assembly(api, sw, templates.assembly, result, parts, assembly_file)
        _write_drawing_metadata(output, result)
        return output
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def _resolve_templates(api: dict[str, object], sw, configured_templates) -> TemplatePaths:
    configured_part, configured_assembly = (Path(path) if path else None for path in configured_templates)
    preferences = api["const"]["user_preferences"]
    default_part = _solidworks_template(sw, preferences.swDefaultTemplatePart)
    default_assembly = _solidworks_template(sw, preferences.swDefaultTemplateAssembly)
    part = configured_part if configured_part and configured_part.is_file() else default_part
    assembly = configured_assembly if configured_assembly and configured_assembly.is_file() else default_assembly
    missing = tuple(name for name, path in (("part", part), ("assembly", assembly)) if path is None or not path.is_file())
    if missing:
        raise SolidWorksTemplateError(missing)
    return TemplatePaths(part=part, assembly=assembly)


def _solidworks_template(sw, preference) -> Path | None:
    try:
        value = sw.GetUserPreferenceStringValue(preference)
    except Exception:
        return None
    return Path(value) if value else None


def _flag_methods(com_object, *names: str) -> None:
    flag = getattr(com_object, "_FlagAsMethod", None)
    if flag is not None:
        for name in names:
            flag(name)


def _new_document(sw, template: Path, name: str):
    if sw.NewDocument(str(template), 0, 0.0, 0.0) is None:
        raise SolidWorksExportError(f"SolidWorks не создал документ: {name}")
    document = sw.IActiveDoc2
    if document is None:
        raise SolidWorksExportError(f"Не удалось получить документ: {name}")
    return document


def _create_beam(api, sw, template: Path, material: PalletMaterial, material_library: Path, material_name: str, length: float, width: float, height: float, filename: Path) -> None:
    model = _new_document(sw, template, filename.name)
    model.ClearSelection2(True)
    if not model.Extension.SelectByID2(BASE_PLANE_NAME, "PLANE", 0.0, 0.0, 0.0, False, 0, None, 0):
        raise SolidWorksExportError(f"Не удалось выбрать плоскость '{BASE_PLANE_NAME}'.")
    sketch_manager = model.SketchManager
    sketch_manager.InsertSketch(True)
    sketch_manager.CreateCornerRectangle(
        -_metres(width) / 2.0, -_metres(height) / 2.0, 0.0,
        _metres(width) / 2.0, _metres(height) / 2.0, 0.0,
    )
    sketch_manager.InsertSketch(True)
    sketch = model.Extension.GetLastFeatureAdded()
    model.ClearSelection2(True)
    if sketch is None or not sketch.Select2(False, 0):
        raise SolidWorksExportError("Не удалось подготовить эскиз бруса.")
    blind = api["Convert"].ToInt32(api["const"]["end_conditions"].swEndCondBlind)
    extrusion = model.FeatureManager.FeatureExtrusion2(True, False, False, blind, blind, _metres(length), 0.0,
        False, False, False, False, 0.0, 0.0, False, False, False, False, True, True, True, 0, 0.0, False)
    if extrusion is None:
        raise SolidWorksExportError("Не удалось создать брус в SolidWorks.")
    _apply_material(_part_document(api, model), material, material_library, material_name)
    _save(api, model, filename)


def _part_document(api: dict[str, object], model):
    """Return the active part through IDispatch when pythonnet gives ModelDoc2.

    The interop wrapper exposes the new document as ``IModelDoc2``.  Material
    assignment is a member of ``IPartDoc`` only; obtaining the same active
    document through pywin32 gives access to that part-specific interface.
    """
    try:
        document = api["win32"].GetActiveObject("SldWorks.Application").ActiveDoc
        if document is not None:
            return document
    except Exception:
        LOGGER.debug("SolidWorks did not expose an IPartDoc wrapper.", exc_info=True)
    return model


def _apply_material(model, material: PalletMaterial, material_library: Path, material_name: str) -> None:
    """Assign the SolidWorks material and preserve readable export metadata.

    ``SetMaterialPropertyName2`` belongs to ``IPartDoc`` (the document
    itself), not to ``IModelDocExtension``.  Passing an empty database tells
    SolidWorks to use its configured default ``.sldmat`` database.
    """
    configuration = _active_configuration_name(model)
    try:
        _flag_methods(model, "SetMaterialPropertyName2")
        model.SetMaterialPropertyName2(configuration, material_library.name, material_name)
    except Exception as exc:
        raise SolidWorksExportError(
            f"Не удалось назначить материал '{material.name}' детали SolidWorks. "
            "Проверьте доступ к библиотеке материалов SolidWorks."
        ) from exc

    # These properties are supplemental: the native material assignment above
    # is what SolidWorks uses for the material tree and mass properties.
    try:
        manager = model.Extension.CustomPropertyManager("")
        manager.Add2("Материал", 30, material.name)
        manager.Add2("Плотность, кг/м³", 30, str(material.density_kg_m3))
    except Exception:
        LOGGER.debug("SolidWorks did not accept supplemental material metadata.", exc_info=True)


def _active_configuration_name(model) -> str:
    """Return the exact active configuration for a part material assignment."""
    try:
        configuration = model.ConfigurationManager.ActiveConfiguration
        if configuration is not None and configuration.Name:
            return str(configuration.Name)
    except Exception:
        LOGGER.debug("SolidWorks did not expose an active configuration.", exc_info=True)
    # Empty is the SolidWorks API fallback when a minimal template has no
    # available ConfigurationManager object.
    return ""


def available_materials(material_library: str | Path) -> tuple[str, ...]:
    """Return material names from a user-selected SolidWorks .sldmat file."""
    library = Path(material_library)
    try:
        root = ElementTree.parse(library).getroot()  # noqa: S314 - the user explicitly selects this local CAD library.
        names = tuple(node.attrib["name"] for node in root.iter() if node.tag.endswith("material") and node.attrib.get("name"))
    except (OSError, ElementTree.ParseError) as exc:
        raise SolidWorksMaterialLibraryError("Не удалось прочитать выбранную библиотеку материалов SolidWorks.") from exc
    if not names:
        raise SolidWorksMaterialLibraryError("В выбранной библиотеке SolidWorks нет материалов.")
    return names


def _validate_material_library(material_library: str | Path | None, material_name: str | None) -> Path:
    if not material_library:
        raise SolidWorksMaterialLibraryError("Не выбрана библиотека материалов SolidWorks (.sldmat).")
    library = Path(material_library)
    names = available_materials(library)
    if not material_name or material_name not in names:
        raise SolidWorksMaterialLibraryError("Не выбран материал из библиотеки SolidWorks.")
    return library


def _ensure_material_library_is_configured(api: dict[str, object], sw, library: Path) -> None:
    """Require an existing corporate SolidWorks setup; never alter it."""
    try:
        databases = sw.GetMaterialDatabases()
        configured = tuple(str(database) for database in (databases or ()))
        target = str(library.resolve()).casefold()
        if not any(str(Path(database).resolve()).casefold() == target for database in configured):
            raise SolidWorksMaterialLibraryError(
                "Выбранная библиотека не подключена в SolidWorks. "
                "Добавьте её в Параметры → Расположение файлов → Базы данных материалов."
            )
    except Exception as exc:
        if isinstance(exc, SolidWorksMaterialLibraryError):
            raise
        raise SolidWorksExportError(
            "Не удалось проверить список библиотек материалов SolidWorks."
        ) from exc


def _save(api, model, filename: Path) -> None:
    _flag_methods(model, "ClearSelection2", "EditRebuild3")
    model.ClearSelection2(True)
    model.EditRebuild3()
    version = api["Convert"].ToInt32(api["const"]["save_version"].swSaveAsCurrentVersion)
    options = api["Convert"].ToInt32(api["const"]["save_options"].swSaveAsOptions_Silent)
    if hasattr(model, "_FlagAsMethod"):
        _flag_methods(model, "SaveAs3")
        model.SaveAs3(str(filename), version, options)
    else:
        extension = model.Extension
        _flag_methods(extension, "SaveAs")
        extension.SaveAs(str(filename), version, options, None)
    if not filename.exists():
        raise SolidWorksExportError(f"SolidWorks не сохранил файл {filename.name}.")


def _matrix(beam: Beam3D) -> tuple[float, ...]:
    """Map PalletLab's X/Y/Z to the proven SolidWorks assembly axes.

    PalletLab: X — length, Y — width, Z — height.
    SolidWorks template: X — length, Y — height, negative Z — width.
    The local Z axis of every generated part is its long edge.
    """
    if beam.orientation == "length":
        # Beam spans the pallet's X direction.
        # The local cross-width axis points into +Z, so all longitudinal
        # beams use positive SolidWorks Z coordinates.  The local height axis
        # is inverted to keep the transformation right-handed.
        axes = ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (1.0, 0.0, 0.0))
        # The part extrusion starts at its local Z=0 face, while a Beam3D
        # coordinate is its centre.  All lengthwise beams start at X=0.
        origin = (0.0, _metres(beam.z), _metres(beam.y))
    else:
        # Beam spans the pallet's Y direction.  Its local Z=0 start face is
        # pinned to SolidWorks Z=0 and the beam grows in the positive Z
        # direction, rather than placing the pallet in negative coordinates.
        axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        # All widthwise beams start at Y=0 (SolidWorks Z=0).
        origin = (_metres(beam.x), _metres(beam.z), 0.0)
    return (*axes[0], *axes[1], *axes[2], *origin, 1.0, 0.0, 0.0, 0.0)


def _create_assembly(api, sw, template: Path, result: PalletResult, parts, filename: Path) -> None:
    _new_document(sw, template, filename.name)
    assembly = api["win32"].GetActiveObject("SldWorks.Application").ActiveDoc
    if assembly is None:
        raise SolidWorksExportError("Не удалось получить сборку SolidWorks.")
    if assembly is None:
        raise SolidWorksExportError("Не удалось получить сборку SolidWorks.")
    placements = []
    for beam in result.beams_3d:
        key = (beam.orientation, beam.size_x, beam.size_y, beam.size_z)
        placements.append((parts[key], _matrix(beam)))
    pythoncom = api["pythoncom"]
    names = api["win32"].VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, tuple(str(path) for path, _ in placements))
    transforms = api["win32"].VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(value for _, matrix in placements for value in matrix))
    coordinate_systems = api["win32"].VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, tuple("" for _ in placements))
    _flag_methods(assembly, "AddComponents3", "EditRebuild3", "ShowNamedView2", "ViewZoomtofit2")
    if assembly.AddComponents3(names, transforms, coordinate_systems) is None:
        raise SolidWorksExportError("SolidWorks не добавил детали в сборку.")
    assembly.EditRebuild3()
    try:
        assembly.ShowNamedView2("", api["Convert"].ToInt32(api["const"]["views"].swIsometricView))
        assembly.ViewZoomtofit2()
    except Exception:
        LOGGER.debug("SolidWorks does not support optional assembly view fitting.", exc_info=True)
    _save(api, assembly, filename)
