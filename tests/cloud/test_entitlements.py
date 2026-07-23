from __future__ import annotations

import pytest

from cloud.entitlements import (
    EntitlementError,
    generate_signing_keypair,
    public_key_from_b64,
    public_key_to_b64,
    sign_entitlement,
    verify_entitlement,
)


def _claims() -> dict:
    return {
        "sub": "account-1",
        "device_id": "device-1",
        "plan": "pro",
        "features": ["media", "automation"],
        "profile_limit": 100,
        "session_limit": 10,
        "iat": 1_700_000_000,
        "exp": 1_700_086_400,
        "offline_grace_deadline": 1_700_604_800,
        "entitlement_version": 3,
    }


def test_sign_then_verify_round_trips_the_claims():
    private_key, public_key = generate_signing_keypair()
    token = sign_entitlement(_claims(), private_key)
    assert verify_entitlement(token, public_key) == _claims()


def test_pinned_public_key_survives_base64_round_trip():
    private_key, public_key = generate_signing_keypair()
    token = sign_entitlement(_claims(), private_key)
    # The desktop ships the public key as base64 and rebuilds it — must still verify.
    rebuilt = public_key_from_b64(public_key_to_b64(public_key))
    assert verify_entitlement(token, rebuilt)["plan"] == "pro"


def test_tampered_payload_is_rejected():
    private_key, public_key = generate_signing_keypair()
    token = sign_entitlement(_claims(), private_key)
    header, payload, signature = token.split(".")
    # Flip a character in the payload segment.
    forged_payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    with pytest.raises(EntitlementError):
        verify_entitlement(f"{header}.{forged_payload}.{signature}", public_key)


def test_a_different_key_cannot_verify():
    private_key, _public_key = generate_signing_keypair()
    _other_private, other_public = generate_signing_keypair()
    token = sign_entitlement(_claims(), private_key)
    with pytest.raises(EntitlementError):
        verify_entitlement(token, other_public)


def test_malformed_token_is_rejected():
    _private, public_key = generate_signing_keypair()
    with pytest.raises(EntitlementError):
        verify_entitlement("not-a-jws", public_key)
