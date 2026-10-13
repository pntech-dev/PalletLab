"""STEP import and support-face detection used by the model-based pallet flow."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv

from palletlab.core.models import DirectionInput
from palletlab.core.calculator import round_to_fifty, round_up_to_five

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
except ImportError as error:  # pragma: no cover - depends on the CAD runtime
    raise RuntimeError(
        "Не найден OpenCascade. Установите зависимости проекта: pip install -r requirements.txt"
    ) from error


DEFAULT_RGB = np.array((184, 194, 204), dtype=np.uint8)
REFERENCE_RGB = np.array((255, 176, 26), dtype=np.uint8)
SUPPORT_RGB = np.array((230, 41, 51), dtype=np.uint8)
PARALLEL_COSINE = math.cos(math.radians(0.5))
HORIZONTAL_COSINE = math.cos(math.radians(2.0))
CACHE_VERSION = 5


@dataclass(frozen=True)
class StepFace:
    """Exact planar data for a displayed B-Rep face."""

    index: int
    point: np.ndarray | None
    normal: np.ndarray | None


@dataclass(frozen=True)
class ImportedStepModel:
    """Display mesh plus the B-Rep information required for face selection."""

    mesh: pv.PolyData
    edges: pv.PolyData
    faces: tuple[StepFace, ...]
    plane_tolerance: float
    source_path: Path


def cache_directory() -> Path:
    """Return PalletLab's per-user cache directory without touching a STEP folder."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".cache"
    return root / "PalletLab" / "step_cache"


def _cache_path(source_path: Path) -> Path:
    key = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:24]
    return cache_directory() / f"step-view-v{CACHE_VERSION}-{key}.npz"


def _load_cached_model(source_path: Path) -> ImportedStepModel | None:
    path = _cache_path(source_path)
    if not path.is_file():
        return None
    source = source_path.stat()
    try:
        with np.load(path, allow_pickle=False) as cached:
            if int(cached["source_size"]) != source.st_size or int(cached["source_mtime_ns"]) != source.st_mtime_ns:
                return None
            mesh = pv.PolyData(np.asarray(cached["points"]), np.asarray(cached["cells"]))
            mesh.cell_data["step_face_index"] = np.asarray(cached["cell_face_indices"], dtype=np.int32)
            points = np.asarray(cached["face_points"], dtype=float)
            normals = np.asarray(cached["face_normals"], dtype=float)
            faces = tuple(
                StepFace(index, None if np.isnan(point).any() else point,
                         None if np.isnan(normal).any() else normal)
                for index, (point, normal) in enumerate(zip(points, normals))
            )
            # Feature contours are VTK line cells, not polygon faces.
            edges = pv.PolyData(np.asarray(cached["edge_points"]), lines=np.asarray(cached["edge_cells"]))
            diagonal = float(np.linalg.norm((mesh.bounds[1] - mesh.bounds[0], mesh.bounds[3] - mesh.bounds[2], mesh.bounds[5] - mesh.bounds[4])))
            return ImportedStepModel(mesh, edges, faces, max(diagonal * 1e-6, 1e-9), source_path)
    except (KeyError, OSError, ValueError, TypeError):
        return None


def load_cached_step_model(filename: str | Path) -> ImportedStepModel | None:
    """Load a completed cache without opening OpenCascade or tessellating again."""
    return _load_cached_model(Path(filename).expanduser().resolve())


