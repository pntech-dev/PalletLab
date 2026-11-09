from types import SimpleNamespace

from palletlab import step_performance


def test_memory_diagnostics_do_not_break_import_when_windows_api_fails(monkeypatch):
    class ApiFunction:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    def fail(*_args):
        raise OSError("memory counters unavailable")

    api = SimpleNamespace(
        kernel32=SimpleNamespace(GetCurrentProcess=ApiFunction(lambda: 1)),
        psapi=SimpleNamespace(GetProcessMemoryInfo=ApiFunction(fail)),
    )
    monkeypatch.setattr(step_performance.sys, "platform", "win32")
    monkeypatch.setattr(step_performance.ctypes, "windll", api, raising=False)

    assert step_performance.process_rss_bytes() is None
    assert step_performance.StepPerformanceTrace().report() == {"points": []}
