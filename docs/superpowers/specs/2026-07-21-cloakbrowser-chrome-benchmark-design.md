# CloakBrowser vs Google Chrome Benchmark Design

## Objective

Measure the runtime performance of CloakBrowser against the locally installed stable Google Chrome executable under equivalent Playwright workloads on the same Windows host.

## Comparison rules

- Use Python Playwright for both browsers.
- Use the same Playwright package, Python process, headless mode, viewport, pages, and operation ordering.
- Change only the executable and the launch arguments required by each product.
- Run five measured iterations per browser after one unreported warm-up.
- Alternate browser order between iterations to reduce time/order bias.
- Treat local data-URL navigation as the primary repeatable result.
- Report external navigation separately because DNS, TLS, server, and internet variation are not controlled.
- Record failures and timeouts rather than removing them from the data.

## Workloads

### Single-browser iteration

Measure these phases independently with a monotonic high-resolution timer:

1. Launch browser.
2. Create context and page.
3. Navigate to and query a deterministic local data URL.
4. Navigate to `https://example.com`, wait for DOM content loaded, and read the title.
5. Execute a deterministic JavaScript CPU loop.
6. Sample the browser process-tree working set.
7. Close the browser.

### Short concurrency workload

For each browser:

1. Launch once.
2. Create five pages.
3. Navigate all five pages concurrently to deterministic data URLs.
4. Query each page and verify the expected content.
5. Record elapsed time and process-tree working set.
6. Close the browser.

## Browser resolution

- CloakBrowser: resolve through `cloakbrowser.ensure_binary()` and launch through the public `cloakbrowser.launch()` API so production fingerprint arguments are included.
- Google Chrome: locate stable Chrome from standard Windows installation paths and launch it using Playwright's Chromium browser type with `executable_path`.
- Record the exact executable paths and browser versions.
- Stop with a clear error if stable Google Chrome is not installed.

## Metrics and reporting

For each timed metric report milliseconds as median, arithmetic mean, minimum, maximum, and sample count. Report process-tree working set in MiB. Calculate CloakBrowser relative difference from Chrome using `(cloak - chrome) / chrome * 100`.

The report must include:

- Host OS, architecture, CPU model, logical CPU count, and total physical memory.
- Python, Playwright, CloakBrowser wrapper, CloakBrowser Chromium, and Google Chrome versions.
- Raw measurements in a machine-readable JSON result file.
- A Markdown summary table and interpretation.
- Explicit limitations: one host, five iterations, headless mode, process-cache effects, network variance, and different default browser flags.

## Files

- Create `benchmarks/compare_chrome.py`: reusable benchmark runner and JSON emitter.
- Create `benchmarks/results/cloakbrowser-vs-chrome-2026-07-21.json`: raw result artifact.
- Update `docs/CODEBASE_FUNCTIONALITY.md`: methodology, summary tables, interpretation, and reproduction command.

## Error handling

- Each browser iteration has bounded navigation timeouts.
- An iteration failure is stored with browser name, phase, exception type, and message.
- The runner closes browsers in `finally` blocks.
- External-navigation failure does not invalidate local workload measurements; it is reported separately.
- Memory is reported as unavailable if the process tree cannot be resolved safely.

## Verification

- The runner must complete both browser warm-ups and five measured iterations.
- Local page title and DOM assertions must pass for every successful iteration.
- The concurrency workload must verify all five page results.
- JSON output must parse successfully and contain environment, browser metadata, raw iterations, summaries, concurrency results, and errors.
- The documentation numbers must match the generated JSON summaries.

