from palletlab.ui.app_icon import _application_icon_path


def test_application_icon_file_is_available_from_the_source_tree():
    assert _application_icon_path().is_file()
