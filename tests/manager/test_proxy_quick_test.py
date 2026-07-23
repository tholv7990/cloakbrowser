from __future__ import annotations

from datetime import datetime, timezone
import time

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.features.proxies.testing import (
    QuickTestResult,
    ProxyTestFailure,
    ScannerQuickTester,
)


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
