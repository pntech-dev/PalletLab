"""Export the calculated pallet to native KOMPAS-3D parts and an assembly."""

from __future__ import annotations

from collections import defaultdict
import logging
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palletlab.core.models import Beam3D, PalletResult
from palletlab.core.materials import PalletMaterial, get_material


LOGGER = logging.getLogger(__name__)


class KompasExportError(RuntimeError):
    """A user-facing failure while preparing or exporting a KOMPAS model."""


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
    return output


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
