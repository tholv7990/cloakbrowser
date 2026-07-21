"""Run a redacted Pixelscan regression check against a persistent profile."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cloakbrowser import launch_persistent_context


def redact_proxy(proxy: str) -> str:
    """Return a log-safe proxy string while retaining server information."""
    if "://" in proxy:
        parsed = urlsplit(proxy)
        hostname = parsed.hostname or ""
        host = f"[{hostname}]" if ":" in hostname else hostname
        port = f":{parsed.port}" if parsed.port else ""
        credentials = "***:***@" if parsed.username is not None else ""
        return urlunsplit((parsed.scheme, f"{credentials}{host}{port}", parsed.path, parsed.query, parsed.fragment))

    parts = proxy.split(":")
    if len(parts) >= 4:
        return ":".join([parts[0], parts[1], "***", "***"])
    return proxy


def parse_pixelscan_verdict(text: str) -> dict[str, bool]:
    """Parse the four stable verdicts used by the regression gate."""
    normalized = " ".join(text.lower().split())
    verdict_lines = {" ".join(line.lower().split()) for line in text.splitlines() if line.strip()}
    no_masking = bool(re.search(r"\bno masking detected\b", normalized))
    no_automation = bool(re.search(r"\bno automated behavior detected\b", normalized))
    explicit_consistent = "consistent" in verdict_lines
    explicit_inconsistent = "inconsistent" in verdict_lines
    redesigned_pass = no_masking and no_automation
    return {
        "consistent": (explicit_consistent or redesigned_pass)
        and not explicit_inconsistent,
        "masking_detected": bool(re.search(r"(?<!no )\bmasking detected\b", normalized)),
        "automation_detected": bool(re.search(r"(?<!no )\bautomated behavior detected\b", normalized)),
        "incognito": bool(re.search(r"incognito window\s*:\s*yes", normalized)),
    }


def run_scan(profile_dir: Path, output_dir: Path, proxy: str) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    screenshot = output_dir / f"pixelscan-{stamp}.png"

    context = launch_persistent_context(
        str(profile_dir),
        headless=False,
        proxy=proxy,
        geoip=True,
        humanize=True,
        fingerprint_preset="consistent",
        args=["--fingerprint=63003"],
    )
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://pixelscan.net/", wait_until="domcontentloaded", timeout=90_000)
        scan_button = page.get_by_text(re.compile(r"scan my browser", re.I)).first
        if scan_button.is_visible(timeout=10_000):
            scan_button.click()
        page.get_by_text(re.compile(r"consistent|inconsistent", re.I)).first.wait_for(
            state="visible", timeout=90_000
        )
        page.wait_for_timeout(3_000)
        body_text = page.locator("body").inner_text(timeout=30_000)
        page.screenshot(path=str(screenshot), full_page=True)
    finally:
        context.close()

    verdict = parse_pixelscan_verdict(body_text)
    passed = (
        verdict["consistent"]
        and not verdict["masking_detected"]
        and not verdict["automation_detected"]
        and not verdict["incognito"]
    )
    result: dict[str, object] = {
        "timestamp_utc": stamp,
        "scanner": "pixelscan",
        "proxy": redact_proxy(proxy),
        "profile_dir": str(profile_dir),
        "screenshot": str(screenshot),
        "verdict": verdict,
        "passed": passed,
    }
    result_path = output_dir / f"pixelscan-{stamp}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["result_file"] = str(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, default=Path("artifacts/pixelscan-profile"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/proxy-profile-test"))
    args = parser.parse_args()
    proxy = os.environ.get("CLOAK_TEST_PROXY")
    if not proxy:
        parser.error("CLOAK_TEST_PROXY must contain the proxy URL")

    result = run_scan(args.profile_dir.resolve(), args.output_dir.resolve(), proxy)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
