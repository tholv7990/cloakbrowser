# CloakBrowser vs Google Chrome Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible Playwright benchmark comparing CloakBrowser with locally installed stable Google Chrome, retain raw JSON, and document measured results.

**Architecture:** A standalone Python runner resolves both executables and executes identical alternating workloads through Playwright. Pure summary helpers are unit-tested separately; runtime measurements and metadata serialize to JSON, which becomes the sole numerical source for the Markdown report.

**Tech Stack:** Python 3.13, Playwright 1.61, CloakBrowser 0.4.12, psutil, pytest, PowerShell, JSON, Markdown.

## Global Constraints

- Run both browsers on the same Windows host using Python Playwright, headless mode, and the same viewport.
- Perform one unreported warm-up and five measured iterations per browser.
- Alternate browser order to reduce ordering bias.
- Primary comparison uses deterministic data URLs; external navigation is reported separately.
- Record failures rather than dropping them.
- Produce raw JSON and make all Markdown numbers traceable to it.
- Do not alter CloakBrowser production code.

---

### Task 1: Benchmark summary primitives

**Files:**
- Create: `benchmarks/__init__.py`
- Create: `benchmarks/compare_chrome.py`
- Create: `tests/test_benchmark_compare.py`

**Interfaces:**
- Produces: `summarize(values: list[float]) -> dict[str, float | int]`
- Produces: `relative_percent(cloak: float, chrome: float) -> float | None`
- Produces: `find_google_chrome() -> Path`

- [ ] **Step 1: Write failing unit tests**

```python
from benchmarks.compare_chrome import relative_percent, summarize

def test_summarize():
    assert summarize([10.0, 20.0, 30.0]) == {
        "count": 3, "median": 20.0, "mean": 20.0, "min": 10.0, "max": 30.0,
    }

def test_relative_percent():
    assert relative_percent(120.0, 100.0) == 20.0
    assert relative_percent(1.0, 0.0) is None
```

- [ ] **Step 2: Verify the test fails before implementation**

Run: `python -m pytest tests/test_benchmark_compare.py -q`

Expected: import failure because `benchmarks.compare_chrome` does not exist.

- [ ] **Step 3: Implement the pure helpers and Chrome resolver**

Implement `summarize` with `statistics.mean` and `statistics.median`, returning rounded millisecond values. Implement `relative_percent` as `(cloak - chrome) / chrome * 100`, returning `None` for a zero baseline. Search standard system, x86, and per-user Chrome paths and raise `FileNotFoundError` if none exists.

- [ ] **Step 4: Run helper tests**

Run: `python -m pytest tests/test_benchmark_compare.py -q`

Expected: all tests pass.

### Task 2: Runtime workload and JSON report

**Files:**
- Modify: `benchmarks/compare_chrome.py`
- Modify: `tests/test_benchmark_compare.py`
- Create at runtime: `benchmarks/results/cloakbrowser-vs-chrome-2026-07-21.json`

**Interfaces:**
- Produces: `run_iteration(browser_name: str, launch: Callable[[], Browser]) -> dict[str, object]`
- Produces: `run_concurrency(browser_name: str, launch: Callable[[], Browser], page_count: int = 5) -> dict[str, object]`
- Produces: `build_report(iterations: dict[str, list[dict]], concurrency: dict[str, dict]) -> dict[str, object]`
- CLI: `python benchmarks/compare_chrome.py --iterations 5 --output <path>`

- [ ] **Step 1: Add failing tests for report schema and failure retention**

Use fake iteration dictionaries to assert summaries contain `launch_ms`, `page_setup_ms`, `local_navigation_ms`, `external_navigation_ms`, `javascript_ms`, `close_ms`, and `memory_mib`, and that error records remain in `iterations`.

- [ ] **Step 2: Run tests and observe the missing runtime/report functions**

Run: `python -m pytest tests/test_benchmark_compare.py -q`

Expected: failure for missing functions.

- [ ] **Step 3: Implement measured workloads**

Use `time.perf_counter_ns()` for timing, Playwright navigation timeouts of 20 seconds, `psutil.Process(pid).children(recursive=True)` for process-tree RSS, `finally` cleanup, local content assertions, a deterministic JavaScript loop, and five-page `asyncio.gather` concurrency. Resolve versions from executable metadata and browser APIs. Warm each browser once and alternate measured order.

- [ ] **Step 4: Add JSON serialization and CLI arguments**

Add `--iterations`, `--pages`, and `--output`. Store environment, browser metadata, raw iterations, summaries, relative percentages, concurrency, and errors. Create the output directory when absent.

- [ ] **Step 5: Run unit tests**

Run: `python -m pytest tests/test_benchmark_compare.py -q`

Expected: all tests pass.

- [ ] **Step 6: Install benchmark-only dependency and run benchmark**

Run:

```powershell
python -m pip install psutil
$env:PYTHONUTF8 = "1"
python benchmarks/compare_chrome.py --iterations 5 --pages 5 --output benchmarks/results/cloakbrowser-vs-chrome-2026-07-21.json
```

Expected: exit code 0, five successful local iterations per browser, concurrency verification for five pages, and parseable JSON.

### Task 3: Results validation and documentation

**Files:**
- Modify: `docs/CODEBASE_FUNCTIONALITY.md`
- Read: `benchmarks/results/cloakbrowser-vs-chrome-2026-07-21.json`

**Interfaces:**
- Consumes: JSON keys `environment`, `browsers`, `summary`, `relative_percent`, `concurrency`, and `errors`.
- Produces: a benchmark section whose numeric values match JSON.

- [ ] **Step 1: Validate result completeness**

Run a Python assertion that parses the JSON, checks both browser keys, verifies five measured iterations per browser, confirms local assertions and five-page concurrency, and verifies required summary metrics.

- [ ] **Step 2: Add methodology and results tables to the guide**

Document host/browser versions, median values, relative differences, concurrency results, errors, interpretation, limitations, and the exact reproduction command. Keep network numbers separate from local measurements.

- [ ] **Step 3: Verify documentation values against JSON**

Run a script that checks each documented median and relative value appears exactly as serialized in JSON.

- [ ] **Step 4: Run final verification**

Run:

```powershell
python -m pytest tests/test_benchmark_compare.py -q
python benchmarks/compare_chrome.py --help
python -m json.tool benchmarks/results/cloakbrowser-vs-chrome-2026-07-21.json > $null
```

Expected: tests pass, CLI help exits 0, and JSON validation exits 0.

## Commit note

The workspace is not a Git repository, so commit steps are intentionally omitted. All created files remain directly visible in the shared workspace.

