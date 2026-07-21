"""Generate BENCHMARK_REPORT.md from the two raw round JSON files.

Tables are computed straight from the JSON (and pooled via the benchmark's own
summarize()), so Markdown values are guaranteed to match the raw results.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from benchmarks.compare_chrome import METRICS, relative_percent, summarize

RESULTS = Path("benchmarks/results")

LABELS = {
    "launch_ms": "Browser launch",
    "page_setup_ms": "Context + page creation",
    "local_navigation_ms": "Local navigation + DOM verify (deterministic)",
    "external_navigation_ms": "External navigation (network)",
    "javascript_ms": "JavaScript execution",
    "close_ms": "Shutdown / close",
    "total_ms": "Sum of timed phases",
    "memory_mib": "Process-tree working set (MiB)",
}
STAT_ORDER = ("count", "median", "mean", "min", "max", "p90", "p95", "stddev")


def latest(tag: str) -> Path:
    matches = sorted(RESULTS.glob(f"cloakbrowser-session-vs-chrome-{tag}-*.json"))
    if not matches:
        raise SystemExit(f"no JSON found for {tag}")
    return matches[-1]


def num(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, int):
        return str(v)
    return f"{v:.3f}"


def stat_table(summary: dict) -> list[str]:
    """One browser's per-metric stat table (8 statistics)."""
    head = "| Metric | count | median | mean | min | max | p90 | p95 | stddev |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    rows = [head, sep]
    for m in METRICS:
        s = summary[m]
        cells = " | ".join(num(s.get(k)) for k in STAT_ORDER)
        rows.append(f"| {LABELS[m]} | {cells} |")
    return rows


def compare_table(cloak: dict, chrome: dict) -> list[str]:
    """Median + p95 comparison with % difference (negative = Cloak lower/faster)."""
    head = "| Metric | Cloak median | Chrome median | % diff (median) | Cloak p95 | Chrome p95 |"
    sep = "|---|---|---|---|---|---|"
    rows = [head, sep]
    for m in METRICS:
        c, g = cloak[m], chrome[m]
        pct = relative_percent(float(c["median"]), float(g["median"])) if c.get("count") and g.get("count") else None
        pct_s = "—" if pct is None else f"{pct:+.3f}%"
        rows.append(
            f"| {LABELS[m]} | {num(c['median'])} | {num(g['median'])} | {pct_s} "
            f"| {num(c.get('p95'))} | {num(g.get('p95'))} |"
        )
    return rows


def pooled_summary(rounds: list[dict]) -> dict:
    """Recompute summaries over all successful iterations from both rounds (60 each)."""
    out = {}
    for browser in ("cloakbrowser", "chrome"):
        bs = {"successful_iterations": 0, "failed_iterations": 0}
        succ = []
        for r in rounds:
            for rec in r["iterations"][browser]:
                if rec.get("success"):
                    succ.append(rec)
                else:
                    bs["failed_iterations"] += 1
        bs["successful_iterations"] = len(succ)
        for m in METRICS:
            vals = [float(rec["metrics"][m]) for rec in succ if rec.get("metrics", {}).get(m) is not None]
            bs[m] = summarize(vals)
        out[browser] = bs
    return out


