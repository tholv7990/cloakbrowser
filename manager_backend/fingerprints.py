from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


# Bumped to 2 when the retired behavior fields (F-006) left the config hash. A
# one-time migration re-baselines every stored profile's hash under this revision.
FINGERPRINT_REVISION = 2


@dataclass(frozen=True, slots=True)
class FingerprintIdentity:
    seed: str
    revision: int
    config_hash: str


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _fingerprint_behavior(value: Any) -> dict[str, Any]:
    # No behavior field is identity-relevant any more (F-006 retired the hardware /
    # GPU / additional-args knobs; permissions is a runtime grant, not a surface).
    # Kept as a hook so build_fingerprint_identity's signature is stable.
    return {}


def build_fingerprint_identity(
    *,
    seed: str,
    fingerprint_preset: str = "consistent",
    browser_version_mode: str = "installed",
    browser_version: str | None = None,
    user_agent_mode: str = "automatic",
    custom_user_agent: str | None = None,
    location: Any = None,
    window: Any = None,
    behavior: Any = None,
) -> FingerprintIdentity:
    payload = {
        "revision": FINGERPRINT_REVISION,
        "seed": seed,
        "fingerprint_preset": fingerprint_preset,
        "browser_version_mode": browser_version_mode,
        "browser_version": browser_version,
        "user_agent_mode": user_agent_mode,
        "custom_user_agent": custom_user_agent,
        "location": _plain(location) if location is not None else {},
        "window": _plain(window) if window is not None else {},
        "fingerprint_behavior": _fingerprint_behavior(behavior),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return FingerprintIdentity(
        seed=seed,
        revision=FINGERPRINT_REVISION,
        config_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def generate_unique_seed(is_taken: Callable[[str], bool], max_attempts: int = 32) -> str:
    for _ in range(max_attempts):
        candidate = str(secrets.randbits(64))
        if not is_taken(candidate):
            return candidate
    raise RuntimeError("Could not allocate a unique fingerprint seed")
