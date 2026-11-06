"""Low-overhead, opt-in-free measurements for the STEP import pipeline.

The profiler deliberately records process RSS rather than only Python heap
allocations: OpenCascade, VTK and NumPy keep the most significant buffers in
native memory.  It is observation-only and never participates in rendering or
calculation decisions.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Any


def process_rss_bytes() -> int | None:
    """Return the current process working set where the platform exposes it."""
    if sys.platform == "win32":
        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
        )
        return int(counters.WorkingSetSize) if success else None
    try:
        with Path("/proc/self/statm").open(encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (IndexError, OSError, ValueError):
        return None


class StepPerformanceTrace:
    """Collect comparable wall-clock, RSS and geometry-size checkpoints."""

    def __init__(self) -> None:
        self._started = perf_counter()
        self._initial_rss = process_rss_bytes()
        self._points: list[dict[str, Any]] = []

    def checkpoint(self, stage: str, **details: Any) -> None:
        rss = process_rss_bytes()
        point: dict[str, Any] = {
            "stage": stage,
            "elapsedMs": round((perf_counter() - self._started) * 1000, 1),
            "rssBytes": rss,
        }
        if rss is not None and self._initial_rss is not None:
            point["rssDeltaBytes"] = rss - self._initial_rss
        point.update(details)
        self._points.append(point)

    def report(self) -> dict[str, Any]:
        return {"points": self._points}


def geometry_footprint(mesh: Any, edges: Any) -> dict[str, int]:
    """Describe geometry buffers without copying or serialising them."""
    def byte_size(value: Any) -> int:
        return int(getattr(value, "nbytes", 0))

    return {
        "meshPointsBytes": byte_size(mesh.points),
        "meshCellsBytes": byte_size(mesh.faces),
        "faceIdsBytes": byte_size(mesh.cell_data["step_face_index"]),
        "edgePointsBytes": byte_size(edges.points),
        "edgeCellsBytes": byte_size(edges.lines),
        "triangleCount": int(mesh.n_cells),
        "vertexCount": int(mesh.n_points),
        "edgeCellCount": int(edges.n_cells),
    }


def write_step_performance(event: str, trace: dict[str, Any]) -> None:
    """Retired compatibility hook for historic STEP diagnostics.

    Kept so older callers and integrations remain compatible, but production
    imports no longer create or append diagnostic files.
    """
    del event, trace