def _save_cached_model(model: ImportedStepModel) -> None:
    """Persist only display geometry and exact support-plane descriptors."""
    path = _cache_path(model.source_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        source = model.source_path.stat()
        temporary = path.with_suffix(".tmp.npz")
        np.savez(
            temporary,
            source_size=np.uint64(source.st_size), source_mtime_ns=np.uint64(source.st_mtime_ns),
            points=model.mesh.points, cells=model.mesh.faces,
            edge_points=model.edges.points, edge_cells=model.edges.lines,
            cell_face_indices=model.mesh.cell_data["step_face_index"],
            face_points=np.asarray([face.point if face.point is not None else (np.nan, np.nan, np.nan) for face in model.faces]),
            face_normals=np.asarray([face.normal if face.normal is not None else (np.nan, np.nan, np.nan) for face in model.faces]),
        )
        temporary.replace(path)
    except OSError:
        # Caching is only an acceleration. A read-only profile must not stop import.
        return


def _planar_face_geometry(face) -> tuple[np.ndarray | None, np.ndarray | None]:
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


def _surface_centroid(points: np.ndarray, cells: list[int]) -> np.ndarray:
    """Return the area-weighted centroid of tessellated face triangles.

    A plane's origin is arbitrary in STEP.  In particular, it is not the
    centre of a circular foot, so support coordinates must be derived from the
    actual face surface instead.
    """
    weighted = np.zeros(3)
    total_area = 0.0
    for offset in range(0, len(cells), 4):
        first, second, third = cells[offset + 1:offset + 4]
        triangle = points[[first, second, third]]
        area = float(np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0]))) / 2.0
        if area > 0:
            weighted += area * triangle.mean(axis=0)
            total_area += area
    if total_area <= 0:
        return points.mean(axis=0)
    return weighted / total_area


def _face_triangles(face) -> tuple[np.ndarray, list[int]] | None:
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


def _shape_diagonal(shape) -> float:
    """Determine model scale without trusting unbounded helper geometry."""
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if not box.IsVoid():
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        diagonal = float(np.linalg.norm((xmax - xmin, ymax - ymin, zmax - zmin)))
        if math.isfinite(diagonal) and 1e-9 < diagonal < 1e12:
            return diagonal
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
    if not math.isfinite(diagonal) or diagonal <= 1e-9:
        raise ValueError("Не удалось определить габарит STEP-модели.")
    return diagonal


