from palletlab.desktop.web_host import WebApplicationApi


def test_web_application_api_reports_compatible_snapshot_version() -> None:
    status = WebApplicationApi().status()

    assert status["application"] == "PalletLab"
    assert status["snapshotVersion"] == 1
