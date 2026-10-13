"""Интерактивная проверка поиска опорных граней в STEP-модели.

Запуск:
    python test_scripts/step_support_detector.py
    python test_scripts/step_support_detector.py path\\to\\machine.step

Левой кнопкой мыши выберите *плоскую* нижнюю грань одной опоры. Скрипт
подсветит все плоские грани, лежащие в той же плоскости. Повторный клик по
другой грани запускает поиск заново; клавиша R сбрасывает подсветку.

Это намеренно отдельный прототип: он использует тот же PyVista, что и
приложение, но добавляет OpenCascade (пакет cadquery-ocp) для точной
топологии STEP. В VTK передаётся только отображение; решение о совпадении
опор принимается по B-Rep геометрии OpenCascade.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from tkinter import Tk, filedialog

import numpy as np
import pyvista as pv

try:
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.Bnd import Bnd_Box
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from vtkmodules.vtkRenderingCore import vtkCellPicker
except ImportError as error:  # pragma: no cover - depends on local CAD runtime
    raise SystemExit(
        "Не найден OpenCascade. Установите зависимости проекта: "
        "pip install -r requirements.txt"
    ) from error


DEFAULT_RGB = np.array((184, 194, 204), dtype=np.uint8)
REFERENCE_RGB = np.array((255, 176, 26), dtype=np.uint8)
SUPPORT_RGB = np.array((230, 41, 51), dtype=np.uint8)
PARALLEL_COSINE = math.cos(math.radians(0.5))
# Bump whenever the visual mesh recipe changes, so old coarse meshes are not
# reused after an improvement to cylindrical and other curved surfaces.
CACHE_VERSION = 3
MESH_ANGULAR_DEFLECTION = math.radians(12.0)


@dataclass(frozen=True)
class StepFace:
    """One B-Rep face and exact data needed for the support-plane test."""

    index: int
    point: np.ndarray | None
    normal: np.ndarray | None


class ConsoleProgress:
    """Small dependency-free progress bar for long STEP conversions."""

    def __init__(self) -> None:
        self._last_percent = -1
        self._last_label = ""

    def update(self, fraction: float, label: str) -> None:
        percent = max(0, min(100, round(fraction * 100)))
        if percent == self._last_percent and label == self._last_label:
            return
        complete = percent // 5
        bar = "#" * complete + "-" * (20 - complete)
        print(f"\r[{bar}] {percent:3d}% {label:<48}", end="", flush=True)
        self._last_percent = percent
        self._last_label = label

    def finish(self, label: str = "Ready") -> None:
        self.update(1.0, label)
        print()


def choose_step_file() -> Path | None:
    """Ask for a STEP file without bringing a second persistent GUI toolkit in."""
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askopenfilename(
        title="Выберите STEP-модель",
        filetypes=[("STEP models", "*.step *.stp"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(selected) if selected else None


def read_step(filename: Path):
    reader = STEPControl_Reader()
    result = reader.ReadFile(str(filename))
    if result != IFSelect_RetDone:
        raise RuntimeError(f"OpenCascade не смог прочитать STEP-файл: {filename}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise RuntimeError("STEP-файл прочитан, но не содержит геометрии.")
    return shape


def planar_face_geometry(face) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Return a point and outward normal for a planar B-Rep face."""
    surface = BRepAdaptor_Surface(face, True)
    if surface.GetType() != GeomAbs_Plane:
        return None, None
    plane = surface.Plane()
    location = plane.Location()
    direction = plane.Axis().Direction()
    normal = np.array((direction.X(), direction.Y(), direction.Z()), dtype=float)
    if face.Orientation() == TopAbs_REVERSED:
        normal *= -1.0
    return np.array((location.X(), location.Y(), location.Z()), dtype=float), normal


def face_triangles(face) -> tuple[np.ndarray, list[int]] | None:
    """Convert an already-generated OpenCascade triangulation to VTK cells."""
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face, location)
    if triangulation is None or triangulation.NbTriangles() == 0:
        return None

    transformation = location.Transformation()
    points = []
    for node_index in range(1, triangulation.NbNodes() + 1):
        point = triangulation.Node(node_index).Transformed(transformation)
        points.append((point.X(), point.Y(), point.Z()))

    cells: list[int] = []
    reversed_face = face.Orientation() == TopAbs_REVERSED
    for triangle_index in range(1, triangulation.NbTriangles() + 1):
        first, second, third = triangulation.Triangle(triangle_index).Get()
        if reversed_face:
            second, third = third, second
        cells.extend((3, first - 1, second - 1, third - 1))
    return np.asarray(points), cells


