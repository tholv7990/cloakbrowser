from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from benchmarks.proxy_quality import run_proxy_quality_scan

from ...models import ProxyQualityRun
from .service import resolve_proxy_url


_SCOPE = "Timestamped observation; not a permanent cleanliness guarantee."


def recover_orphan_quality_runs(session_factory) -> int:
    with session_factory() as session:
        runs = list(
            session.query(ProxyQualityRun).filter(
                ProxyQualityRun.state.in_({"queued", "running"})
            )
        )
        for run in runs:
            run.state = "failed"
            run.last_message = "manager_restarted"
            run.checked_at = datetime.now(timezone.utc)
        session.commit()
        return len(runs)


def _finding(status="unknown", detail="No observation was available."):
    return {"status": status, "detail": detail}


def map_scanner_report(run: ProxyQualityRun, raw: dict) -> dict:
    connectivity = raw.get("connectivity") if isinstance(raw.get("connectivity"), dict) else {}
    classification = raw.get("classification") if isinstance(raw.get("classification"), dict) else {}
    sites = raw.get("site_outcomes") if isinstance(raw.get("site_outcomes"), dict) else {}
    reputation_data = raw.get("reputation_intelligence") if isinstance(raw.get("reputation_intelligence"), dict) else {}
    matches = reputation_data.get("high_confidence_matches") or []
    match_names = [str(item.get("source")) for item in matches if isinstance(item, dict) and item.get("source")]
    alignment = {name: _finding() for name in ("http", "webrtc", "dns", "timezone", "locale")}
    return {
        "id": run.id,
        "proxy_id": run.proxy_id,
        "state": "completed",
        "proxy_type": classification.get("type") or classification.get("network_type") or "unknown",
        "type_confidence": classification.get("confidence"),
        "reputation": "suspicious" if match_names else "clean",
        "matched_lists": match_names,
        "google_outcome": (sites.get("google") or {}).get("verdict"),
        "turnstile_outcome": (sites.get("cloudflare") or {}).get("verdict"),
        "alignment": alignment,
        "latency_ms": round(float(connectivity["latency_median_ms"])) if connectivity.get("latency_median_ms") is not None else None,
        "exit_ip": connectivity.get("exit_ip"),
        "country": None,
        "city": None,
        "timezone": None,
        "asn": None,
        "organization": None,
        "screenshot_path": None,
        "report_path": None,
        "observed_scope": _SCOPE,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


class ProxyQualityManager:
    def __init__(self, session_factory, store, settings, *, scanner=run_proxy_quality_scan):
        self._session_factory = session_factory
        self._store = store
        self._settings = settings
        self._scanner = scanner
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="proxy-quality")

    def submit(self, run_id: str) -> None:
        self._executor.submit(self._execute, run_id)

    def _execute(self, run_id: str) -> None:
        with self._session_factory() as session:
            run = session.get(ProxyQualityRun, run_id)
            if run is None:
                return
            run.state = "running"
            run.last_message = "running"
            session.commit()
            try:
                proxy_url = resolve_proxy_url(session, self._store, run.proxy_id)
                if proxy_url is None:
                    raise ValueError
                raw = self._scanner(
                    proxy_url,
                    self._settings.data_root / "diagnostics" / "proxy-quality" / run.id,
                    browser_checks=True,
                    ipinfo_token=os.environ.get("IPINFO_TOKEN") or None,
                )
                run.report = map_scanner_report(run, raw)
                run.state = "completed"
                run.last_message = "completed"
                run.checked_at = datetime.now(timezone.utc)
            except Exception:
                run.state = "failed"
                run.last_message = "proxy_quality_failed"
                run.checked_at = datetime.now(timezone.utc)
            session.commit()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
