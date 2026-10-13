from pathlib import Path

import numpy as np
import pyvista as pv

from palletlab.importers.step_model import (
    ImportedStepModel,
    StepFace,
    _surface_centroid,
    _coalesced_beam_positions,
    coplanar_supports,
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


def test_support_detection_accepts_a_machine_laid_on_its_side():
    vertical_support = StepFace(0, np.array((0, 50, 50), dtype=float), np.array((1, 0, 0), dtype=float))
    same_plane_support = StepFace(1, np.array((0, 200, 50), dtype=float), np.array((1, 0, 0), dtype=float))
    model = _model(vertical_support, same_plane_support)

    assert coplanar_supports(model, 0) == (vertical_support, same_plane_support)


def test_pallet_inputs_rotate_a_sideways_machine_onto_its_support_plane():
    supports = (
        StepFace(0, np.array((0, 50, 50), dtype=float), np.array((1, 0, 0), dtype=float)),
        StepFace(1, np.array((0, 200, 50), dtype=float), np.array((1, 0, 0), dtype=float)),
    )
    model = _model(*supports)

    _length, _width, placed_mesh, _edges = pallet_inputs_from_supports(
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
        reference_support_index=0,
    )

    assert placed_mesh.bounds[4] == 140


def test_automatic_model_offsets_position_supports_from_mesh_bounds():
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
    )

    assert length.first_edge_to_support == 120
    assert length.last_support_to_edge == 100
    assert length.support_positions == (220, 1000)


def test_close_support_candidates_keep_the_beam_with_more_supported_feet():
    # Two feet at X=100 compete with five feet at X=130 for a 50 mm beam.
    assert _coalesced_beam_positions([100, 100, 130, 130, 130, 130, 130], 0.01, 50) == (130,)


def test_equal_close_candidates_keep_the_one_farther_from_the_previous_beam():
    # The right candidate wins the documented deterministic tie-break.
    assert _coalesced_beam_positions([100, 100, 130, 130], 0.01, 50) == (130,)


def test_non_conflicting_candidates_remain_separate_beams():
    assert _coalesced_beam_positions([100, 100, 160, 160, 160], 0.01, 50) == (100, 160)
