"""Export the calculated pallet to native SolidWorks parts and an assembly.

SolidWorks is deliberately imported lazily.  This keeps the main application
usable on workstations where the CAD system is not installed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palletlab.core.models import Beam3D, PalletResult
from palletlab.core.materials import PalletMaterial, get_material


BASE_PLANE_NAME = "Спереди"
SOLIDWORKS_API_DIR = Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist")

class SolidWorksExportError(RuntimeError):
    """A user-facing failure while preparing or exporting a CAD model."""


class SolidWorksTemplateError(SolidWorksExportError):
    """SolidWorks has no usable part or assembly template configured."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        labels = {"part": "детали (.prtdot)", "assembly": "сборки (.asmdot)"}
        super().__init__("Не найден шаблон " + " и ".join(labels[item] for item in missing) + ".")


@dataclass(frozen=True)
class TemplatePaths:
    part: Path
    assembly: Path


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
) -> Path:
    """Create the native parts and assembly; return the newly-created folder."""
    api = _load_solidworks_api()
    try:
        return _export(api, result, Path(parent_directory), configured_templates, get_material(material_id))
    except SolidWorksExportError:
        raise
    except Exception as exc:
        raise SolidWorksExportError(str(exc)) from exc


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


def _export(api: dict[str, object], result: PalletResult, parent_directory: Path, configured_templates, material: PalletMaterial) -> Path:
    sw = api["SldWorks"]()
    if sw is None:
        raise SolidWorksExportError("Не удалось запустить SolidWorks.")
    sw.Visible = True
    templates = _resolve_templates(api, sw, configured_templates)
    output = create_output_directory(parent_directory, result)

    groups: dict[tuple[str, float, float, float], list[Beam3D]] = defaultdict(list)
    for beam in result.beams_3d:
        groups[(beam.orientation, beam.size_x, beam.size_y, beam.size_z)].append(beam)

    parts: dict[tuple[str, float, float, float], Path] = {}
    for index, (key, beams) in enumerate(groups.items(), start=1):
        orientation, size_x, size_y, size_z = key
        length, cross_width = (size_y, size_x) if orientation == "width" else (size_x, size_y)
        filename = output / f"Beam_{index}_{_format_number(length)}x{_format_number(cross_width)}x{_format_number(size_z)}.SLDPRT"
        _create_beam(api, sw, templates.part, material, length, cross_width, size_z, filename)
        parts[key] = filename

    assembly_file = output / f"Pallet_{_format_number(result.pallet_length)}x{_format_number(result.pallet_width)}.SLDASM"
    _create_assembly(api, sw, templates.assembly, result, parts, assembly_file)
    return output


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


def _create_beam(api, sw, template: Path, material: PalletMaterial, length: float, width: float, height: float, filename: Path) -> None:
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
    _apply_material(model, material)
    _save(api, model, filename)


def _apply_material(model, material: PalletMaterial) -> None:
    """Assign PalletLab's native material and always preserve readable metadata."""
    try:
        model.Extension.SetMaterialPropertyName2("", "", material.solidworks_name)
    except Exception:
        pass
    try:
        manager = model.Extension.CustomPropertyManager("")
        manager.Add2("Материал", 30, material.name)
        manager.Add2("Плотность, кг/м³", 30, str(material.density_kg_m3))
    except Exception:
        pass


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
        axes = ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        # The part extrusion starts at its local Z=0 face, while a Beam3D
        # coordinate is its centre.  All lengthwise beams start at X=0.
        origin = (0.0, _metres(beam.z), -_metres(beam.y))
    else:
        # Beam spans the pallet's Y direction, which is -Z in the template.
        axes = ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
        # All widthwise beams start at Y=0 (SolidWorks Z=0).  Together with
        # the branch above this pins the pallet's shared corner to (0, 0, 0).
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
        pass
    _save(api, assembly, filename)
