from __future__ import annotations

from palletlab.diagnostics import measure_step_cache_loads, representative_scenarios


def test_representative_pallet_scenarios_capture_calculation_geometry_and_render_metrics():
    measurements = representative_scenarios()

    assert measurements.keys() == {"three-layer", "manual-beam", "multilayer"}
    for measurement in measurements.values():
        assert measurement.calculation_seconds >= 0
        assert measurement.geometry_seconds >= 0
        assert measurement.beam_count > 0
        assert measurement.dimension_count > 0
        assert measurement.render_calls == 1


def test_step_cache_diagnostic_measures_cold_and_warm_loads_once_each():
    calls: list[str] = []

    measurement = measure_step_cache_loads(
        lambda: calls.append("uncached"),
        lambda: calls.append("cached"),
    )

    assert calls == ["uncached", "cached"]
    assert measurement.uncached_seconds >= 0
    assert measurement.cached_seconds >= 0
