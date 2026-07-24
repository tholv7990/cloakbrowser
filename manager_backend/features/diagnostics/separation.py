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
# Seed-derived surfaces: expected near-unique. The same value across two DIFFERENT
# seeds means the seed does not actually drive the surface — an impossible correlation.
SEED_DERIVED_FIELDS = ("canvas", "webgl", "audio")
# Common real values that MAY repeat across profiles without being a defect.
MAY_REPEAT_FIELDS = ("screen", "cores", "gpu", "ua", "timezone", "locale")


def _duplicate_id_groups(identities: list[dict], field: str) -> list[list[str]]:
    groups: dict[object, list[str]] = defaultdict(list)
    for identity in identities:
        groups[identity.get(field)].append(identity["id"])
    return sorted(ids for ids in groups.values() if len(ids) > 1)


def analyze_separation(identities: list[dict]) -> dict:
    count = len(identities)

    duplicate_seeds = _duplicate_id_groups(identities, "seed")
    duplicate_config_hashes = _duplicate_id_groups(identities, "config_hash")

    impossible_correlations = []
    for field in SEED_DERIVED_FIELDS:
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
