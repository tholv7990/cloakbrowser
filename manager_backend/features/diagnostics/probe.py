"""First-party fingerprint probe (F-020, backbone for F-003/F-004).

Collects browser-exposed surfaces from a launched profile, normalizes them into a
schema-versioned result, redacts local paths / the machine username, and separates
raw observation from computed verdict. Collects no cookies, history, or credentials
and never phones home — see docs/research/fingerprint-assurance/07-external-checker-policy.md.

This module is the pure, testable core. Wiring it to a live launch (an isolated-world
evaluate against the real binary) is a follow-up; `run_probe` takes an injected
evaluator so tests drive it with fixture data.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


PROBE_SCHEMA_VERSION = 1

# The live probe launches the real binary; it is opt-in so the default build never
# spawns a browser for a probe. A binary-backed environment sets this to run it.
LIVE_PROBE_ENV = "CLOAK_LIVE_DIAGNOSTICS"

# In-page collector: a self-contained async expression returning the raw surfaces.
# Async so it can render a real audio fingerprint (OfflineAudioContext.startRendering
# is a promise). Every surface is guarded so one failure can't blank the collection.
# It reads only fingerprint-relevant properties — no cookies, storage, or history.
# Client Hints (userAgentData) only populate in a secure context, so a real read needs
# an https page (see default_probe_page's optional navigation).
COLLECTOR_JS = r"""(async () => {
  const safe = (fn, fallback) => { try { return fn(); } catch (e) { return fallback; } };
  const uaData = navigator.userAgentData || null;
  const clientHints = uaData
    ? await safe(
        () => uaData.getHighEntropyValues(['platform', 'platformVersion', 'architecture', 'bitness', 'uaFullVersion']),
        { platform: uaData.platform, mobile: uaData.mobile }
      )
    : null;
  const audio = await (async () => {
    try {
      const Ctor = window.OfflineAudioContext || window.webkitOfflineAudioContext;
      const ctx = new Ctor(1, 5000, 44100);
      const osc = ctx.createOscillator(); osc.type = 'triangle'; osc.frequency.value = 10000;
      const comp = ctx.createDynamicsCompressor();
      osc.connect(comp); comp.connect(ctx.destination); osc.start(0);
      const buffer = await ctx.startRendering();
      const data = buffer.getChannelData(0);
      let sum = 0; for (let i = 4000; i < 5000; i++) sum += Math.abs(data[i]);
      return sum.toString();
    } catch (e) { return null; }
  })();
  return {
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    userAgentData: clientHints,
    languages: safe(() => Array.from(navigator.languages), []),
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: safe(() => navigator.deviceMemory, null),
    webdriver: navigator.webdriver === true,
    vendor: navigator.vendor,
    screen: { width: screen.width, height: screen.height, colorDepth: screen.colorDepth },
    window: {
      outerWidth: window.outerWidth, outerHeight: window.outerHeight,
      innerWidth: window.innerWidth, innerHeight: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    intl: safe(() => {
      const o = Intl.DateTimeFormat().resolvedOptions();
      return { timeZone: o.timeZone, locale: o.locale };
    }, {}),
    canvas: safe(() => {
      const c = document.createElement('canvas'); c.width = 200; c.height = 40;
      const ctx = c.getContext('2d');
      ctx.textBaseline = 'top'; ctx.font = '14px Arial';
      ctx.fillText('CloakBrowser probe', 2, 2);
      return c.toDataURL().slice(-64);
    }, null),
    webgl: safe(() => {
      const gl = document.createElement('canvas').getContext('webgl');
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      return {
        vendor: gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL),
        renderer: gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL),
      };
    }, null),
    audio: audio,
    nativeIntegrity: safe(() => ({
      // A patched getter reveals a JS shim here instead of "[native code]".
      hardwareConcurrencyGetter: Object.getOwnPropertyDescriptor(
        Navigator.prototype, 'hardwareConcurrency'
      ).get.toString(),
    }), {}),
  };
})()"""


_USERNAME_PLACEHOLDER = "<redacted>"
_PATH_PLACEHOLDER = "<redacted-path>"
# Windows drive paths and POSIX home paths — the shapes a leaked local path takes.
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\"'\s]+|/(?:home|Users)/[^\"'\s]+")


def _redact_string(value: str, host_username: str | None) -> str:
    redacted = _PATH_RE.sub(_PATH_PLACEHOLDER, value)
    if host_username:
        redacted = redacted.replace(host_username, _USERNAME_PLACEHOLDER)
    return redacted


def _redact(value: Any, host_username: str | None) -> Any:
    if isinstance(value, str):
        return _redact_string(value, host_username)
    if isinstance(value, dict):
        return {key: _redact(item, host_username) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, host_username) for item in value]
    return value


def _verdict(raw: dict) -> dict:
    """Cross-layer coherence judgments — computed from raw values, never conflated
    with them. Single-run only (stability/separation are comparison suites)."""
    ua = raw.get("userAgent") or ""
    platform = raw.get("platform") or ""
    ua_data_platform = (raw.get("userAgentData") or {}).get("platform") or ""
    ua_platform = (
        "coherent"
        if "Windows" in ua
        and platform.startswith("Win")
        and ua_data_platform in ("", "Windows")
        else "contradictory"
    )
    window = raw.get("window") or {}
    screen = raw.get("screen") or {}
    within_screen = window.get("outerWidth", 0) <= screen.get("width", 0) and window.get(
        "outerHeight", 0
    ) <= screen.get("height", 0)
    getter = (raw.get("nativeIntegrity") or {}).get("hardwareConcurrencyGetter")
    if getter is None:
        native_integrity = "unknown"
    elif "[native code]" in getter:
        native_integrity = "intact"
    else:
        native_integrity = "tampered"
    return {
        "ua_platform": ua_platform,
        "window_within_screen": "coherent" if within_screen else "contradictory",
        "automation": "detected" if raw.get("webdriver") else "clean",
        "native_integrity": native_integrity,
    }


def normalize_probe(raw: dict, *, host_username: str | None = None) -> dict:
    """Wrap a raw collection into the schema-versioned probe result: separate raw
    (redacted) observation from the computed verdict."""
    return {
        "probe_schema_version": PROBE_SCHEMA_VERSION,
        "raw": _redact(raw, host_username),
        "verdict": _verdict(raw),
    }


def run_probe(
    evaluate: Callable[[str], dict], *, host_username: str | None = None
) -> dict:
    """Collect via the injected evaluator (live: an isolated-world page evaluate;
    tests: a fixture stub) and normalize the result."""
    raw = evaluate(COLLECTOR_JS)
    return normalize_probe(raw, host_username=host_username)


def probe_status_and_findings(normalized: dict) -> tuple[str, dict[str, str]]:
    """Map a normalized probe into a diagnostic outcome. A cross-layer contradiction
    fails; an automation marker, tampered native API, or an unverifiable surface
    warns; otherwise it passes. Findings are the enum verdicts only — no PII."""
    verdict = normalized["verdict"]
    findings = {
        "ua_platform": verdict["ua_platform"],
        "window_within_screen": verdict["window_within_screen"],
        "automation": verdict["automation"],
        "native_integrity": verdict["native_integrity"],
    }
    contradictory = (
        verdict["ua_platform"] == "contradictory"
        or verdict["window_within_screen"] == "contradictory"
    )
    flagged = (
        verdict["automation"] == "detected"
        or verdict["native_integrity"] in ("tampered", "unknown")
    )
    status = "failed" if contradictory else ("warning" if flagged else "passed")
    return status, findings


def live_probe_enabled() -> bool:
    return os.environ.get(LIVE_PROBE_ENV) == "1"


# Signature of an injected page opener: given a launch snapshot, yield an evaluate()
# that runs a script in the browser and returns its value.
ProbePageOpener = Callable[[dict], Any]


def run_live_probe(
    snapshot: dict,
    *,
    open_probe_page: ProbePageOpener,
    host_username: str | None = None,
) -> dict:
    """Orchestrate a live probe: open a page over a launched profile, collect+normalize,
    and map to a diagnostic status. ``open_probe_page`` is injected — live uses
    ``default_probe_page`` (the real binary); tests use a fixture. Nothing here spawns
    a browser, so the orchestration is deterministically testable."""
    with open_probe_page(snapshot) as evaluate:
        normalized = run_probe(evaluate, host_username=host_username)
    status, findings = probe_status_and_findings(normalized)
    return {"status": status, "findings": findings, "probe": normalized}


@contextmanager
def default_probe_page(snapshot: dict) -> Iterator[Callable[[str], dict]]:
    """Real headless launch + isolated-world evaluator over the profile's exact launch
    snapshot.

    NEEDS BINARY VALIDATION: this spawns the closed CloakBrowser binary and drives it
    over CDP; it is never exercised by unit tests and only runs when a caller opts in
    (see ``live_probe_enabled``). The collector runs in an isolated world so it is not
    visible to page scripts and leaks no automation signal (mirrors the human/ layer).
    """
    import cloakbrowser

    from ..runtime.launcher import persistent_context_kwargs

    context = cloakbrowser.launch_persistent_context(
        str(snapshot["profile_dir"] / "user-data"),
        **persistent_context_kwargs(snapshot, headless=True),
    )
    try:
        page = context.new_page()
        # Client Hints (userAgentData) only populate in a secure context, so an https
        # probe_url gives a real read; the default about:blank cannot (F-008-CH).
        probe_url = snapshot.get("probe_url")
        if probe_url:
            page.goto(probe_url, wait_until="commit", timeout=20000)
        cdp = context.new_cdp_session(page)
        frame_id = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        world = cdp.send("Page.createIsolatedWorld", {"frameId": frame_id})
        context_id = world["executionContextId"]

        def evaluate(script: str) -> dict:
            response = cdp.send(
                "Runtime.evaluate",
                {
                    "expression": script,
                    "contextId": context_id,
                    "returnByValue": True,
                    "awaitPromise": True,  # the collector is async (real audio render)
                },
            )
            return response["result"]["value"]

        yield evaluate
    finally:
        try:
            context.close()
        except Exception:
            pass
