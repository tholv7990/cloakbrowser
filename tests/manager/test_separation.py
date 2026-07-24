from __future__ import annotations

from manager_backend.features.diagnostics.separation import (
    MAY_REPEAT_FIELDS,
    MUST_DIFFER_FIELDS,
    analyze_separation,
)


def _identity(index: int, **overrides) -> dict:
    identity = {
        "id": f"prof-{index}",
        "seed": str(1000 + index),
        "config_hash": f"hash{index}",
        "canvas": f"canvas{index}",
        "webgl": f"webgl{index}",
        "audio": f"audio{index}",
        # MAY_REPEAT — common real values are expected to collide.
        "screen": "1920x1080",
        "cores": 8,
        "gpu": "ANGLE (Intel)",
        "ua": "Chrome/146",
        "timezone": "America/New_York",
        "locale": "en-US",
    }
    identity.update(overrides)
    return identity


def test_healthy_fleet_passes_even_when_common_values_repeat():
    report = analyze_separation([_identity(i) for i in range(5)])
    assert report["verdict"] == "pass"
    assert report["duplicate_seeds"] == []
    assert report["impossible_correlations"] == []
    # A common screen repeating across the whole fleet is allowed (MAY_REPEAT).
    assert report["component_duplicate_rates"]["screen"] == 1.0
    assert "screen" in MAY_REPEAT_FIELDS


def test_duplicate_seed_fails():
    identities = [_identity(0), _identity(1, seed="1000")]  # same seed as prof-0
    report = analyze_separation(identities)
    assert report["verdict"] == "fail"
    assert report["duplicate_seeds"]
    assert "seed" in MUST_DIFFER_FIELDS


def test_duplicate_config_hash_fails():
    identities = [_identity(0), _identity(1, config_hash="hash0")]
    report = analyze_separation(identities)
    assert report["verdict"] == "fail"
    assert report["duplicate_config_hashes"]


def test_impossible_correlation_same_canvas_different_seed_fails():
    # A seed-derived surface (canvas) shared across two DIFFERENT seeds means the seed
    # does not actually drive that surface — an impossible correlation.
    identities = [_identity(0), _identity(1, canvas="canvas0")]
    report = analyze_separation(identities)
    assert report["verdict"] == "fail"
    assert any(c["field"] == "canvas" for c in report["impossible_correlations"])


def test_exact_duplicate_identity_fails():
    twin = _identity(0)
    twin["id"] = "prof-twin"
    report = analyze_separation([_identity(0), twin])
    assert report["verdict"] == "fail"
    assert report["exact_duplicates"]
