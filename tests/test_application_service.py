from palletlab.application.service import ApplicationService
from palletlab.core.models import DirectionInput
from palletlab.core.persistence import project_to_dict
from palletlab.core.project_state import ProjectState


def test_calculate_returns_a_fresh_web_snapshot() -> None:
    state = ProjectState(
        length_input=DirectionInput(100, 80, (700,), 100, 100, 50, 50),
        width_input=DirectionInput(80, 60, (500,), 80, 80, 40, 40),
    )

    response = ApplicationService().calculate(project_to_dict(state))

    assert response["ok"] is True
    assert response["snapshot"]["pallet"]["beams"]


def test_calculate_returns_a_user_facing_validation_error() -> None:
    response = ApplicationService().calculate({"format_version": 999})

    assert response["ok"] is False
    assert isinstance(response["error"], str)
