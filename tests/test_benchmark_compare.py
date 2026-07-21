from benchmarks.compare_chrome import (
    build_overhead_summary,
    build_summary,
    measured_total,
    relative_percent,
    summarize,
)


def test_summarize_reports_descriptive_statistics():
    assert summarize([10.0, 20.0, 30.0]) == {
        "count": 3,
        "median": 20.0,
        "mean": 20.0,
        "min": 10.0,
        "max": 30.0,
        "p90": 28.0,
        "p95": 29.0,
        "stddev": 10.0,
    }


def test_summarize_empty_values_returns_zero_count():
    assert summarize([]) == {"count": 0}


def test_summarize_reports_tail_and_dispersion_statistics():
    # Linear-interpolation percentiles (numpy-style) + sample stddev.
    stats = summarize([10.0, 20.0, 30.0, 40.0, 50.0])
    assert stats["p90"] == 46.0
    assert stats["p95"] == 48.0
    assert stats["stddev"] == 15.811


def test_summarize_single_value_has_zero_stddev_and_flat_percentiles():
    stats = summarize([42.0])
    assert stats["p90"] == 42.0
    assert stats["p95"] == 42.0
    assert stats["stddev"] == 0.0


def test_relative_percent_reports_overhead_and_handles_zero_baseline():
    assert relative_percent(120.0, 100.0) == 20.0
    assert relative_percent(1.0, 0.0) is None


def test_measured_total_excludes_memory_instrumentation():
    metrics = {
        "launch_ms": 100.0,
        "page_setup_ms": 20.0,
        "local_navigation_ms": 10.0,
        "external_navigation_ms": 30.0,
        "javascript_ms": 5.0,
        "memory_mib": 300.0,
        "close_ms": 15.0,
    }
    assert measured_total(metrics) == 180.0


def test_build_summary_keeps_failures_out_of_metric_samples():
    iterations = {
        "cloakbrowser": [
            {"success": True, "metrics": {"launch_ms": 120.0, "memory_mib": 300.0}},
            {"success": False, "error": {"phase": "launch", "message": "failed"}},
        ],
        "chrome": [
            {"success": True, "metrics": {"launch_ms": 100.0, "memory_mib": 250.0}},
        ],
    }

    result = build_summary(iterations)

    assert result["cloakbrowser"]["launch_ms"]["median"] == 120.0
    assert result["cloakbrowser"]["successful_iterations"] == 1
    assert result["cloakbrowser"]["failed_iterations"] == 1
    assert result["chrome"]["memory_mib"]["median"] == 250.0


def test_build_overhead_summary_keeps_driver_and_legacy_cost_separate():
    result = build_overhead_summary(
        driver_start_ms=[300.0, 320.0, 310.0],
        legacy_launch_ms=[470.0, 490.0, 480.0],
    )
    assert result["playwright_driver_start_ms"]["median"] == 310.0
    assert result["legacy_cloak_launch_ms"]["median"] == 480.0
