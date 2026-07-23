from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

import pytest

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.features.proxies.service import build_proxy_preflight
from manager_backend.features.proxies.testing import (
    QuickTestResult,
    ProxyTestFailure,
    ScannerQuickTester,
)
from manager_backend.models import Proxy


def _create(client, auth_headers, **changes):
    payload = {
        "label": "Quick test",
        "scheme": "socks5",
        "host": "198.51.100.25",
        "port": 50101,
        "username": "fixture-user",
        "password": "fixture-pass",
        "test_before_launch": True,
    }
    payload.update(changes)
    return client.post("/api/v1/proxies", headers=auth_headers, json=payload).json()


def test_quick_tester_enriches_exit_ip_with_geo():
    def fake_resolver(url, attempts=3):
        return {"exit_ip": "1.2.3.4", "exit_ip_agreement": True, "latency_median_ms": 100.0}

    def fake_geo(ip):
        assert ip == "1.2.3.4"
        return {
            "country": "US", "country_name": "United States", "city": "Dallas",
            "zip_code": "75201", "timezone": "America/Chicago", "latitude": 32.8,
            "longitude": -96.8, "asn": "AS62240", "organization": "Acme",
        }

    result = ScannerQuickTester(resolver=fake_resolver, geo_lookup=fake_geo).run("socks5://h:1")
    assert result.exit_ip == "1.2.3.4"
    assert result.city == "Dallas" and result.country_name == "United States"
    assert result.zip_code == "75201" and result.timezone == "America/Chicago"
    assert result.latitude == 32.8 and result.longitude == -96.8
    assert result.asn == "AS62240" and result.organization == "Acme"


def test_quick_test_returns_and_caches_only_safe_results(client, auth_headers):
    client.app.state.credential_store = MemoryCredentialStore()

    class Tester:
        def __init__(self):
            self.received = None

        def run(self, proxy_url, timeout_seconds=20):
            self.received = (proxy_url, timeout_seconds)
            return QuickTestResult(
                exit_ip="74.0.96.143",
                exit_ip_matches=True,
                latency_ms=184,
                country="US",
                country_name="United States",
                city="Dallas",
                zip_code="75201",
                timezone="America/Chicago",
                latitude=32.7767,
                longitude=-96.797,
                asn="AS212238",
                organization="Datacamp Limited",
                checked_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
            )

    tester = Tester()
    client.app.state.proxy_quick_tester = tester
    proxy = _create(client, auth_headers)
    response = client.post(f"/api/v1/proxies/{proxy['id']}/quick-test", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "connectivity": True,
        "exit_ip": "74.0.96.143",
        "exit_ip_matches": True,
        "latency_ms": 184,
        "country": "US",
        "country_name": "United States",
        "city": "Dallas",
        "zip_code": "75201",
        "timezone": "America/Chicago",
        "latitude": 32.7767,
        "longitude": -96.797,
        "asn": "AS212238",
        "organization": "Datacamp Limited",
        "checked_at": "2026-07-21T00:00:00Z",
        "error": None,
    }
    assert tester.received[1] == 20
    assert "fixture-user" in tester.received[0]
    assert "fixture-pass" in tester.received[0]
    serialized = str(body)
    assert "fixture-user" not in serialized and "fixture-pass" not in serialized
    cached = client.get(f"/api/v1/proxies/{proxy['id']}").json()
    assert cached["exit_ip"] == "74.0.96.143"
    assert cached["city"] == "Dallas"
    assert cached["latency_ms"] == 184