def shape_diagonal(shape) -> float:
    """Get a finite model scale without an extra tessellation pass.

    Some exported STEP assemblies contain unbounded construction geometry. In
    that case OpenCascade's generic bounding box can contain ±1e100 sentinels;
    using that value as a mesh tolerance turns cylinders into squares.
    """
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if not box.IsVoid():
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        diagonal = float(np.linalg.norm((xmax - xmin, ymax - ymin, zmax - zmin)))
        if math.isfinite(diagonal) and 1e-9 < diagonal < 1e12:
            return diagonal

    # A model's topological vertices are finite even if a helper surface is
    # unbounded. This is linear in vertices and vastly cheaper than meshing.
    minimum = np.full(3, np.inf)
    maximum = np.full(3, -np.inf)
    explorer = TopExp_Explorer(shape, TopAbs_VERTEX)
    while explorer.More():
        vertex = TopoDS.Vertex_s(explorer.Current())
        point = BRep_Tool.Pnt_s(vertex).Transformed(vertex.Location().Transformation())
        coordinates = np.array((point.X(), point.Y(), point.Z()), dtype=float)
        minimum = np.minimum(minimum, coordinates)
        maximum = np.maximum(maximum, coordinates)
        explorer.Next()
    diagonal = float(np.linalg.norm(maximum - minimum))
    if math.isfinite(diagonal) and diagonal > 1e-9:
        return diagonal
    raise RuntimeError("Не удалось определить конечный габарит STEP-модели.")


