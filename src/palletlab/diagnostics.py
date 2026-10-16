"""Repeatable, opt-in measurements for PalletLab performance scenarios.

This module deliberately has no GUI dependency.  It is suitable for a local
diagnostic command or tests and provides comparable timing fields without
turning performance observations into machine-specific pass/fail thresholds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter

from palletlab.controllers.viewport_geometry import editable_dimensions, insertion_markers
from palletlab.core.calculator import build_multilayer_pallet, calculate_direction, insertion_slots
from palletlab.core.models import Beam3D, BeamSection, DirectionInput, LayerDefinition, ManualBeamInput, PalletResult


@dataclass(frozen=True)
class ScenarioMeasurement:
    """Timing and output counts for a single pallet calculation scenario."""

    name: str
    calculation_seconds: float
    geometry_seconds: float
    beam_count: int
    dimension_count: int
    render_calls: int


@dataclass(frozen=True)
class StepCacheMeasurement:
    """Timing for equivalent uncached and cached STEP load operations."""

    uncached_seconds: float
    cached_seconds: float


def _measure_result(
    name: str,
    result: PalletResult,
    layers: tuple[LayerDefinition, ...],
    calculation_seconds: float,
    manual_beams: tuple[ManualBeamInput, ...] = (),
) -> ScenarioMeasurement:
    """Measure viewport preparation after a scenario has calculated its result."""
    started = perf_counter()
    dimensions = editable_dimensions(result, manual_beams)
    slots = insertion_slots(result, layers[0].axis)
    insertion_markers(result, slots)
    geometry_seconds = perf_counter() - started
    return ScenarioMeasurement(name, calculation_seconds, geometry_seconds, len(result.beams_3d), len(dimensions), 1)


def measure_pallet_scenario(name: str, layers: tuple[LayerDefinition, ...]) -> ScenarioMeasurement:
    """Measure calculation and viewport-geometry preparation for ``layers``.

    Rendering is intentionally not performed here: this diagnostic records
    the one final render a controller is expected to request after applying a
    calculated result.
    """
    started = perf_counter()
    result = build_multilayer_pallet(layers)
    calculation_seconds = perf_counter() - started

    return _measure_result(name, result, layers, calculation_seconds)


def measure_step_cache_loads(
    load_uncached: Callable[[], object], load_cached: Callable[[], object],
) -> StepCacheMeasurement:
    """Measure one cold and one warm STEP load without prescribing a loader."""
    started = perf_counter()
    load_uncached()
    uncached_seconds = perf_counter() - started
    started = perf_counter()
    load_cached()
    cached_seconds = perf_counter() - started
    return StepCacheMeasurement(uncached_seconds=uncached_seconds, cached_seconds=cached_seconds)


def representative_scenarios() -> dict[str, ScenarioMeasurement]:
    """Return measurements for the standard three pallet scenarios.

    STEP cache timings are supplied separately because they require a real
    model file and must not make the regular test suite depend on CAD assets.
    """
    length = DirectionInput(70, 50, (1070, 460, 1300, 499), 123, 552, 100, 100)
    width = DirectionInput(70, 50, (560, 720), 277.55, 179, 100, 100)
    basic = (
        LayerDefinition("length", "length", calculate_direction(length)),
        LayerDefinition("width", "width", calculate_direction(width)),
    )
    multilayer = (*basic, LayerDefinition("top", "length", calculate_direction(length)))
    started = perf_counter()
    manual_result = build_multilayer_pallet(basic)
    supports = [beam for beam in manual_result.beams_3d if beam.layer_id == "width"]
    manual = ManualBeamInput("manual-1", ("width", 0), ("width", 1), 1000, BeamSection(70, 50))
    manual_result = replace(
        manual_result,
        beams_3d=(*manual_result.beams_3d, Beam3D(
            1025,
            (min(beam.y - beam.size_y / 2 for beam in supports[:2]) + max(beam.y + beam.size_y / 2 for beam in supports[:2])) / 2,
            max(beam.z + beam.size_z / 2 for beam in supports[:2]) + 35,
            max(beam.x + beam.size_x / 2 for beam in supports[:2]) - min(beam.x - beam.size_x / 2 for beam in supports[:2]),
            50,
            70,
            "length",
            "manual-1",
        )),
    )
    manual_calculation_seconds = perf_counter() - started
    return {
        "three-layer": measure_pallet_scenario("three-layer", multilayer),
        "manual-beam": _measure_result("manual-beam", manual_result, basic, manual_calculation_seconds, (manual,)),
        "multilayer": measure_pallet_scenario("multilayer", multilayer),
    }
