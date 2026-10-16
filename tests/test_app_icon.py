from palletlab.ui.app_icon import application_icon


def test_application_icon_is_available_from_the_source_tree():
    assert not application_icon().isNull()
