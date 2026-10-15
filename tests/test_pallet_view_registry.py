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
