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
    city: str | None = None
    timezone: str | None = None
    asn: str | None = None
    organization: str | None = None


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
    def __init__(self, *, resolver=resolve_exit_ip):
        self._resolver = resolver

    def run(self, proxy_url: str, timeout_seconds: float = 20) -> QuickTestResult:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="proxy-quick-test")
        try:
            future = executor.submit(self._resolver, proxy_url, attempts=3)
            result = future.result(timeout=timeout_seconds)
            return QuickTestResult(
                exit_ip=str(result["exit_ip"]),
                exit_ip_matches=bool(result["exit_ip_agreement"]),
                latency_ms=round(float(result["latency_median_ms"])),
                checked_at=datetime.now(timezone.utc),
            )
        except FutureTimeout:
            raise ProxyTestFailure("timeout") from None
        except ProxyConnectivityError as error:
            raise ProxyTestFailure(_failure_category(error)) from None
        except Exception as error:
            raise ProxyTestFailure(_failure_category(error)) from None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
