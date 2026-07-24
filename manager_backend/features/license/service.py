"""License enforcement for the desktop app.

The cloud issues a short-lived Ed25519-signed *entitlement*; the desktop caches it
and verifies it **offline** on every profile launch. Enforcement is opt-in
(``settings.require_license``) so the free/dev build is unaffected — a licensed build
sets ``PLASMA_REQUIRE_LICENSE=1`` and pins ``PLASMA_ENTITLEMENT_PUBKEY``.

State machine (only ``disabled`` / ``active`` / ``grace`` may launch):

    disabled    enforcement off -> always allowed
    active      signed, now <= exp
    grace       signed, exp < now <= offline_grace_deadline (still allowed; UI warns)
    unlicensed  enforcing, no entitlement cached                -> blocked
    expired     signed, now > offline_grace_deadline            -> blocked
    invalid     bad signature / missing claims / no pinned key  -> blocked (fail closed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ...config import ManagerSettings
from ...errors import ManagerError
from .verifier import EntitlementError, public_key_from_b64, verify_entitlement

_ALLOWED_STATES = frozenset({"disabled", "active", "grace"})
_BLOCK_CODES = {
    "unlicensed": ("license_required", "No active license. Sign in and activate your key."),
    "expired": ("license_expired", "Your license has expired. Renew to continue."),
    "invalid": ("license_invalid", "Your license could not be verified."),
}


@dataclass
class LicenseStatus:
    state: str
    allowed: bool
    plan: str | None = None
    features: list[str] = field(default_factory=list)
    expires_at: int | None = None  # epoch seconds (entitlement exp)
    grace_deadline: int | None = None  # epoch seconds (offline_grace_deadline)
    trial_end: int | None = None  # epoch seconds; hard trial cutoff (trial keys only)
    detail: str | None = None  # safe reason code, never a secret


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


# --- cache (a capability token, not a secret credential) ----------------------


def load_entitlement(settings: ManagerSettings) -> str | None:
    path = settings.entitlement_path
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def save_entitlement(settings: ManagerSettings, token: str) -> None:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.entitlement_path.write_text(token.strip(), encoding="utf-8")


def clear_entitlement(settings: ManagerSettings) -> None:
    settings.entitlement_path.unlink(missing_ok=True)


# --- evaluation ---------------------------------------------------------------


def evaluate_license(settings: ManagerSettings, *, now: int | None = None) -> LicenseStatus:
    if not settings.require_license:
        return LicenseStatus("disabled", allowed=True)
    now = now if now is not None else _now_epoch()

    if not settings.entitlement_pubkey:
        # Enforcing but no pinned key -> fail closed (misconfigured build).
        return LicenseStatus("invalid", allowed=False, detail="no_pinned_key")

    token = load_entitlement(settings)
    if token is None:
        return LicenseStatus("unlicensed", allowed=False)

    try:
        public_key = public_key_from_b64(settings.entitlement_pubkey)
        claims = verify_entitlement(token, public_key)
    except (EntitlementError, ValueError):
        return LicenseStatus("invalid", allowed=False, detail="bad_signature")

    exp = claims.get("exp")
    grace = claims.get("offline_grace_deadline")
    if not isinstance(exp, int) or not isinstance(grace, int):
        return LicenseStatus("invalid", allowed=False, detail="missing_claims")

    features = claims.get("features") or []
    plan = claims.get("plan")
    trial_end = claims.get("trial_end")
    trial_end = trial_end if isinstance(trial_end, int) else None
    if trial_end is not None and now > trial_end:
        state = "expired"  # trial hard-cap wins over exp/grace
    elif now <= exp:
        state = "active"
    elif now <= grace:
        state = "grace"
    else:
        state = "expired"
    return LicenseStatus(
        state=state,
        allowed=state in _ALLOWED_STATES,
        plan=plan,
        features=list(features),
        expires_at=exp,
        grace_deadline=grace,
        trial_end=trial_end,
    )


def install_entitlement(settings: ManagerSettings, token: str) -> LicenseStatus:
    """Verify a freshly-issued entitlement and cache it. Rejects an unverifiable
    token (bad signature / no pinned key) so garbage never lands in the store."""
    if not settings.entitlement_pubkey:
        raise ManagerError(
            "license_invalid", "This build has no pinned license key.", 400
        )
    try:
        public_key = public_key_from_b64(settings.entitlement_pubkey)
        verify_entitlement(token, public_key)
    except (EntitlementError, ValueError) as error:
        raise ManagerError(
            "license_invalid", "The entitlement could not be verified.", 400
        ) from error
    save_entitlement(settings, token)
    return evaluate_license(settings)


def require_entitled(settings: ManagerSettings) -> None:
    """Raise ManagerError (safe code, no secrets) if the app may not launch profiles."""
    status = evaluate_license(settings)
    if status.allowed:
        return
    code, message = _BLOCK_CODES.get(
        status.state, ("license_invalid", "Your license could not be verified.")
    )
    raise ManagerError(code, message, 403)


def make_license_gate(settings: ManagerSettings):
    """A no-arg callable the runtime calls before each launch."""
    return lambda: require_entitled(settings)
