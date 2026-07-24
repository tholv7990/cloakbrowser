"""Cross-profile separation analysis (Phase 5 core, doc 05).

Pure logic: given a list of collected profile identities, decide whether the fleet
is plausibly distinct without being impossibly uniform or impossibly correlated.
"Different" does not mean every value differs — common real values (screen, cores,
GPU) are expected to repeat; only the MUST_DIFFER anchors and seed-derived surfaces
must not collide, and a seed-derived surface shared across different seeds is an
impossible correlation. The live generation/collection of ≥100 profiles needs the
binary; this analyzer is deterministically testable on fixture identities.
"""

from __future__ import annotations

from collections import Counter, defaultdict


# Every profile must be unique on these.
MUST_DIFFER_FIELDS = ("seed", "config_hash")
# High-entropy noise surfaces: unique per seed only when fingerprint noise is ON (the
# default preset). Under the consistent preset (--fingerprint-noise=false) they are
# deterministic and shared across profiles by design (verified live), so sharing is not
# a defect. Sharing across DIFFERENT seeds under noise-on is an impossible correlation.
NOISE_ENTROPY_FIELDS = ("canvas", "audio")
# Pool-selected or common surfaces: collisions across seeds are EXPECTED, never a
# failure. Verified live: the GPU/WebGL renderer is drawn from a finite pool (16 seeds
# already collide, birthday-style), and screen/cores are fleet-constant.
MAY_REPEAT_FIELDS = ("webgl", "gpu", "screen", "cores", "ua", "timezone", "locale")


def _duplicate_id_groups(identities: list[dict], field: str) -> list[list[str]]:
    groups: dict[object, list[str]] = defaultdict(list)
    for identity in identities:
        groups[identity.get(field)].append(identity["id"])
    return sorted(ids for ids in groups.values() if len(ids) > 1)


def analyze_separation(identities: list[dict], *, preset: str = "default") -> dict:
    count = len(identities)

    duplicate_seeds = _duplicate_id_groups(identities, "seed")
    duplicate_config_hashes = _duplicate_id_groups(identities, "config_hash")

    # Only the high-entropy noise surfaces must be unique per seed, and only when noise
    # is on. GPU/WebGL is pool-selected, so its collisions are expected (MAY_REPEAT).
    impossible_fields = () if preset == "consistent" else NOISE_ENTROPY_FIELDS
    impossible_correlations = []
    for field in impossible_fields:
        seeds_by_value: dict[object, set] = defaultdict(set)
        for identity in identities:
            seeds_by_value[identity.get(field)].add(identity.get("seed"))
        for value, seeds in seeds_by_value.items():
            if len(seeds) > 1:
                impossible_correlations.append(
                    {"field": field, "value": value, "seeds": sorted(seeds)}
                )

    tuple_groups: dict[tuple, list[str]] = defaultdict(list)
    for identity in identities:
        key = tuple(sorted((k, str(v)) for k, v in identity.items() if k != "id"))
        tuple_groups[key].append(identity["id"])
    exact_duplicates = sorted(ids for ids in tuple_groups.values() if len(ids) > 1)

    # Per-component duplicate rate: fraction of profiles whose value is shared with at
    # least one other profile. Informational for MAY_REPEAT fields — never a failure.
    component_duplicate_rates = {}
    for field in MAY_REPEAT_FIELDS:
        values = [identity.get(field) for identity in identities]
        counts = Counter(values)
        shared = sum(1 for value in values if counts[value] > 1)
        component_duplicate_rates[field] = round(shared / count, 4) if count else 0.0

    failed = bool(
        duplicate_seeds
        or duplicate_config_hashes
        or impossible_correlations
        or exact_duplicates
    )
    return {
        "count": count,
        "verdict": "fail" if failed else "pass",
        "duplicate_seeds": duplicate_seeds,
        "duplicate_config_hashes": duplicate_config_hashes,
        "impossible_correlations": impossible_correlations,
        "exact_duplicates": exact_duplicates,
        "component_duplicate_rates": component_duplicate_rates,
    }
