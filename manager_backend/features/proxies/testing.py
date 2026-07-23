from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from benchmarks.proxy_intelligence import ProxyConnectivityError, resolve_exit_ip


class ProxyTestFailure(Exception):
    def __init__(self, category: str):
        self.category = category


@dataclass(frozen=True, slots=True)
class QuickTestResult:
    exit_ip: str
    exit_ip_matches: bool
    latency_ms: int
    checked_at: datetime
    country: str | None = None
    country_name: str | None = None
    city: str | None = None
    zip_code: str | None = None
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    asn: str | None = None
    organization: str | None = None


def lookup_geo(ip: str) -> dict:
    """Best-effort geolocation of an exit IP (country, city, zip, tz, lat/lon, ASN,
    org). Uses ipwho.is (free, no key), falling back to ip-api.com. {} on failure."""
    import httpx

    try:
        data = httpx.get(f"https://ipwho.is/{ip}", timeout=8.0).json()
        if data.get("success"):
            conn = data.get("connection") or {}
            asn = conn.get("asn")
            return {
                "country": data.get("country_code") or None,
                "country_name": data.get("country") or None,
                "city": data.get("city") or None,
                "zip_code": data.get("postal") or None,
                "timezone": (data.get("timezone") or {}).get("id") or None,
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "asn": f"AS{asn}" if asn else None,
                "organization": (conn.get("org") or conn.get("isp")) or None,
            }
    except Exception:
        pass
    try:
        data = httpx.get(
            f"http://ip-api.com/json/{ip}"
            "?fields=status,countryCode,country,city,zip,timezone,lat,lon,as,org,isp",
            timeout=8.0,
        ).json()
        if data.get("status") == "success":
            as_field = str(data.get("as") or "")
            return {
                "country": data.get("countryCode") or None,
                "country_name": data.get("country") or None,
                "city": data.get("city") or None,
                "zip_code": data.get("zip") or None,
                "timezone": data.get("timezone") or None,
                "latitude": data.get("lat"),
                "longitude": data.get("lon"),
                "asn": as_field.split()[0] if as_field else None,
                "organization": (data.get("org") or data.get("isp")) or None,
            }
    except Exception:
        pass
    return {}


def _failure_category(error: Exception) -> str:
    text = str(error).casefold()
    if "auth" in text or "407" in text:
        return "authentication_failed"
    if "refused" in text:
        return "connection_refused"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "dns" in text or "name resolution" in text:
        return "dns_failed"
    return "upstream_unavailable"


class ScannerQuickTester:
    def __init__(self, *, resolver=resolve_exit_ip, geo_lookup=lookup_geo):
        self._resolver = resolver
        self._geo_lookup = geo_lookup

    def run(self, proxy_url: str, timeout_seconds: float = 20) -> QuickTestResult:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="proxy-quick-test")
        try:
            future = executor.submit(self._resolver, proxy_url, attempts=3)
            result = future.result(timeout=timeout_seconds)
            exit_ip = str(result["exit_ip"])
            geo = self._geo_lookup(exit_ip) or {}
            return QuickTestResult(
                exit_ip=exit_ip,
                exit_ip_matches=bool(result["exit_ip_agreement"]),
                latency_ms=round(float(result["latency_median_ms"])),
                checked_at=datetime.now(timezone.utc),
                country=geo.get("country"),
                country_name=geo.get("country_name"),
                city=geo.get("city"),
                zip_code=geo.get("zip_code"),
                timezone=geo.get("timezone"),
                latitude=geo.get("latitude"),
                longitude=geo.get("longitude"),
                asn=geo.get("asn"),
                organization=geo.get("organization"),
            )
        except FutureTimeout:
            raise ProxyTestFailure("timeout") from None
        except ProxyConnectivityError as error:
            raise ProxyTestFailure(_failure_category(error)) from None
        except Exception as error:
            raise ProxyTestFailure(_failure_category(error)) from None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
