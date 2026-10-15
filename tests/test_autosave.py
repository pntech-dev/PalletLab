from palletlab.core.autosave import AUTOSAVE_LIMIT, AutosaveStore
from palletlab.core.models import DirectionInput
from palletlab.core.project_state import ProjectState


def _state(camera: str = "isometric") -> ProjectState:
    return ProjectState(
        length_input=DirectionInput(70, 50, (100,), 120, 240, 100, 150, True, 50),
        width_input=DirectionInput(60, 40, (200,), 90, 190, 80, 70, False, 5),
        camera=camera,  # type: ignore[arg-type]
    )


def test_autosave_keeps_only_the_three_newest_snapshots(tmp_path):
    store = AutosaveStore(tmp_path)

    snapshots = [store.save(_state("top" if index % 2 else "isometric")) for index in range(4)]

    remaining = sorted(tmp_path.glob("*.autosave.palletlab.json"))
    assert len(remaining) == AUTOSAVE_LIMIT
    assert snapshots[0] not in remaining
    assert snapshots[-1] in remaining


def test_manual_save_cleanup_removes_all_autosaves_and_binds_the_project(tmp_path):
    store = AutosaveStore(tmp_path)
    store.save(_state())
    store.set_project("C:/Projects/first.palletlab.json")
    store.save(_state("top"))

    store.clear()
    store.set_project("C:/Projects/final.palletlab.json")
    snapshot = store.save(_state("front"))

    remaining = list(tmp_path.glob("*.autosave.palletlab.json"))
    assert remaining == [snapshot]
    assert snapshot.name.startswith("project-")
