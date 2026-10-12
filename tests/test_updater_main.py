import os

from updater_main import _running


def test_running_recognizes_current_process():
    assert _running(os.getpid())
