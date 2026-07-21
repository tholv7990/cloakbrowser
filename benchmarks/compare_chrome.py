"""Compare CloakBrowser and installed Google Chrome under equal Playwright workloads."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Awaitable, Callable

import psutil
from playwright.async_api import Browser, async_playwright

import cloakbrowser
from cloakbrowser import ensure_binary, launch_async
from cloakbrowser.browser import _launch_with_playwright_async


METRICS = (
    "launch_ms",
    "page_setup_ms",
    "local_navigation_ms",
    "external_navigation_ms",
    "javascript_ms",
    "memory_mib",
    "close_ms",
    "total_ms",
)
TIMED_PHASES = (
    "launch_ms",
    "page_setup_ms",
    "local_navigation_ms",
    "external_navigation_ms",
    "javascript_ms",
    "close_ms",
)
LOCAL_URL = (
    "data:text/html,<title>Benchmark Local</title>"
    "<main id='result'>cloakbrowser-benchmark</main>"
)
EXTERNAL_URL = "https://example.com"


def _round(value: float) -> float:
    return round(value, 3)


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (numpy 'linear' method)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median": _round(statistics.median(values)),
        "mean": _round(statistics.mean(values)),
        "min": _round(min(values)),
        "max": _round(max(values)),
        "p90": _round(_percentile(values, 90)),
        "p95": _round(_percentile(values, 95)),
        "stddev": _round(statistics.stdev(values)) if len(values) > 1 else 0.0,
    }


def relative_percent(cloak: float, chrome: float) -> float | None:
    if chrome == 0:
        return None
    return _round((cloak - chrome) / chrome * 100.0)


def measured_total(metrics: dict[str, float | None]) -> float:
    """Sum timed workload phases, excluding memory-sampling instrumentation."""
    return _round(sum(float(metrics[name]) for name in TIMED_PHASES if metrics.get(name) is not None))


def build_summary(iterations: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for browser_name, records in iterations.items():
        successful = [record for record in records if record.get("success")]
        browser_summary: dict[str, Any] = {
            "successful_iterations": len(successful),
            "failed_iterations": len(records) - len(successful),
        }
        for metric in METRICS:
            values = [
                float(record["metrics"][metric])
                for record in successful
                if record.get("metrics", {}).get(metric) is not None
            ]
            browser_summary[metric] = summarize(values)
        result[browser_name] = browser_summary
    return result


def build_relative(summary: dict[str, Any]) -> dict[str, float | None]:
    relative: dict[str, float | None] = {}
    for metric in METRICS:
        cloak_metric = summary["cloakbrowser"][metric]
        chrome_metric = summary["chrome"][metric]
        if not cloak_metric.get("count") or not chrome_metric.get("count"):
            relative[metric] = None
        else:
            relative[metric] = relative_percent(
                float(cloak_metric["median"]), float(chrome_metric["median"])
            )
    return relative


def build_overhead_summary(
    driver_start_ms: list[float], legacy_launch_ms: list[float]
) -> dict[str, dict[str, float | int]]:
    return {
        "playwright_driver_start_ms": summarize(driver_start_ms),
        "legacy_cloak_launch_ms": summarize(legacy_launch_ms),
    }


def find_google_chrome() -> Path:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Stable Google Chrome was not found in standard Windows paths")


def file_version(path: Path) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buffer)
        value = ctypes.c_void_p()
        length = wintypes.UINT()
        ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(length))
        words = ctypes.cast(value, ctypes.POINTER(wintypes.DWORD * 13)).contents
        ms, ls = words[2], words[3]
        return f"{ms >> 16}.{ms & 0xffff}.{ls >> 16}.{ls & 0xffff}"
    except Exception:
        return None


def executable_memory_mib(executable: Path, started_at: float) -> float | None:
    expected = os.path.normcase(str(executable.resolve()))
    rss = 0
    matched = 0
    for process in psutil.process_iter(["exe", "create_time", "memory_info"]):
        try:
            exe = process.info["exe"]
            created = process.info["create_time"]
            if exe and os.path.normcase(str(Path(exe).resolve())) == expected and created >= started_at - 2:
                rss += process.info["memory_info"].rss
                matched += 1
        except (psutil.Error, OSError):
            continue
    return _round(rss / (1024 * 1024)) if matched else None


async def _close_timed(browser: Browser) -> float:
    started = time.perf_counter_ns()
    await browser.close()
    return _round((time.perf_counter_ns() - started) / 1_000_000)


async def run_iteration(
    browser_name: str,
    launch: Callable[[], Awaitable[Browser]],
    executable: Path,
    iteration: int,
) -> dict[str, Any]:
    phase = "launch"
    browser: Browser | None = None
    started_wall = time.time()
    metrics: dict[str, float | None] = {}
    try:
        started = time.perf_counter_ns()
        browser = await launch()
        metrics["launch_ms"] = _round((time.perf_counter_ns() - started) / 1_000_000)

        phase = "page_setup"
        started = time.perf_counter_ns()
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        page.set_default_navigation_timeout(20_000)
        metrics["page_setup_ms"] = _round((time.perf_counter_ns() - started) / 1_000_000)

        phase = "local_navigation"
        started = time.perf_counter_ns()
        await page.goto(LOCAL_URL, wait_until="domcontentloaded")
        assert await page.title() == "Benchmark Local"
        assert await page.locator("#result").inner_text() == "cloakbrowser-benchmark"
        metrics["local_navigation_ms"] = _round((time.perf_counter_ns() - started) / 1_000_000)

        phase = "external_navigation"
        started = time.perf_counter_ns()
        await page.goto(EXTERNAL_URL, wait_until="domcontentloaded")
        assert await page.title() == "Example Domain"
        metrics["external_navigation_ms"] = _round((time.perf_counter_ns() - started) / 1_000_000)

        phase = "javascript"
        started = time.perf_counter_ns()
        js_result = await page.evaluate("""() => { let x = 0; for (let i=0; i<1000000; i++) x = (x + i) % 1000003; return x; }""")
        assert isinstance(js_result, int)
        metrics["javascript_ms"] = _round((time.perf_counter_ns() - started) / 1_000_000)
        metrics["memory_mib"] = executable_memory_mib(executable, started_wall)

        phase = "close"
        metrics["close_ms"] = await _close_timed(browser)
        browser = None
        metrics["total_ms"] = measured_total(metrics)
        return {"iteration": iteration, "browser": browser_name, "success": True, "metrics": metrics}
    except Exception as exc:
        return {
            "iteration": iteration,
            "browser": browser_name,
            "success": False,
            "metrics": metrics,
            "error": {"phase": phase, "type": type(exc).__name__, "message": str(exc)},
        }
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


async def run_concurrency(
    browser_name: str,
    launch: Callable[[], Awaitable[Browser]],
    executable: Path,
    page_count: int,
) -> dict[str, Any]:
    browser: Browser | None = None
    started_wall = time.time()
    started = time.perf_counter_ns()
    try:
        browser = await launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        pages = await asyncio.gather(*(context.new_page() for _ in range(page_count)))
        urls = [f"data:text/html,<title>Page {i}</title><p id='value'>{i}</p>" for i in range(page_count)]
        await asyncio.gather(*(page.goto(url, wait_until="domcontentloaded") for page, url in zip(pages, urls)))
        values = await asyncio.gather(*(page.locator("#value").inner_text() for page in pages))
        assert values == [str(i) for i in range(page_count)]
        elapsed = _round((time.perf_counter_ns() - started) / 1_000_000)
        return {
            "browser": browser_name,
            "success": True,
            "page_count": page_count,
            "elapsed_ms": elapsed,
            "memory_mib": executable_memory_mib(executable, started_wall),
            "verified_pages": len(values),
        }
    except Exception as exc:
        return {
            "browser": browser_name,
            "success": False,
            "page_count": page_count,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


def environment_info() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    cpu_name = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER") or "unknown"
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": cpu_name,
        "logical_cpus": psutil.cpu_count(logical=True),
        "physical_memory_gib": _round(memory.total / (1024**3)),
        "python": platform.python_version(),
        "playwright": package_version("playwright"),
        "cloakbrowser_wrapper": cloakbrowser.__version__,
    }


async def benchmark(iteration_count: int, page_count: int, warmup_count: int = 3) -> dict[str, Any]:
    cloak_exe = Path(ensure_binary()).resolve()
    chrome_exe = find_google_chrome()
    driver_start_ms: list[float] = []
    for sample in range(iteration_count):
        started = time.perf_counter_ns()
        sample_pw = await async_playwright().start()
        driver_start_ms.append(_round((time.perf_counter_ns() - started) / 1_000_000))
        await sample_pw.stop()

    legacy_launch_ms: list[float] = []
    for sample in range(iteration_count):
        started = time.perf_counter_ns()
        legacy_browser = await launch_async(headless=True)
        legacy_launch_ms.append(_round((time.perf_counter_ns() - started) / 1_000_000))
        await legacy_browser.close()

    playwright = await async_playwright().start()

    async def launch_cloak() -> Browser:
        return await _launch_with_playwright_async(playwright, headless=True)

    async def launch_chrome() -> Browser:
        return await playwright.chromium.launch(executable_path=str(chrome_exe), headless=True)

    launchers = {"cloakbrowser": launch_cloak, "chrome": launch_chrome}
    executables = {"cloakbrowser": cloak_exe, "chrome": chrome_exe}
    iterations: dict[str, list[dict[str, Any]]] = {"cloakbrowser": [], "chrome": []}
    try:
        for browser_name in ("cloakbrowser", "chrome"):
            for warm in range(warmup_count):
                print(f"Warming {browser_name} ({warm + 1}/{warmup_count})...", flush=True)
                await run_iteration(browser_name, launchers[browser_name], executables[browser_name], 0)

        for iteration in range(1, iteration_count + 1):
            order = ("cloakbrowser", "chrome") if iteration % 2 else ("chrome", "cloakbrowser")
            for browser_name in order:
                print(f"Iteration {iteration}/{iteration_count}: {browser_name}", flush=True)
                record = await run_iteration(
                    browser_name, launchers[browser_name], executables[browser_name], iteration
                )
                iterations[browser_name].append(record)

        concurrency = {}
        for browser_name in ("cloakbrowser", "chrome"):
            print(f"Concurrency ({page_count} pages): {browser_name}", flush=True)
            concurrency[browser_name] = await run_concurrency(
                browser_name, launchers[browser_name], executables[browser_name], page_count
            )
    finally:
        await playwright.stop()

    summary = build_summary(iterations)
    errors = [
        record
        for records in iterations.values()
        for record in records
        if not record.get("success")
    ]
    errors.extend(record for record in concurrency.values() if not record.get("success"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "warmup_iterations": warmup_count,
            "measured_iterations": iteration_count,
            "headless": True,
            "viewport": {"width": 1280, "height": 720},
            "concurrent_pages": page_count,
            "external_url": EXTERNAL_URL,
            "shared_playwright_driver": True,
        },
        "environment": environment_info(),
        "browsers": {
            "cloakbrowser": {"path": str(cloak_exe), "version": file_version(cloak_exe)},
            "chrome": {"path": str(chrome_exe), "version": file_version(chrome_exe)},
        },
        "iterations": iterations,
        "summary": summary,
        "relative_percent": build_relative(summary),
        "overheads": build_overhead_summary(driver_start_ms, legacy_launch_ms),
        "concurrency": concurrency,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/cloakbrowser-vs-chrome-2026-07-21.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.iterations < 1 or args.pages < 1:
        raise SystemExit("--iterations and --pages must both be positive")
    if args.warmups < 0:
        raise SystemExit("--warmups must not be negative")
    report = asyncio.run(benchmark(args.iterations, args.pages, args.warmups))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Results: {args.output.resolve()}")
    print(json.dumps(report["summary"], indent=2))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