def load_step_model(filename: str | Path, progress=None) -> ImportedStepModel:
    """Read a STEP file once and retain a mapping between triangles and B-Rep faces."""
    source_path = Path(filename).expanduser().resolve()
    if source_path.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("Выберите STEP-модель с расширением .step или .stp.")
    if not source_path.is_file():
        raise ValueError(f"Файл не найден: {source_path}")
    if progress:
        progress(2, "Проверяем кэш модели…")
    cached = _load_cached_model(source_path)
    if cached is not None:
        if progress:
            progress(100, "Модель загружена из кэша.")
        return cached
    if progress:
        progress(5, "Читаем STEP-файл…")
    reader = STEPControl_Reader()
    if reader.ReadFile(str(source_path)) != IFSelect_RetDone:
        raise ValueError(f"OpenCascade не смог прочитать STEP-файл: {source_path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("STEP-файл прочитан, но не содержит геометрии.")
    if progress:
        progress(10, "Подготавливаем геометрию…")
    # This is the same scale-sensitive tessellation recipe proven in
    # test_scripts/step_support_detector.py.
    deflection = max(_shape_diagonal(shape) * 1e-4, 1e-9)
    BRepMesh_IncrementalMesh(shape, deflection, False, math.radians(12.0), True).Perform()
    counter = TopExp_Explorer(shape, TopAbs_FACE)
    face_count = 0
    while counter.More():
        face_count += 1
        counter.Next()
    faces: list[StepFace] = []
    point_blocks: list[np.ndarray] = []
    cells: list[int] = []
    cell_face_indices: list[int] = []
    point_offset = 0
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    index = 0
    processed = 0
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        triangles = _face_triangles(face)
        if triangles is not None:
            face_points, face_cells = triangles
            point, normal = _planar_face_geometry(face)
            if point is not None:
                # Keep a point on the plane, but make it the real face centre
                # rather than the arbitrary OpenCascade plane origin.
                point = _surface_centroid(face_points, face_cells)
            faces.append(StepFace(index, point, normal))
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
        if progress and (processed % max(1, face_count // 100) == 0 or processed == face_count):
            progress(10 + round(85 * processed / max(1, face_count)), f"Преобразуем грани: {processed:,}/{face_count:,}")
    if not faces:
        raise ValueError("В STEP-модели не найдено отображаемых граней.")
    mesh = pv.PolyData(np.vstack(point_blocks), np.asarray(cells))
    mesh.cell_data["step_face_index"] = np.asarray(cell_face_indices, dtype=np.int32)
    mesh.compute_normals(cell_normals=False, point_normals=True, inplace=True)
    if progress:
        progress(93, "Выделяем рёбра деталей…")
    edges = mesh.extract_feature_edges(
        feature_angle=30, boundary_edges=True, non_manifold_edges=True,
        feature_edges=True, manifold_edges=False,
    )
    diagonal = float(np.linalg.norm((mesh.bounds[1] - mesh.bounds[0], mesh.bounds[3] - mesh.bounds[2], mesh.bounds[5] - mesh.bounds[4])))
    model = ImportedStepModel(mesh, edges, tuple(faces), max(diagonal * 1e-6, 1e-9), source_path)
    if progress:
        progress(96, "Сохраняем кэш модели…")
    _save_cached_model(model)
    if progress:
        progress(100, "Модель готова.")
    return model


def coplanar_supports(model: ImportedStepModel, reference_index: int) -> tuple[StepFace, ...]:
    """Find planar B-Rep faces in the selected support plane, in any orientation."""
    reference = model.faces[reference_index]
    if reference.point is None or reference.normal is None:
        raise ValueError("Выберите плоскую нижнюю грань опоры.")
    return tuple(
        candidate for candidate in model.faces
        if candidate.point is not None and candidate.normal is not None
        and abs(float(np.dot(candidate.normal, reference.normal))) >= PARALLEL_COSINE
        and abs(float(np.dot(candidate.point - reference.point, reference.normal))) <= model.plane_tolerance
    )


def _support_frame(model: ImportedStepModel, reference_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build a stable pallet frame from the selected lower support plane.

    STEP assemblies are often exported with an arbitrary global orientation.
    The face normal nearest the machine centre becomes local +Z, while a
    projected global axis provides repeatable local X/Y directions.
    """
    reference = model.faces[reference_index]
    if reference.point is None or reference.normal is None:
        raise ValueError("Выберите плоскую нижнюю грань опоры.")
    origin = reference.point
    normal = reference.normal / np.linalg.norm(reference.normal)
    centre = np.array(((model.mesh.bounds[0] + model.mesh.bounds[1]) / 2,
                       (model.mesh.bounds[2] + model.mesh.bounds[3]) / 2,
                       (model.mesh.bounds[4] + model.mesh.bounds[5]) / 2))
    # A lower face's CAD orientation is not dependable.  Always point local
    # +Z into the assembly, so the pallet is built below the machine.
    if float(np.dot(centre - origin, normal)) < 0:
        normal *= -1.0
    world_axes = np.eye(3)
    anchor = world_axes[int(np.argmin(np.abs(world_axes @ normal)))]
    x_axis = anchor - np.dot(anchor, normal) * normal
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(normal, x_axis)
    return origin, x_axis, y_axis, normal


def support_axis_coordinate(model: ImportedStepModel, reference_index: int, point: np.ndarray, axis: int) -> float:
    """Project a model point into the selected support plane's X or Y axis."""
    origin, x_axis, y_axis, _normal = _support_frame(model, reference_index)
    return float(np.dot(point - origin, x_axis if axis == 0 else y_axis))


def _support_frame_mesh(source: pv.PolyData, frame: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]) -> pv.PolyData:
    """Copy display geometry into the selected support plane's local frame."""
    origin, x_axis, y_axis, z_axis = frame
    transformed = source.copy(deep=True)
    relative = transformed.points - origin
    transformed.points = np.column_stack((relative @ x_axis, relative @ y_axis, relative @ z_axis))
    return transformed


def _coalesced_beam_positions(values: list[float], tolerance: float, beam_width: float) -> tuple[float, ...]:
    """Choose non-overlapping beam centres for nearby support-face centres.

    Faces sharing a coordinate (within the STEP tolerance) represent several
    feet that one beam can carry.  If two candidate beams would overlap, keep
    the one carrying more feet.  With equal coverage the later candidate is
    farther from the already accepted beam on its left, which leaves the more
    useful clear span for subsequent beams.
    """
    if not values:
        return ()
    values.sort()
    candidates: list[tuple[float, int]] = []
    cluster: list[float] = [values[0]]
    for value in values[1:]:
        if value - cluster[-1] <= tolerance:
            cluster.append(value)
        else:
            candidates.append((sum(cluster) / len(cluster), len(cluster)))
            cluster = [value]
    candidates.append((sum(cluster) / len(cluster), len(cluster)))

    # Production coordinates are whole millimetres.  Merge candidates that
    # collapse to the same manufactured centre before resolving collisions.
    snapped: list[tuple[float, int]] = []
    for position, coverage in candidates:
        centre = float(math.floor(position + 0.5))
        if snapped and centre == snapped[-1][0]:
            previous_centre, previous_coverage = snapped[-1]
            snapped[-1] = (previous_centre, previous_coverage + coverage)
        else:
            snapped.append((centre, coverage))

    selected: list[tuple[float, int]] = []
    for candidate in snapped:
        if not selected or candidate[0] - selected[-1][0] >= beam_width - tolerance:
            selected.append(candidate)
            continue
        previous = selected[-1]
        # In a tie replace the right candidate: it maximises the distance from
        # the preceding accepted beam and avoids arbitrary result changes.
        if candidate[1] >= previous[1]:
            selected[-1] = candidate
    return tuple(position for position, _coverage in selected)


def edge_to_support_center_distance(
    model: ImportedStepModel, boundary_index: int, support_index: int, axis: int, reference_index: int,
) -> float:
    """Measure a pallet-axis distance from a bounding plane to a foot centre."""
    boundary = model.faces[boundary_index]
    support = model.faces[support_index]
    if boundary.point is None or boundary.normal is None:
        raise ValueError("Грань габарита должна быть плоской.")
    if support.point is None or support.normal is None:
        raise ValueError("Грань опоры должна быть плоской.")
    _origin, x_axis, y_axis, _z_axis = _support_frame(model, reference_index)
    if abs(float(np.dot(boundary.normal, x_axis if axis == 0 else y_axis))) < HORIZONTAL_COSINE:
        direction = "X" if axis == 0 else "Y"
        raise ValueError(f"Грань габарита должна быть перпендикулярна оси {direction}.")
    boundary_coordinate = support_axis_coordinate(model, reference_index, boundary.point, axis)
    support_coordinate = support_axis_coordinate(model, reference_index, support.point, axis)
    return float(math.floor(abs(support_coordinate - boundary_coordinate) + 0.5))


def pallet_inputs_from_supports(
    model: ImportedStepModel,
    supports: tuple[StepFace, ...],
    *,
    length_beam_height: float,
    length_beam_width: float,
    width_beam_height: float,
    width_beam_width: float,
    length_margin_start: float,
    length_margin_end: float,
    width_margin_start: float,
    width_margin_end: float,
    round_pallet_size: bool,
    rounding_step: int,
    length_edge_distances: tuple[float | None, float | None] | None = None,
    width_edge_distances: tuple[float | None, float | None] | None = None,
    length_origin: float | None = None,
    width_origin: float | None = None,
    reference_support_index: int | None = None,
) -> tuple[DirectionInput, DirectionInput, pv.PolyData, pv.PolyData]:
    """Create editable pallet inputs and place the machine on its support plane.

    Each unique support X/Y coordinate receives a cross/longitudinal beam; edge
    beams remain present in the existing pallet model.  The pallet encloses the
    complete imported machine with a small fixed safety margin.
    """
    if not supports:
        raise ValueError("Не найдены грани опор в выбранной плоскости.")
    reference = next((face for face in supports if face.index == reference_support_index), supports[0])
    assert reference.point is not None
    frame = _support_frame(model, reference.index)
    local_mesh = _support_frame_mesh(model.mesh, frame)
    local_edges = _support_frame_mesh(model.edges, frame)
    local_points = {
        face.index: np.array((
            support_axis_coordinate(model, reference.index, face.point, 0),
            support_axis_coordinate(model, reference.index, face.point, 1),
            float(np.dot(face.point - frame[0], frame[3])),
        ))
        for face in supports if face.point is not None
    }
    xmin, xmax, ymin, ymax, _zmin, _zmax = local_mesh.bounds
    machine_length, machine_width = xmax - xmin, ymax - ymin
    if machine_length <= 0 or machine_width <= 0:
        raise ValueError("STEP-модель не имеет конечных габаритов в плоскости поддона.")
    tolerance = max(model.plane_tolerance, 1e-6)
    margin_x_start = max(length_margin_start, 2 * length_beam_width)
    margin_x_end = max(length_margin_end, 2 * length_beam_width)
    margin_y_start = max(width_margin_start, 2 * width_beam_width)
    margin_y_end = max(width_margin_end, 2 * width_beam_width)
    support_x = _coalesced_beam_positions(
        [float(local_points[face.index][0]) for face in supports if face.index in local_points],
        tolerance, length_beam_width,
    )
    support_y = _coalesced_beam_positions(
        [float(local_points[face.index][1]) for face in supports if face.index in local_points],
        tolerance, width_beam_width,
    )
    if not support_x or not support_y:
        raise ValueError("Не удалось определить координаты опор.")

    def measured_positions(
        positions: tuple[float, ...], origin: float, size: float,
        distances: tuple[float | None, float | None] | None,
    ) -> tuple[tuple[float, ...], float, float]:
        relative = tuple(value - positions[0] for value in positions)
        default_start = float(math.floor(positions[0] - origin + 0.5))
        default_end = float(math.floor(origin + size - positions[-1] + 0.5))
        start, end = distances if distances is not None else (default_start, default_end)
        start = default_start if start is None else start
        end = default_end if end is None else end
        if start < 0 or end < 0:
            raise ValueError("Отступ от габарита до опоры не может быть отрицательным.")
        return relative, float(start), float(end)

    # The selected bounding planes replace the mesh bounding box only after a
    # user measures them.  Until then, preserve the previous automatic flow.
    x_relative, x_first, x_last = measured_positions(
        support_x, xmin if length_origin is None else length_origin, machine_length, length_edge_distances,
    )
    y_relative, y_first, y_last = measured_positions(
        support_y, ymin if width_origin is None else width_origin, machine_width, width_edge_distances,
    )

    def direction(
        relative_positions: tuple[float, ...], first_distance: float, last_distance: float,
        beam_height: float, beam_width: float, margin_start: float, margin_end: float,
    ) -> DirectionInput:
        positions = tuple(margin_start + first_distance + value for value in relative_positions)
        return DirectionInput(
            beam_height=beam_height,
            beam_width=beam_width,
            support_distances=tuple(right - left for left, right in zip(relative_positions, relative_positions[1:])),
            first_edge_to_support=first_distance,
            last_support_to_edge=last_distance,
            margin_start=margin_start,
            margin_end=margin_end,
            round_pallet_size=round_pallet_size,
            rounding_step=rounding_step,
            support_positions=positions,
        )

    length_input = direction(
        x_relative, x_first, x_last, length_beam_height, length_beam_width, margin_x_start, margin_x_end
    )
    width_input = direction(
        y_relative, y_first, y_last, width_beam_height, width_beam_width, margin_y_start, margin_y_end
    )
    raw_width = width_input.first_edge_to_support + sum(width_input.support_distances) + width_input.last_support_to_edge + margin_y_start + margin_y_end
    pallet_width = (
        (round_to_fifty(raw_width) if rounding_step == 50 else round_up_to_five(raw_width))
        if round_pallet_size else raw_width
    )

    def place(source: pv.PolyData) -> pv.PolyData:
        transformed = source.copy(deep=True)
        points = transformed.points.copy()
        points[:, 0] = points[:, 0] - (xmin if length_origin is None else length_origin) + margin_x_start
        # PalletView mirrors the pallet's Y coordinate for its technical-drawing
        # orientation, so mirror the imported machine in the same display space.
        points[:, 1] = pallet_width - (points[:, 1] - (ymin if width_origin is None else width_origin) + margin_y_start)
        points[:, 2] = points[:, 2] + length_beam_height + width_beam_height
        transformed.points = points
        return transformed
    return (
        length_input,
        width_input,
        place(local_mesh),
        place(local_edges),
    )
