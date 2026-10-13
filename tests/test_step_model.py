from pathlib import Path

import numpy as np
import pyvista as pv

from palletlab.importers.step_model import (
    ImportedStepModel,
    StepFace,
    _surface_centroid,
    edge_to_support_center_distance,
    pallet_inputs_from_supports,
)


def _model(*faces: StepFace) -> ImportedStepModel:
    return ImportedStepModel(
        pv.Cube(bounds=(0, 1000, 0, 500, 0, 400)), pv.PolyData(), tuple(faces), 0.01, Path("machine.step")
    )


def test_surface_centroid_is_area_weighted_not_a_plane_origin():
    points = np.array(((0, 0, 0), (4, 0, 0), (0, 2, 0), (4, 2, 0)), dtype=float)
    # Two equal-area triangles form a rectangle whose centroid is (2, 1, 0).
    centroid = _surface_centroid(points, [3, 0, 1, 2, 3, 1, 3, 2])

    assert np.allclose(centroid, (2, 1, 0))


def test_edge_distance_uses_the_selected_support_face_centre():
    model = _model(
        StepFace(0, np.array((0, 0, 0), dtype=float), np.array((-1, 0, 0), dtype=float)),
        StepFace(1, np.array((123.6, 50, 0), dtype=float), np.array((0, 0, -1), dtype=float)),
    )

    assert edge_to_support_center_distance(model, 0, 1, 0) == 124


def test_selected_boundary_distances_position_supports_from_that_boundary():
    supports = (
        StepFace(0, np.array((120, 80, 0), dtype=float), np.array((0, 0, -1), dtype=float)),
        StepFace(1, np.array((900, 80, 0), dtype=float), np.array((0, 0, -1), dtype=float)),
    )
    model = _model(*supports)

    length, _width, _mesh, _edges = pallet_inputs_from_supports(
        model,
        supports,
        length_beam_height=70,
        length_beam_width=50,
        width_beam_height=70,
        width_beam_width=50,
        length_margin_start=100,
        length_margin_end=100,
        width_margin_start=100,
        width_margin_end=100,
        round_pallet_size=False,
        rounding_step=5,
        length_edge_distances=(120, 100),
        length_origin=0,
    )

    assert length.first_edge_to_support == 120
    assert length.last_support_to_edge == 100
    assert length.support_positions == (220, 1000)