def build_view(shape, deflection: float, progress=None) -> tuple[list[StepFace], pv.PolyData]:
    """Mesh the shape once and attach the B-Rep face id to each VTK cell."""
    # The first implementation created a mesher and actor for every face.
    # That made assemblies slow and drew every triangle boundary.
    if progress:
        progress(0.0, "Counting B-Rep faces")
    face_count = 0
    counter = TopExp_Explorer(shape, TopAbs_FACE)
    while counter.More():
        face_count += 1
        counter.Next()

    if progress:
        progress(0.02, "Building OpenCascade display mesh")
    # Linear deflection controls size-based refinement; angular deflection is
    # equally important for pipes.  0.5 radian made small-radius cylinders
    # look close to square even where their linear deviation was acceptable.
    mesher = BRepMesh_IncrementalMesh(shape, deflection, False, MESH_ANGULAR_DEFLECTION, True)
    mesher.Perform()
    faces: list[StepFace] = []
    point_blocks: list[np.ndarray] = []
    cells: list[int] = []
    cell_face_indices: list[int] = []
    point_offset = 0
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    index = 0
    processed = 0
    report_every = max(1, face_count // 100)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        triangles = face_triangles(face)
        if triangles is not None:
            face_points, face_cells = triangles
            point, normal = planar_face_geometry(face)
            item = StepFace(index, point, normal)
            faces.append(item)
            point_blocks.append(face_points)
            for offset in range(0, len(face_cells), 4):
                cells.extend((3, face_cells[offset + 1] + point_offset,
                              face_cells[offset + 2] + point_offset,
                              face_cells[offset + 3] + point_offset))
                cell_face_indices.append(index)
            point_offset += len(face_points)
            index += 1
        explorer.Next()
        processed += 1
        if progress and (processed % report_every == 0 or processed == face_count):
            progress(0.02 + 0.98 * processed / max(face_count, 1),
                     f"Converting faces: {processed:,}/{face_count:,}")
    if not faces:
        raise RuntimeError("В STEP-модели не найдено отображаемых граней.")
    mesh = pv.PolyData(np.vstack(point_blocks), np.asarray(cells))
    mesh.cell_data["step_face_index"] = np.asarray(cell_face_indices, dtype=np.int32)
    # We already duplicate points at B-Rep face boundaries, so this smooths a
    # cylindrical face without rounding over the sharp edge into a flat face.
    mesh.compute_normals(cell_normals=False, point_normals=True, inplace=True)
    return faces, mesh


def cache_path_for(filename: Path) -> Path:
    """Keep reusable visual caches out of the source STEP-model directory."""
    key = hashlib.sha256(str(filename).encode("utf-8")).hexdigest()[:24]
    cache_root = Path(__file__).resolve().parent / ".step_cache"
    return cache_root / f"step-view-v{CACHE_VERSION}-{key}.npz"


def load_cached_view(filename: Path) -> tuple[list[StepFace], pv.PolyData, float] | None:
    """Load mesh and B-Rep plane descriptors without opening OpenCascade STEP."""
    cache_path = cache_path_for(filename)
    if not cache_path.is_file():
        return None
    source = filename.stat()
    try:
        with np.load(cache_path, allow_pickle=False) as cached:
            if int(cached["source_size"]) != source.st_size or int(cached["source_mtime_ns"]) != source.st_mtime_ns:
                return None
            mesh = pv.PolyData(np.asarray(cached["points"]), np.asarray(cached["cells"]))
            mesh.cell_data["step_face_index"] = np.asarray(cached["cell_face_indices"], dtype=np.int32)
            points = np.asarray(cached["face_points"], dtype=float)
            normals = np.asarray(cached["face_normals"], dtype=float)
            faces = [
                StepFace(index, None if np.isnan(point).any() else point,
                         None if np.isnan(normal).any() else normal)
                for index, (point, normal) in enumerate(zip(points, normals))
            ]
            return faces, mesh, float(cached["deflection"])
    except (KeyError, OSError, ValueError, TypeError):
        # A partial or obsolete cache must never prevent loading the STEP file.
        return None


def save_cached_view(filename: Path, faces: list[StepFace], mesh: pv.PolyData, deflection: float) -> None:
    """Persist only data needed for rendering and support-plane queries."""
    cache_path = cache_path_for(filename)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    source = filename.stat()
    face_points = np.array(
        [item.point if item.point is not None else (np.nan, np.nan, np.nan) for item in faces], dtype=float
    )
    face_normals = np.array(
        [item.normal if item.normal is not None else (np.nan, np.nan, np.nan) for item in faces], dtype=float
    )
    temporary = cache_path.with_suffix(".tmp.npz")
    np.savez(
        temporary,
        source_size=np.uint64(source.st_size),
        source_mtime_ns=np.uint64(source.st_mtime_ns),
        deflection=np.float64(deflection),
        points=mesh.points,
        cells=mesh.faces,
        cell_face_indices=mesh.cell_data["step_face_index"],
        face_points=face_points,
        face_normals=face_normals,
    )
    temporary.replace(cache_path)


def is_coplanar_support(candidate: StepFace, reference: StepFace, tolerance: float) -> bool:
    if candidate.point is None or candidate.normal is None:
        return False
    # Directions may be reversed by a CAD exporter; the supporting plane is
    # still the same physical plane, so accept both signs of its normal.
    aligned = abs(float(np.dot(candidate.normal, reference.normal))) >= PARALLEL_COSINE
    distance = abs(float(np.dot(candidate.point - reference.point, reference.normal)))
    return aligned and distance <= tolerance


def run(filename: Path, plane_tolerance: float | None, deflection: float | None) -> None:
    # An explicit mesh tolerance requests a fresh conversion. The default path
    # first attempts a warm cache and therefore avoids both STEP parsing and
    # B-Rep tessellation on subsequent openings.
    progress = ConsoleProgress()
    if deflection is None:
        progress.update(0.0, "Looking for a warm cache")
    cached = None if deflection is not None else load_cached_view(filename)
    if cached is not None:
        faces, mesh, mesh_deflection = cached
        cache_state = "warm cache"
        progress.finish("Loaded from warm cache")
    else:
        progress.update(0.0, "Reading STEP file (OpenCascade does not expose byte progress)")
        shape = read_step(filename)
        diagonal = shape_diagonal(shape)
        mesh_deflection = deflection if deflection is not None else max(diagonal * 1e-4, 1e-9)
        faces, mesh = build_view(
            shape,
            mesh_deflection,
            lambda fraction, label: progress.update(0.03 + fraction * 0.96, label),
        )
        progress.update(0.99, "Saving warm cache")
        save_cached_view(filename, faces, mesh, mesh_deflection)
        cache_state = "fresh STEP import; cache saved"
        progress.finish()
    diagonal = float(np.linalg.norm((mesh.bounds[1] - mesh.bounds[0], mesh.bounds[3] - mesh.bounds[2],
                                     mesh.bounds[5] - mesh.bounds[4])))
    tolerance = plane_tolerance if plane_tolerance is not None else max(diagonal * 1e-6, 1e-9)

    plotter = pv.Plotter(window_size=(1440, 920), title=f"STEP support detector — {filename.name}")
    plotter.set_background("#171b20")
    colors = np.tile(DEFAULT_RGB, (mesh.n_cells, 1))
    mesh.cell_data["face_colors"] = colors
    model_actor = plotter.add_mesh(
        mesh, scalars="face_colors", rgb=True, show_edges=False,
        # Do not enable smooth_shading here: PyVista then makes a private mesh
        # copy and later colour updates are invisible on the rendered actor.
        smooth_shading=False,
        pickable=True, name="step-model",
    )
    plotter.add_axes(line_width=1)
    plotter.add_text(
        "Left click: choose a flat support face\nR: reset selection\n"
        f"Plane tolerance: {tolerance:.6g}; mesh: {mesh_deflection:.6g} STEP units",
        position="upper_left",
        font_size=11,
        color="white",
        name="status",
    )

    def reset() -> None:
        colors[:] = DEFAULT_RGB
        update_colours()
        mesh.Modified()
        plotter.add_text(
            "Left click: choose a flat support face\nR: reset selection\n"
            f"Plane tolerance: {tolerance:.6g}; mesh: {mesh_deflection:.6g} STEP units",
            position="upper_left", font_size=11, color="white", name="status",
        )
        plotter.render()

    def select(reference: StepFace) -> None:
        if reference.point is None or reference.normal is None:
            plotter.add_text(
                "Choose a flat face: a curved face cannot define a support plane.",
                position="upper_left", font_size=11, color="#ffcc66", name="status",
            )
            plotter.render()
            return
        matched = [item for item in faces if is_coplanar_support(item, reference, tolerance)]
        colors[:] = DEFAULT_RGB
        face_ids = mesh.cell_data["step_face_index"]
        for item in matched:
            colors[face_ids == item.index] = SUPPORT_RGB
        colors[face_ids == reference.index] = REFERENCE_RGB
        update_colours()
        plotter.add_text(
            f"Coplanar support faces: {len(matched)}\n"
            f"Selected face: {reference.index}; tolerance: {tolerance:.6g}",
            position="upper_left", font_size=11, color="white", name="status",
        )
        print(f"Selected face {reference.index}; coplanar support faces: {[item.index for item in matched]}")
        plotter.render()

    def update_colours() -> None:
        """Tell VTK that the RGB cell array changed in place."""
        colour_array = mesh.cell_data["face_colors"]
        colour_array[:] = colors
        mesh.GetCellData().GetArray("face_colors").Modified()
        mesh.GetCellData().Modified()
        mesh.Modified()
        model_actor.mapper.Update()

    cell_picker = vtkCellPicker()
    cell_picker.SetTolerance(0.0005)

    def pick_face(*_args) -> None:
        x, y = plotter.iren.get_event_position()
        cell_picker.Pick(x, y, 0, plotter.renderer)
        cell_id = cell_picker.GetCellId()
        if 0 <= cell_id < mesh.n_cells:
            select(faces[int(mesh.cell_data["step_face_index"][cell_id])])

    plotter.iren.add_observer("LeftButtonPressEvent", pick_face)
    plotter.add_key_event("r", reset)
    plotter.view_isometric()
    plotter.reset_camera()
    print(f"Loaded {len(faces)} B-Rep faces / {mesh.n_cells} display triangles from {filename} ({cache_state})")
    print(f"Coplanarity tolerance: {tolerance:.6g} STEP units")
    plotter.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find coplanar support faces in a STEP model.")
    parser.add_argument("step_file", nargs="?", type=Path, help="Path to .step or .stp file")
    parser.add_argument(
        "--plane-tolerance", type=float, default=None,
        help="Coplanarity tolerance in the model's STEP units (default: model diagonal × 1e-6).",
    )
    parser.add_argument(
        "--deflection", type=float, default=None,
        help="Tessellation deflection in STEP units (default: model diagonal × 1e-4).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    filename = args.step_file or choose_step_file()
    if filename is None:
        return
    filename = filename.expanduser().resolve()
    if not filename.is_file():
        raise SystemExit(f"Файл не найден: {filename}")
    if filename.suffix.lower() not in {".step", ".stp"}:
        raise SystemExit("Нужен файл STEP с расширением .step или .stp")
    if args.plane_tolerance is not None and args.plane_tolerance <= 0:
        raise SystemExit("--plane-tolerance должен быть больше нуля.")
    if args.deflection is not None and args.deflection <= 0:
        raise SystemExit("--deflection должен быть больше нуля.")
    run(filename, args.plane_tolerance, args.deflection)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1) from error