def test_adhoc_quick_test_uses_typed_values_without_persisting(client, auth_headers):
    class Tester:
        def __init__(self):
            self.received = None

        def run(self, proxy_url, timeout_seconds=20):
            self.received = (proxy_url, timeout_seconds)
            return QuickTestResult(
                exit_ip="74.0.96.143",
                exit_ip_matches=True,
                latency_ms=184,
                country="US",
                country_name="United States",
                city="Dallas",
                zip_code="75201",
                timezone="America/Chicago",
                latitude=32.7767,
                longitude=-96.797,
                asn="AS212238",
                organization="Datacamp Limited",
                checked_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
            )

    tester = Tester()
    client.app.state.proxy_quick_tester = tester
    before = client.get("/api/v1/proxies", headers=auth_headers).json()
    response = client.post(
        "/api/v1/proxies/test",
        headers=auth_headers,
        json={
            "scheme": "socks5",
            "host": "198.51.100.25",
            "port": 50101,
            "username": "typed-user",
            "password": "typed-pass",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["exit_ip"] == "74.0.96.143"
    # Typed creds go into the transient connection URL...
    assert "typed-user" in tester.received[0] and "typed-pass" in tester.received[0]
    # ...but never come back in the response.
    assert "typed-user" not in str(body) and "typed-pass" not in str(body)
    # Nothing is persisted — the proxy list is unchanged.
    after = client.get("/api/v1/proxies", headers=auth_headers).json()
    assert len(after) == len(before)


def test_apply_proxy_geo_stamps_timezone_only_for_geo_mode_proxy():
    from manager_backend.features.proxies.service import _apply_proxy_geo

    result = QuickTestResult(
        exit_ip="172.120.41.88",
        exit_ip_matches=True,
        latency_ms=120,
        country="US",
        country_name="United States",
        city="Las Vegas",
        zip_code="89101",
        timezone="America/Los_Angeles",
        latitude=36.17,
        longitude=-115.14,
        asn="AS62240",
        organization="IWIHOST",
        checked_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    # geo_mode="proxy": the exit-IP timezone + a matching locale are stamped on.
    proxy_snap = {"location": {"geo_mode": "proxy"}, "timezone": None, "locale": None}
    _apply_proxy_geo(proxy_snap, result)
    assert proxy_snap["timezone"] == "America/Los_Angeles"
    assert proxy_snap["locale"] == "en-US"

    # geo_mode="system": left alone (browser follows the host).
    system_snap = {"location": {"geo_mode": "system"}, "timezone": None, "locale": None}
    _apply_proxy_geo(system_snap, result)
    assert system_snap["timezone"] is None and system_snap["locale"] is None

    # An explicit locale is preserved; timezone still tracks the proxy.
    kept = {"location": {"geo_mode": "proxy"}, "timezone": None, "locale": "fr-FR"}
    _apply_proxy_geo(kept, result)
    assert kept["locale"] == "fr-FR" and kept["timezone"] == "America/Los_Angeles"


def test_adhoc_quick_test_rejects_direct(client, auth_headers):
    response = client.post(
        "/api/v1/proxies/test",
        headers=auth_headers,
        json={"scheme": "direct", "host": "", "port": None},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "proxy_test_not_applicable"


def test_quick_test_maps_transport_failure_to_safe_category(client, auth_headers):
    client.app.state.credential_store = MemoryCredentialStore()

    class Tester:
        def run(self, _proxy_url, timeout_seconds=20):
            raise ProxyTestFailure("authentication_failed")

    client.app.state.proxy_quick_tester = Tester()
    proxy = _create(client, auth_headers)
    response = client.post(f"/api/v1/proxies/{proxy['id']}/quick-test", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "authentication_failed"


def test_direct_proxy_quick_test_is_rejected(client, auth_headers):
    client.app.state.credential_store = MemoryCredentialStore()
    proxy = _create(
        client,
        auth_headers,
        label="Direct",
        scheme="direct",
        host="",
        port=None,
        username=None,
        password=None,
    )
    response = client.post(f"/api/v1/proxies/{proxy['id']}/quick-test", headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "proxy_test_not_applicable"


def test_scanner_quick_test_honors_total_timeout_budget():
    def slow_resolver(_proxy_url, *, attempts):
        time.sleep(0.2)
        return {}

    tester = ScannerQuickTester(resolver=slow_resolver)
    started = time.monotonic()
    try:
        tester.run("socks5://proxy.example:1080", timeout_seconds=0.02)
    except ProxyTestFailure as error:
        assert error.category == "timeout"
    else:
        raise AssertionError("expected timeout")
    assert time.monotonic() - started < 0.15


def test_fast_proxy_test_bounds_resolver_and_geo_by_one_deadline():
    def resolver(_proxy_url, *, attempts):
        assert attempts == 2
        return {
            "exit_ip": "1.2.3.4",
            "exit_ip_agreement": True,
            "latency_median_ms": 10.0,
        }

    def slow_geo(_ip):
        time.sleep(0.2)
        return {"country": "US"}

    tester = ScannerQuickTester(resolver=resolver, geo_lookup=slow_geo)
    started = time.monotonic()
    with pytest.raises(ProxyTestFailure) as caught:
        tester.run_fast("socks5://proxy.example:1080", timeout_seconds=0.02)

    assert caught.value.category == "timeout"
    assert time.monotonic() - started < 0.15


def test_preflight_skips_tester_when_profile_check_is_disabled(db_session_factory):
    proxy = Proxy(
        label="No launch test",
        scheme="socks5",
        host="proxy.example",
        port=1080,
    )
    with db_session_factory() as session:
        session.add(proxy)
        session.commit()
        proxy_id = proxy.id

    class UnexpectedTester:
        def run(self, *_args, **_kwargs):
            raise AssertionError("disabled launch check must not call the tester")

    snapshot = {
        "proxy_id": proxy_id,
        "test_proxy_before_launch": False,
        "location": {"geo_mode": "system"},
    }
    preflight = build_proxy_preflight(
        db_session_factory, MemoryCredentialStore(), UnexpectedTester()
    )

    assert preflight(snapshot) == "socks5://proxy.example:1080"


def test_preflight_skips_tester_when_proxy_check_is_disabled(db_session_factory):
    proxy = Proxy(
        label="Proxy-level launch check disabled",
        scheme="socks5",
        host="proxy.example",
        port=1080,
        test_before_launch=False,
    )
    with db_session_factory() as session:
        session.add(proxy)
        session.commit()
        proxy_id = proxy.id

    class UnexpectedTester:
        def run_fast(self, *_args, **_kwargs):
            raise AssertionError("disabled proxy check must not call the tester")

    snapshot = {
        "proxy_id": proxy_id,
        "test_proxy_before_launch": True,
        "location": {"geo_mode": "system"},
    }
    preflight = build_proxy_preflight(
        db_session_factory, MemoryCredentialStore(), UnexpectedTester()
    )

    assert preflight(snapshot) == "socks5://proxy.example:1080"


def test_preflight_reuses_recent_successful_proxy_result(db_session_factory):
    checked_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    proxy = Proxy(
        label="Fresh launch check",
        scheme="socks5",
        host="proxy.example",
        port=1080,
        exit_ip="203.0.113.8",
        country="US",
        timezone="America/Chicago",
        latency_ms=80,
        last_checked_at=checked_at,
    )
    with db_session_factory() as session:
        session.add(proxy)
        session.commit()
        proxy_id = proxy.id
        original_updated_at = proxy.updated_at

    class UnexpectedTester:
        def run_fast(self, *_args, **_kwargs):
            raise AssertionError("fresh successful result must be reused")

    snapshot = {
        "proxy_id": proxy_id,
        "test_proxy_before_launch": True,
        "location": {"geo_mode": "proxy"},
        "locale": None,
        "timezone": None,
    }
    preflight = build_proxy_preflight(
        db_session_factory, MemoryCredentialStore(), UnexpectedTester()
    )

    assert preflight(snapshot) == "socks5://proxy.example:1080"
    assert snapshot["timezone"] == "America/Chicago"
    assert snapshot["locale"] == "en-US"
    assert snapshot["proxy_exit_ip"] == "203.0.113.8"
    with db_session_factory() as session:
        assert session.get(Proxy, proxy_id).updated_at.replace(
            tzinfo=None
        ) == original_updated_at.replace(tzinfo=None)


def test_preflight_rechecks_stale_proxy_result(db_session_factory):
    proxy = Proxy(
        label="Stale launch check",
        scheme="socks5",
        host="proxy.example",
        port=1080,
        exit_ip="203.0.113.8",
        last_checked_at=datetime.now(timezone.utc) - timedelta(seconds=61),
    )
    with db_session_factory() as session:
        session.add(proxy)
        session.commit()
        proxy_id = proxy.id

    class Tester:
        called = False

        def run_fast(self, _proxy_url, timeout_seconds=5):
            self.called = True
            return QuickTestResult(
                exit_ip="203.0.113.9",
                exit_ip_matches=True,
                latency_ms=90,
                checked_at=datetime.now(timezone.utc),
            )

    tester = Tester()
    snapshot = {
        "proxy_id": proxy_id,
        "test_proxy_before_launch": True,
        "location": {"geo_mode": "system"},
    }
    preflight = build_proxy_preflight(
        db_session_factory, MemoryCredentialStore(), tester
    )

    assert preflight(snapshot) == "socks5://proxy.example:1080"
    assert tester.called is True
    assert snapshot["proxy_exit_ip"] == "203.0.113.9"