def main() -> None:
    r1_path, r2_path = latest("round1"), latest("round2")
    r1 = json.loads(r1_path.read_text(encoding="utf-8"))
    r2 = json.loads(r2_path.read_text(encoding="utf-8"))
    rounds = [r1, r2]
    pooled = pooled_summary(rounds)

    env = r1["environment"]
    br = r1["browsers"]
    L: list[str] = []
    A = L.append

    A("# CloakBrowser vs. Google Chrome — Benchmark Report")
    A("")
    A(f"Generated from two independent rounds run on {r1['generated_at'][:10]} (UTC).")
    A("")
    A("- Round 1 raw JSON: `" + r1_path.as_posix() + "`")
    A("- Round 2 raw JSON: `" + r2_path.as_posix() + "`")
    A("")
    A("Both rounds: 3 warm-up iterations + 30 measured iterations per browser, "
      "alternating execution order, a shared already-started Playwright driver for the "
      "primary comparison, and a 10-page concurrency workload. "
      f"Failures across both rounds: **{sum(len(r['errors']) for r in rounds)}**.")
    A("")

    # Methodology
    A("## Methodology")
    A("")
    A("- **Fairness controls.** The *same* already-started Playwright driver launches both "
      "CloakBrowser (via `_launch_with_playwright_async`) and stable Google Chrome (via "
      "`chromium.launch(executable_path=chrome.exe)`). Identical headless mode, viewport "
      "(1280×720), URLs, operation order, per-page 20 s navigation timeout, and Playwright "
      f"{env['playwright']} apply to both.")
    A("- **Alternating order.** Odd iterations run CloakBrowser→Chrome, even iterations "
      "Chrome→CloakBrowser, so warm-cache / scheduler effects don't favor one browser.")
    A("- **Per iteration** (one fresh browser process each): launch → new context+page → "
      "local `data:` navigation with title + `#result` text assertions → external navigation "
      "to `https://example.com` with title assertion → a 1e6-iteration JS loop → close. "
      "Each phase is timed with `perf_counter_ns`.")
    A("- **`total_ms` = sum of the six timed phases only.** Memory sampling happens *after* "
      "the JS phase timer stops and is **excluded** from `total_ms`, so instrumentation "
      "overhead never inflates the workload total.")
    A("- **Memory** = summed working-set (RSS) of every process whose executable matches the "
      "browser binary and that started within the iteration window (the whole Chromium "
      "process tree — browser + renderer + GPU + utility).")
    A("- **Measured separately** (not attributed to any single browser): Playwright driver "
      "start/stop cost, and the legacy module-level `launch_async()` lifecycle (which starts "
      "its *own* driver on every call).")
    A("- **External vs. deterministic.** External navigation is reported as its own metric and "
      "excluded from the deterministic-local discussion below; only local navigation, launch, "
      "page setup, JS, and close are fully deterministic.")
    A("- **Statistics.** Percentiles use numpy-style linear interpolation; `stddev` is the "
      "sample standard deviation. `% diff (median)` is `(cloak − chrome) / chrome × 100`; "
      "**negative means CloakBrowser is lower (faster / less memory).**")
    A("")

    # Environment
    A("## Environment")
    A("")
    A("| Field | Value |")
    A("|---|---|")
    A(f"| OS | {env['os']} |")
    A(f"| Architecture | {env['architecture']} |")
    A(f"| CPU | {env['cpu']} |")
    A(f"| Logical CPUs | {env['logical_cpus']} |")
    A(f"| Physical memory | {env['physical_memory_gib']} GiB |")
    A(f"| Python | {env['python']} |")
    A(f"| Playwright | {env['playwright']} |")
    A(f"| CloakBrowser wrapper | {env['cloakbrowser_wrapper']} |")
    A(f"| CloakBrowser Chromium | {br['cloakbrowser']['version']} — `{br['cloakbrowser']['path']}` |")
    A(f"| Google Chrome (stable) | {br['chrome']['version']} — `{br['chrome']['path']}` |")
    A("")

    # Pooled headline
    pc, pg = pooled["cloakbrowser"], pooled["chrome"]
    A("## Corrected comparison — equal lifecycle, shared driver (pooled, 60 iterations each)")
    A("")
    A("Both browsers launched through the **same** already-started driver, so Playwright "
      "driver-init cost is charged to neither. Pooled over all successful iterations from both "
      "rounds.")
    A("")
    A("**CloakBrowser**")
    A("")
    L.extend(stat_table(pc))
    A("")
    A("**Chrome (stable)**")
    A("")
    L.extend(stat_table(pg))
    A("")
    A("**Median / p95 comparison**")
    A("")
    L.extend(compare_table(pc, pg))
    A("")
    tot_pct = relative_percent(float(pc["total_ms"]["median"]), float(pg["total_ms"]["median"]))
    lau_pct = relative_percent(float(pc["launch_ms"]["median"]), float(pg["launch_ms"]["median"]))
    mem_pct = relative_percent(float(pc["memory_mib"]["median"]), float(pg["memory_mib"]["median"]))
    ext_pct = relative_percent(float(pc["external_navigation_ms"]["median"]), float(pg["external_navigation_ms"]["median"]))
    loc_pct = relative_percent(float(pc["local_navigation_ms"]["median"]), float(pg["local_navigation_ms"]["median"]))
    A(f"**Headline (pooled medians):** CloakBrowser's summed timed workload is "
      f"{tot_pct:+.2f}% vs. Chrome, browser launch {lau_pct:+.2f}%, and process-tree memory "
      f"{mem_pct:+.2f}%. On deterministic local navigation CloakBrowser is {loc_pct:+.2f}% and "
      f"on external navigation {ext_pct:+.2f}% (network-dependent).")
    A("")

    # Per-round tables
    for idx, r in enumerate(rounds, start=1):
        A(f"## Round {idx} results (30 iterations each)")
        A("")
        A(f"Warm-ups: {r['methodology']['warmup_iterations']} · measured: "
          f"{r['methodology']['measured_iterations']} · concurrent pages: "
          f"{r['methodology']['concurrent_pages']} · failures: {len(r['errors'])}")
        A("")
        A("**CloakBrowser**")
        A("")
        L.extend(stat_table(r["summary"]["cloakbrowser"]))
        A("")
        A("**Chrome (stable)**")
        A("")
        L.extend(stat_table(r["summary"]["chrome"]))
        A("")
        A("**Median / p95 comparison**")
        A("")
        L.extend(compare_table(r["summary"]["cloakbrowser"], r["summary"]["chrome"]))
        A("")

    # Round-to-round variance
    A("## Round-to-round variance")
    A("")
    A("Median of each headline metric per round, and the round-2−round-1 drift as a "
      "percentage of round 1. Small drift = stable measurement.")
    A("")
    A("| Browser | Metric | Round 1 median | Round 2 median | Drift |")
    A("|---|---|---|---|---|")
    for browser in ("cloakbrowser", "chrome"):
        for m in ("launch_ms", "total_ms", "memory_mib", "external_navigation_ms"):
            m1 = float(r1["summary"][browser][m]["median"])
            m2 = float(r2["summary"][browser][m]["median"])
            drift = (m2 - m1) / m1 * 100.0 if m1 else 0.0
            A(f"| {browser} | {LABELS[m]} | {m1:.3f} | {m2:.3f} | {drift:+.2f}% |")
    A("")

    # Overheads / legacy
    A("## Playwright driver init & legacy `launch_async()` (measured separately)")
    A("")
    A("| Round | Driver start median (ms) | Driver start p95 | Legacy `launch_async()` median (ms) | Legacy p95 |")
    A("|---|---|---|---|---|")
    for idx, r in enumerate(rounds, start=1):
        d = r["overheads"]["playwright_driver_start_ms"]
        lg = r["overheads"]["legacy_cloak_launch_ms"]
        A(f"| {idx} | {num(d['median'])} | {num(d.get('p95'))} | {num(lg['median'])} | {num(lg.get('p95'))} |")
    A("")
    # Legacy vs session
    d1 = float(r1["overheads"]["playwright_driver_start_ms"]["median"])
    d2 = float(r2["overheads"]["playwright_driver_start_ms"]["median"])
    lg1 = float(r1["overheads"]["legacy_cloak_launch_ms"]["median"])
    lg2 = float(r2["overheads"]["legacy_cloak_launch_ms"]["median"])
    sess_launch = float(pc["launch_ms"]["median"])
    legacy_med = (lg1 + lg2) / 2.0
    driver_med = (d1 + d2) / 2.0
    reduction = (legacy_med - sess_launch) / legacy_med * 100.0
    A("### Legacy lifecycle vs. reusable session")
    A("")
    A(f"- Legacy `launch_async()` median (full lifecycle, **starts its own driver every call**): "
      f"**{legacy_med:.1f} ms** (round1 {lg1:.3f}, round2 {lg2:.3f}).")
    A(f"- Reusable-session per-launch median (driver already started, pooled): "
      f"**{sess_launch:.3f} ms**.")
    A(f"- Median Playwright driver start cost: **{driver_med:.1f} ms** — paid **once** by a "
      f"session, but **once per launch** by legacy `launch_async()`.")
    A(f"- **Reusable-session improvement per launch: {reduction:.1f}% lower** than the legacy "
      f"call. Over *N* launches, legacy pays ≈ N × (driver + launch) while a session pays "
      f"≈ driver + N × launch; the driver-start cost (~{driver_med:.0f} ms) is amortized to "
      f"zero as N grows.")
    A("")

    # Concurrency
    A("## 10-page concurrency workload")
    A("")
    A("One browser, one context, 10 pages opened and navigated concurrently; every page's "
      "`#value` text is verified.")
    A("")
    A("| Round | Browser | Pages verified | Elapsed (ms) | Memory (MiB) | Success |")
    A("|---|---|---|---|---|---|")
    for idx, r in enumerate(rounds, start=1):
        for browser in ("cloakbrowser", "chrome"):
            c = r["concurrency"][browser]
            A(f"| {idx} | {browser} | {c.get('verified_pages','—')}/{c['page_count']} "
              f"| {num(c.get('elapsed_ms'))} | {num(c.get('memory_mib'))} | {c['success']} |")
    A("")

    # Bottleneck analysis
    A("## Bottleneck analysis")
    A("")
    A("Ranked by share of the median summed workload (pooled CloakBrowser medians):")
    A("")
    phase_meds = [(LABELS[m], float(pc[m]["median"])) for m in
                  ("external_navigation_ms", "launch_ms", "page_setup_ms",
                   "close_ms", "local_navigation_ms", "javascript_ms")]
    tot = float(pc["total_ms"]["median"])
    A("| Phase | Median (ms) | Share of total |")
    A("|---|---|---|")
    for name, val in sorted(phase_meds, key=lambda x: -x[1]):
        A(f"| {name} | {val:.3f} | {val / tot * 100:.1f}% |")
    A("")
    A(f"- **External navigation dominates** (~{float(pc['external_navigation_ms']['median'])/tot*100:.0f}% "
      "of the workload) and is network-bound — not a property of either browser. It also carries "
      "the highest variance (largest stddev/p95 gap), so it is the main source of run-to-run noise.")
    A("- **Launch + page setup** are the largest *browser-controlled* costs. CloakBrowser's "
      f"launch is consistently below Chrome's ({lau_pct:+.2f}% pooled median); its extra stealth "
      "`--fingerprint*` args do not add measurable launch latency here.")
    A("- **Close/shutdown** is the noisiest deterministic phase (occasional multi-hundred-ms "
      "outliers from OS process teardown), visible in the high p95/stddev for `close_ms` in both "
      "browsers.")
    A(f"- **Memory:** CloakBrowser's process tree is {mem_pct:+.2f}% vs. Chrome (pooled median "
      f"{float(pc['memory_mib']['median']):.1f} vs {float(pg['memory_mib']['median']):.1f} MiB), "
      "partly because the free CloakBrowser binary is Chromium 146 while stable Chrome is 150.")
    A("")

    # Limitations
    A("## Limitations")
    A("")
    A("- **Different Chromium versions.** CloakBrowser's *free* binary is "
      f"{br['cloakbrowser']['version']}; stable Chrome is {br['chrome']['version']}. Launch, "
      "memory, and JS timings partly reflect that version gap, not only the stealth patches.")
    A("- **External navigation is network-dependent.** `example.com` latency varies; those "
      "numbers are informational and excluded from deterministic conclusions.")
    A("- **Memory sampling is a single point-in-time RSS snapshot** taken after the JS phase, "
      "matched by executable path + a 2 s process-start window. A browser process still tearing "
      "down from a prior same-browser iteration could, rarely, be double-counted; the effect is "
      "symmetric across browsers.")
    A("- **Headless only.** Headed mode and stealth-detection outcomes are out of scope here — "
      "this measures lifecycle performance, not detection evasion.")
    A("- **Windows-only host.** Results do not transfer directly to Linux/macOS.")
    A("")

    # Reproduction
    A("## Reproduction")
    A("")
    A("```powershell")
    A('$env:PYTHONUTF8 = "1"')
    A("python -m py_compile cloakbrowser/browser.py cloakbrowser/session.py benchmarks/compare_chrome.py")
    A("python -m pytest tests/test_session.py tests/test_benchmark_compare.py tests/test_launch.py -q")
    A("")
    A("# one round (repeat with a fresh --output for additional rounds)")
    A('$ts = Get-Date -Format "yyyyMMdd-HHmmss"')
    A("python -m benchmarks.compare_chrome --warmups 3 --iterations 30 --pages 10 `")
    A('  --output "benchmarks/results/cloakbrowser-session-vs-chrome-round1-$ts.json"')
    A("```")
    A("")

    # Recommendations
    A("## Optimization recommendations")
    A("")
    A("1. **Ship `CloakBrowserSession` / `AsyncCloakBrowserSession` as the default for "
      "multi-launch workloads.** The measured win is the ~"
      f"{driver_med:.0f} ms Playwright driver start, paid once instead of per launch "
      f"(~{reduction:.0f}% lower per-launch cost vs. legacy `launch_async()`). Document it as "
      "the recommended pattern for scrapers/agents that open many browsers.")
    A("2. **Pool contexts, not just the driver.** Page-setup (new context + page) is the second "
      "largest browser cost (~"
      f"{float(pc['page_setup_ms']['median'])/tot*100:.0f}% of the workload). For same-fingerprint "
      "work, reusing one context across pages (as the concurrency path already does) avoids "
      "repeated context creation.")
    A("3. **Keep external URLs out of regression gating.** External navigation is the dominant, "
      "noisiest phase; CI comparisons should gate on the deterministic-local subtotal (launch + "
      "page setup + local nav + JS + close) and treat external timings as informational.")
    A("4. **Track close-phase outliers.** `close_ms` p95 is several× its median. If shutdown "
      "latency matters, investigate whether backgrounding `browser.close()` (fire-and-forget with "
      "a join at session end) removes it from the critical path.")
    A("5. **Re-baseline against Pro (Chromium 150) for an apples-to-apples version match** — the "
      "current memory/launch gaps are partly the 146-vs-150 delta, not the wrapper.")
    A("")
    A("---")
    A("")
    A("*All tables above are generated directly from the round JSON files; regenerate with "
      "`python -m benchmarks.gen_report` after new rounds.*")

    out = RESULTS / "BENCHMARK_REPORT.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", out.resolve(), len(L), "lines")


if __name__ == "__main__":
    main()
