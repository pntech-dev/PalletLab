from types import SimpleNamespace
from unittest.mock import patch

from palletlab.core.models import Beam3D
from palletlab.visualization.pallet_view import PalletView


def _beam(x: float) -> Beam3D:
    return Beam3D(x, 0, 35, 50, 100, 70, "width", "length", 0)


def test_actor_registry_keeps_unchanged_beam_identity_and_targets_only_changed_geometry():
    original = {("length", 0): _beam(25), ("length", 1): _beam(125)}
    unchanged = original.copy()
    changed = {("length", 0): _beam(25), ("length", 1): _beam(150), ("width", 0): _beam(0)}

    assert PalletView._changed_beam_keys(original, unchanged) == set()
    assert PalletView._changed_beam_keys(original, changed) == {("length", 1), ("width", 0)}


def test_beam_actor_names_are_stable_when_global_render_order_changes():
    # A deletion from an earlier layer changes enumerate() positions of every
    # later beam, but must never reuse its PyVista actor name.
    assert PalletView._beam_actor_name(("top", 2)) == "pallet-beam-top-2"
    assert PalletView._beam_actor_name(("middle", 2)) == "pallet-beam-middle-2"


def test_step_hover_is_rate_limited_to_thirty_picks_per_second():
    picked: list[None] = []
    displayed: list[int] = []
    view = SimpleNamespace(
        _support_callback=object(),
        _step_model_actor=object(),
        _step_model_visible=True,
        _last_step_hover_pick_at=float("-inf"),
        _hovered_step_face_index=None,
        _hardware_step_face_at_cursor=lambda: picked.append(None) or 7,
        _show_step_hover_face=displayed.append,
        render=lambda: None,
    )

    with patch("palletlab.visualization.pallet_view.monotonic", side_effect=(1.0, 1.01)):
        PalletView._update_step_face_hover(view)
        PalletView._update_step_face_hover(view)

    assert picked == [None]
    assert displayed == [7]


def test_clearing_only_the_step_model_removes_its_hover_actor():
    removed: list[str] = []
    view = SimpleNamespace(
        _remove_step_hover_face=lambda: removed.append("hover"),
        remove_actor=lambda *_args, **_kwargs: None,
        _step_mesh=object(), _step_edges=object(), _step_model_actor=object(), _step_edge_actor=object(),
        _rendered_step_mesh=object(), _step_faces=(1,), _support_callback=object(),
        _support_face_indices={1}, _reference_support_index=1, _step_face_cell_indices={1: object()},
        _hovered_step_face_index=1, _last_step_hover_pick_at=0.0, _step_model_visible=False,
        render=lambda: None,
    )

    PalletView.clear_step_model(view)

    assert removed == ["hover"]
    assert view._step_model_actor is None
    assert view._last_step_hover_pick_at == float("-inf")
