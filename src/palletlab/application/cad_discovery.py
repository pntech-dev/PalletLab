"""Find usable SolidWorks defaults without starting or modifying the CAD application."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from palletlab.exporters.solidworks import SolidWorksMaterialLibraryError, available_materials

LOGGER = logging.getLogger(__name__)


def _running_solidworks_templates() -> dict[str, str]:
    """Read each default from the running COM instance, without starting CAD.

    These preference IDs are documented by SolidWorks' API example; using
    COM integers avoids a dependency on interop DLLs at a fixed install path.
    """
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            app = win32com.client.GetActiveObject("SldWorks.Application")
            flag = getattr(app, "_FlagAsMethod", None)
            if flag is not None:
                flag("GetUserPreferenceStringValue")
            result: dict[str, str] = {}
            for field, preference in (("partTemplate", 8), ("assemblyTemplate", 9), ("drawingTemplate", 10)):
                try:
                    value = app.GetUserPreferenceStringValue(preference)
                    result[field] = value if isinstance(value, str) else ""
                except Exception:
                    # One unsupported preference must not hide the others.
                    LOGGER.debug("Unable to read SolidWorks template preference %s", field, exc_info=True)
            return result
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        # SolidWorks is optional and may not be running or registered.
        return {}


def _registry_solidworks_templates() -> dict[str, str]:
    """Read the newest per-user SOLIDWORKS settings without modifying the registry.

    These registry value names are not a documented public API, so absence,
    access failures and unsupported versions all fall back to other sources.
    """
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SolidWorks", 0, winreg.KEY_READ) as root:
            versions: list[tuple[int, str]] = []
            for index in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, index)
                match = re.fullmatch(r"SOLIDWORKS\s+(20\d{2})", name, re.IGNORECASE)
                if match:
                    versions.append((int(match.group(1)), name))
            if not versions:
                return {}
            _, newest = max(versions)
            with winreg.OpenKey(root, newest + r"\Document Templates", 0, winreg.KEY_READ) as key:
                result: dict[str, str] = {}
                for field, name in (
                    ("partTemplate", "Default Part Template"),
                    ("assemblyTemplate", "Default Assy Template"),
                    ("drawingTemplate", "Default Drawing Template"),
                ):
                    try:
                        value, kind = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str):
                        result[field] = value
                return result
    except (ImportError, OSError):
        return {}


def _valid_path(value: object, suffix: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(os.path.expandvars(value.strip()))
    try:
        return path if path.suffix.casefold() == suffix and path.is_file() else None
    except (OSError, ValueError):
        return None


def _template_folders(program_data: Path, program_files: Path) -> list[Path]:
    root = program_data / "SOLIDWORKS"
    try:
        versions = sorted((path for path in root.glob("SOLIDWORKS*") if path.is_dir()), key=lambda p: p.name.casefold(), reverse=True)
    except OSError:
        versions = []
    folders = [version / "templates" for version in versions]
    install = program_files / "SOLIDWORKS Corp" / "SOLIDWORKS" / "lang"
    folders.extend(install / language / "Tutorial" for language in ("russian", "english"))
    return folders


def _find_template(folders: list[Path], suffix: str) -> Path | None:
    for folder in folders:
        try:
            matches = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() == suffix), key=lambda p: p.name.casefold())
        except OSError:
            continue
        # Prefer the standard English file name. Avoid silently choosing between
        # several custom templates when no default is identifiable.
        standard = {".prtdot": "part", ".asmdot": "assembly", ".drwdot": "drawing"}[suffix]
        preferred = next((p for p in matches if p.stem.casefold() == standard), None)
        if preferred:
            return preferred
        if len(matches) == 1:
            return matches[0]
    return None


def discover_solidworks_paths(current: object, *, program_data: Path | None = None,
                               program_files: Path | None = None, defaults: dict[str, str] | None = None,
                               registry_defaults: dict[str, str] | None = None) -> dict[str, Any]:
    """Find configured or standard files; retain no unverified guessed paths."""
    existing = current if isinstance(current, dict) else {}
    defaults = _running_solidworks_templates() if defaults is None else defaults
    registry_defaults = _registry_solidworks_templates() if registry_defaults is None else registry_defaults
    data = program_data or Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    files = program_files or Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    folders = _template_folders(data, files)
    result: dict[str, Any] = {"configuredPaths": {}}
    for key, suffix in (
        ("partTemplate", ".prtdot"),
        ("assemblyTemplate", ".asmdot"),
        ("drawingTemplate", ".drwdot"),
    ):
        # A configured SolidWorks default is authoritative even when it points
        # to a missing file; do not silently substitute an older saved template.
        if key in defaults:
            path = _valid_path(defaults[key], suffix)
            source = "solidworks" if path else "invalid_default"
        elif key in registry_defaults:
            path = _valid_path(registry_defaults[key], suffix)
            source = "registry" if path else "invalid_default"
        else:
            path = _valid_path(existing.get(key), suffix)
            source = "saved" if path else "not_found"
            if path is None:
                path = _find_template(folders, suffix)
                if path:
                    source = "standard"
        result[key] = str(path) if path else None
        if source == "invalid_default":
            configured = defaults.get(key) if key in defaults else registry_defaults.get(key)
            if isinstance(configured, str) and configured.strip():
                result["configuredPaths"][key] = configured
        result.setdefault("sources", {})[key] = source
    material_dirs = [files / "SOLIDWORKS Corp" / "SOLIDWORKS" / "lang" / language / "sldmaterials"
                     for language in ("russian", "english")]
    candidates = [_valid_path(existing.get("materialLibrary"), ".sldmat")]
    candidates.extend(directory / "solidworks materials.sldmat" for directory in material_dirs)
    result["materialLibrary"] = None
    result["materials"] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            names = available_materials(candidate)
        except SolidWorksMaterialLibraryError:
            continue
        if names:
            result["materialLibrary"] = str(candidate)
            result["materials"] = list(names)
            break
    return result
