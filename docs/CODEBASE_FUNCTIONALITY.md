# CloakBrowser Codebase and Functionality Guide

Validated against the source checkout on 2026-07-21. This document distinguishes source-implemented behavior from functionality that was actually exercised on the current Windows machine.

## 1. What CloakBrowser is

CloakBrowser is a thin, open-source SDK around a separately distributed, patched Chromium binary. The SDK does not implement browser fingerprint spoofing in JavaScript; it downloads and verifies the appropriate binary, builds its command-line fingerprint flags, launches it through an automation framework, and optionally humanizes input behavior.

The repository contains three clients intended to remain behaviorally equivalent:

| Client | Source | Automation API | Status on this machine |
|---|---|---|---|
| Python | `cloakbrowser/` | Playwright sync and async APIs | Built, tested, and browser-launched |
| Node.js/TypeScript | `js/src/` | Playwright and Puppeteer | Type-checked and unit-tested; no separate browser launch performed |
| .NET | `dotnet/src/` | Microsoft.Playwright | Source-reviewed only; .NET SDK is not installed |

Python is identified in `CLAUDE.md` as the reference implementation. The TypeScript and .NET clients mirror its configuration, launch, proxy, GeoIP, licensing, download, Widevine, and human-input behavior.

## 2. High-level architecture

```text
Application code
    |
    | launch options: proxy, locale, timezone, humanize, profile, extensions
    v
Python / TypeScript / .NET wrapper
    |-- resolve free, Pro, pinned, or overridden binary
    |-- download and cryptographically verify binary when absent
    |-- resolve proxy authentication and optional GeoIP/WebRTC identity
    |-- merge default and caller-provided fingerprint flags
    |-- start patched Chromium through Playwright or Puppeteer
    `-- optionally decorate interaction methods with human-like behavior
    v
Patched Chromium binary
    v
Normal Playwright or Puppeteer Browser / BrowserContext / Page API
```

The binary is cached outside the repository, by default under `~/.cloakbrowser/`. On the validated machine the free build resolved to:

```text
C:\Users\Admin\.cloakbrowser\chromium-146.0.7680.177.5\chrome.exe
```

## 3. Implemented functionality

### Browser launch modes

The Python public API is exported from `cloakbrowser/__init__.py` and implemented in `cloakbrowser/browser.py`.

- `launch()` and `launch_async()` start Chromium and return a standard Playwright `Browser`.
- `launch_context()` and `launch_context_async()` start a browser plus a configured context and return a managed context handle.
- `launch_persistent_context()` and its async equivalent use a user-data directory so cookies, local storage, cache, and other profile state survive restarts.
- `CloakBrowserSession` and `AsyncCloakBrowserSession` reuse one Playwright driver across repeated bare-browser launches, avoiding roughly 314 ms of repeated driver initialization on the measured Windows host.
- Headless and headed modes are supported.
- Context options include viewport/no-viewport behavior, user agent, color scheme, storage state, locale, and timezone.
- Chrome extensions can be loaded from one or more local paths.
- Additional Chromium arguments can be supplied; dedicated locale/timezone parameters take precedence when arguments are merged.

The Node client exposes equivalent Playwright functions from `js/src/playwright.ts` and a Puppeteer launch implementation from `js/src/puppeteer.ts`. The .NET client exposes `LaunchAsync`, `LaunchContextAsync`, and `LaunchPersistentContextAsync` from `CloakLauncher`.

### Fingerprint configuration and stealth flags

`cloakbrowser/config.py` selects platform-specific defaults and binary versions. The wrapper assembles `--fingerprint-*` command-line switches rather than injecting page scripts. Supported controls documented and implemented in the source include:

- Stable fingerprint seed and platform persona.
- Timezone and locale.
- WebRTC public-IP spoofing.
- Canvas, client-rectangle, audio, WebGL, GPU, screen, hardware-concurrency, memory, font, and related identity flags accepted by the patched binary.
- Default stealth arguments can be disabled with `stealth_args=False` when callers want full control.
- Duplicate arguments are resolved by flag key, with caller arguments overriding defaults and dedicated parameters overriding both.
- The cross-language `consistent` preset disables per-render fingerprint noise. For persistent contexts it also sets a stock-like 10,240 MiB storage quota; the default preset preserves prior behavior.
- A stable returning identity still requires a dedicated profile directory and caller-supplied fixed `--fingerprint=<seed>`.

The actual fingerprint modifications live in the closed-source Chromium binary, not in this repository.

### Pixelscan regression result

The reusable scanner is `benchmarks/fingerprint_scanners.py`. It reads the proxy only from `CLOAK_TEST_PROXY`, redacts credentials in JSON/console output, starts the current Pixelscan flow, saves timestamped evidence, and exits nonzero if the consistent-profile gate fails.

On 2026-07-21, controlled tests isolated two causes in the prior configuration:

- Implicit rendering noise caused Pixelscan's masking warning; `--fingerprint-noise=false` removed it.
- A 5,000 MiB storage quota differed from installed Chrome's observed 10,240 MiB quota and caused the persistent profile to be classified as incognito. Using 10,240 MiB removed that classification.

Two consecutive scans of the same persistent profile with the `consistent` preset reported a clean fingerprint verdict, no masking, no automated behavior, and no incognito classification. These results are scanner-specific and may change when the site or browser binary changes.

### Proxy handling

Launch APIs accept proxy URLs or structured proxy settings.

- HTTP, HTTPS, SOCKS5, and SOCKS5H URLs are recognized.
- Inline credentials are parsed and special characters are normalized/encoded.
- Playwright-native proxy configuration is used where appropriate.
- SOCKS proxy arguments and authentication are handled with version-aware compatibility logic.
- Proxy bypass lists and explicit username/password fields are supported.
- Proxy resolution is kept aligned across Python, TypeScript, and .NET.

### GeoIP, locale, timezone, and WebRTC alignment

When `geoip=True`, `cloakbrowser/geoip.py` can:

- Determine the proxy exit IP, or the host public IP when no proxy is supplied.
- Download and cache a GeoLite2 City database on first use.
- Map the exit IP to an IANA timezone and a locale.
- Preserve explicitly supplied timezone or locale values.
- Feed the resolved exit IP into the WebRTC fingerprint flag to reduce proxy/WebRTC mismatches.
- Apply a configurable lookup timeout and update the local database in the background.

The Python extra is installed with `pip install -e ".[geoip]"`. GeoIP resolution makes network requests and the database was not downloaded during this review.

### Human-like interaction layer

With `humanize=True`, the wrapper alters high-level interaction behavior while preserving the normal automation API shape.

- Mouse movement follows randomized Bezier paths with wobble, burst timing, overshoot, and target-aware click positions.
- Typing uses per-key delays, key-hold timing, pauses, Shift handling, optional mistakes/corrections, and non-ASCII support.
- Scrolling uses acceleration/deceleration, variable wheel deltas, optional overshoot, and settling delays.
- Actions wait for attachment, visibility, stability, enabled/editable state, and pointer-event reachability.
- DOM checks use an isolated CDP world to avoid exposing helper JavaScript in the page's main world.
- `default` and `careful` presets are available, with granular configuration through `HumanConfig`.
- Sync and async Python implementations are provided; TypeScript and .NET ports implement the corresponding behavior.

### Binary lifecycle and security

`cloakbrowser/download.py` implements the binary lifecycle:

- Resolve a local override, explicitly pinned version, Pro version, or platform-specific free version.
- Download archives into the cache when needed.
- Verify an Ed25519 signature over `SHA256SUMS`, then verify each downloaded file with SHA-256.
- Reject unsafe archive paths and links during extraction.
- Report installed binary metadata, check for updates, and clear the cache.
- Support automatic wrapper update checks.

`CLOAKBROWSER_SKIP_CHECKSUM` bypasses verification only for custom/test download paths and should not be used for production downloads.

### Free/Pro licensing and version selection

`cloakbrowser/license.py` supports:

- Explicit license keys and `CLOAKBROWSER_LICENSE_KEY`.
- Remote license validation with cached responses.
- Pro latest-version resolution and active-session lookup.
- Mapping binary launch errors to `CloakBrowserLicenseError` with clearer messages.
- Explicit version pins for rollback/reproducibility.

Resolution priority is: local binary override, explicit version pin, entitled Pro binary, then the bundled platform-specific free version. A custom download URL disables Pro routing.

### Persistent profiles and Widevine

- Persistent contexts keep browser state in a caller-selected user-data directory.
- Widevine helpers locate a provisioned CDM and seed the persistent profile hint before launch.
- `bin/fetch-widevine.py` provisions Widevine separately.
- Widevine support is optional and platform-dependent.

### CLI and service mode

The Python CLI (`python -m cloakbrowser` or `cloakbrowser`) implements:

| Command | Purpose |
|---|---|
| `install` | Resolve, download, verify, and print the binary path |
| `info` / `doctor` | Report environment, tier, selected binary, launch probe, optional modules, and GeoIP state |
| `update` | Check for and download an updated binary |
| `clear-cache` | Remove cached browser binaries |

`bin/cloakserve` adds a standalone CDP multiplexer. It can expose browser WebSocket endpoints, create a distinct browser process per fingerprint seed, accept identity options through query parameters, and reap idle sessions. This mode requires the Python `serve` extra and is used by integrations that connect over CDP instead of importing the wrapper.

### Integrations and deployment

The `examples/` directory includes direct and integration examples for:

- Python Playwright sync use, persistent contexts, fingerprint checks, reCAPTCHA scoring, and stealth tests.
- Selenium, undetected-chromedriver, browser-use, Crawl4AI, Crawlee, Scrapling, LangChain, and agent-browser.
- AWS Lambda container deployment.
- Docker, Docker Compose, CDP server mode, and Nix development environments.

Humanization requires using the wrapper/decorator layer; a third-party framework that only connects to an already-running CDP endpoint gets the patched browser fingerprint but not automatically the wrapper's human-input methods.

## 4. Configuration surface

Important environment variables found in the source:

| Variable | Effect |
|---|---|
| `CLOAKBROWSER_LICENSE_KEY` | Pro entitlement key |
| `CLOAKBROWSER_VERSION` | Pin a binary version |
| `CLOAKBROWSER_BINARY_PATH` | Use a local Chromium binary directly |
| `CLOAKBROWSER_DOWNLOAD_URL` | Override binary download location |
| `CLOAKBROWSER_CACHE_DIR` | Override cache directory |
| `CLOAKBROWSER_AUTO_UPDATE` | Enable/disable automatic update checks |
| `CLOAKBROWSER_SKIP_CHECKSUM` | Test/custom-download verification bypass |
| `CLOAKBROWSER_SUPPRESS_FONT_WARNING` | Suppress Linux Windows-font warning |
| `CLOAKBROWSER_WIDEVINE` / `CLOAKBROWSER_WIDEVINE_CDM` | Control Widevine discovery/seeding |
| `CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS` | Bound GeoIP lookup time |

## 5. Running the Python client

From the repository root:

```powershell
python -m pip install -e ".[dev,geoip,serve]"
$env:PYTHONUTF8 = "1"
python -m cloakbrowser install
python -m cloakbrowser info
```

Minimal headless launch:

```python
from cloakbrowser import launch

browser = launch(headless=True)
page = browser.new_page()
page.goto("https://example.com")
print(page.title())
browser.close()
```

Persistent humanized context:

```python
from cloakbrowser import launch_persistent_context

context = launch_persistent_context(
    "./profile",
    headless=False,
    humanize=True,
    human_preset="careful",
    geoip=True,
    proxy="http://user:password@proxy.example:8080",
)
page = context.pages[0] if context.pages else context.new_page()
page.goto("https://example.com")
context.close()
```

## 6. Validation performed on 2026-07-21

### Runtime browser check: passed

The signed free binary was resolved at version `146.0.7680.177.5`. A Python Playwright launch loaded a data URL and produced:

```text
TITLE=CloakBrowser Runtime OK
STATUS=running
UA=Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/146.0.0.0 ...
WEBDRIVER=False
```

This confirms binary launch, page creation, navigation, DOM access, user-agent spoofing, and the `navigator.webdriver` stealth signal on the current host.

### Python tests: mostly passed, with Windows-specific failures

Command:

```powershell
python -m pytest -m "not slow" -q
```

Result: **702 passed, 14 failed, 4 skipped, 40 deselected**.

Observed failure groups:

- Tests compare POSIX `/` path suffixes against Windows `\` paths.
- Executable permission semantics differ on Windows.
- Update/download fixtures expect `.tar.gz`, while Windows correctly selects `.zip` in current source.
- Platform-aware mocked release assets do not match the current Windows archive naming.
- License tests are affected by local/external license state.
- One GeoIP timeout test failed on timing behavior.

No source changes were made to hide these failures.

### Node.js/TypeScript validation

Commands:

```powershell
cd js
npm ci
npm run typecheck
npm test -- --run
```

TypeScript type-checking passed. Vitest reported five failures, dominated by the same Windows `.zip` versus `.tar.gz` and platform-aware update-fixture assumptions. The dependency audit reported zero vulnerabilities.

### .NET validation limitation

The repository contains a solution, CLI, library, source generator, examples, and tests, but the current machine has no .NET SDK. Consequently `dotnet build` and `dotnet test` could not run. Install the SDK version required by `dotnet/src/CloakBrowser/CloakBrowser.csproj`, then run:

```powershell
cd dotnet
dotnet restore CloakBrowser.sln
dotnet build CloakBrowser.sln
dotnet test CloakBrowser.sln
```

## 7. Performance benchmark against Google Chrome

The reusable benchmark runner is `benchmarks/compare_chrome.py`; corrected raw measurements are stored in `benchmarks/results/cloakbrowser-session-vs-chrome-2026-07-21.json`.

### Methodology

- Host: Windows 10 build 19045, 12 logical CPUs, 31.745 GiB physical memory.
- Runtime: Python 3.13.12 and Playwright 1.61.0.
- Browsers: CloakBrowser wrapper 0.4.12 with Chromium `146.0.7680.177`; installed Google Chrome `150.0.7871.125`.
- Both browsers used the same already-started Playwright driver, headless mode, and a 1280 × 720 viewport.
- One warm-up was discarded, followed by five alternating measured iterations per browser.
- Each iteration measured launch, context/page creation, deterministic data-URL navigation, `https://example.com` navigation, a deterministic JavaScript loop, process working set, and shutdown.
- The concurrency workload launched one browser, created five pages concurrently, navigated them to deterministic data URLs, and verified all five results.
- Total time is the sum of timed workload phases and excludes the cost of collecting process memory.
- Playwright driver initialization and the legacy module-level CloakBrowser launch are reported separately instead of charging driver initialization only to CloakBrowser.

### Median single-iteration results

| Metric | CloakBrowser | Google Chrome | CloakBrowser difference |
|---|---:|---:|---:|
| Launch | 155.873 ms | 177.511 ms | -12.190% |
| Context and page creation | 115.615 ms | 108.523 ms | +6.535% |
| Local navigation and DOM verification | 43.913 ms | 41.494 ms | +5.830% |
| External navigation | 201.101 ms | 187.999 ms | +6.969% |
| JavaScript loop | 8.646 ms | 8.114 ms | +6.557% |
| Process working set | 315.715 MiB | 348.539 MiB | -9.418% |
| Shutdown | 96.697 ms | 108.295 ms | -10.710% |
| Sum of timed phases | 620.467 ms | 634.109 ms | -2.151% |

All five measured iterations succeeded for each browser; the JSON report contains mean, minimum, maximum, median, and raw values.

### Five-page concurrency result

| Metric | CloakBrowser | Google Chrome | CloakBrowser difference |
|---|---:|---:|---:|
| Launch + create/navigate/verify 5 pages | 363.974 ms | 478.908 ms | -24.000% |
| Process working set | 525.598 MiB | 580.082 MiB | -9.393% |
| Verified pages | 5/5 | 5/5 | — |

### Interpretation

- With equal driver lifecycle, CloakBrowser launched 12.190% faster and its total timed workload was 2.151% faster in this short run.
- Page setup, local navigation, external navigation, and the JavaScript loop were 5.8–7.0% slower, small enough to require a longer benchmark before treating the difference as stable.
- CloakBrowser completed the five-page workload 24.0% faster in this sample.
- CloakBrowser used roughly 9% less process working-set memory in both the single-page median and five-page sample.
- The Playwright driver itself took a median 314.461 ms to start. The backward-compatible module-level `launch_async()` path, which owns a fresh driver, took 456.212 ms; the reusable session removes that repeated driver cost.
- This comparison measures the total product configurations, not only the Chromium engines. CloakBrowser supplies fingerprint flags and patches that stock Chrome does not, and the browser major versions differ (146 versus 150).

### Reproduce

```powershell
python -m pip install psutil
$env:PYTHONUTF8 = "1"
python benchmarks/compare_chrome.py `
  --iterations 5 `
  --pages 5 `
  --output benchmarks/results/cloakbrowser-session-vs-chrome-2026-07-21.json
```

The benchmark is a short, single-host sample rather than a universal performance claim. Results can change with CPU power state, antivirus scanning, process caches, browser versions, background load, and internet conditions. Run 20–30 iterations on the intended deployment hardware for capacity decisions.

## 8. Known review findings

1. On the default Windows console encoding, `python -m cloakbrowser info --quick` can fail while printing the Unicode arrow in the Pro upgrade hint. Setting `PYTHONUTF8=1` avoids it.
2. `python -m cloakbrowser info` timed out while probing `chrome.exe --version`, although a normal Playwright browser launch succeeded immediately afterward. The diagnostic probe is therefore not a reliable launch verdict on this host.
3. Several Python and TypeScript tests contain archive/path assumptions that are not portable to Windows even though the implementation selects the expected Windows `.zip` archive.
4. The root `README.md` headline references a newer Pro Chromium build, while the free platform build resolved by this checkout is `146.0.7680.177.5`. This is consistent with separate free and Pro release tracks but can be confusing without reading the tier details.

## 9. Proxy quality scanner

The standalone proxy-quality CLI is a credential-safe, opt-in diagnostic. It reads `CLOAK_TEST_PROXY` from the environment, accepts only nonsecret `--output-dir PATH` and `--direct-control` options, and serializes only a reconstructed redacted endpoint. Credentialed browser scans use the scanner-private `AuthenticatedProxyRelay`: Chromium receives an ephemeral `http://127.0.0.1:<port>` endpoint while upstream HTTP/HTTPS/SOCKS5/SOCKS5H authentication remains in the parent process. The browser context closes before the relay and temporary profile. Network type remains independent from reputation:

- `type`: `mobile`, `residential_or_isp`, `datacenter_or_hosting`, or `unknown`.
- `type_confidence`: `high`, `medium`, or `low`; two agreeing independent structured sources are high, one nonconflicting structured source is medium, and heuristic-only or conflicting evidence is low.
- `reputation`: `clean_observed`, `questionable`, `blocked`, or `unknown`.
- `suitable_for_protected_sites`: `yes`, `no`, or `uncertain`.

The public `summary` contains `type`, `type_confidence`, `reputation`, and `suitable_for_protected_sites`. Sanitized `classification.evidence` retains source, ASN, organization, category, carrier/mobile/hosting/privacy flags, and conflict information. A residential/mobile classification does not prove an IP is clean, and a datacenter/hosting classification does not prove it is blocked. `clean_observed` is limited to the timestamped scan, the selected data sources, and the specific sites observed; it is never a universal or permanent status.

With browser checks enabled, the scanner records tri-state, field-attributed HTTP-exit, WebRTC, timezone, locale, and proxy-DNS alignment before making one initial navigation to a third-party Turnstile demo and one to Google. It observes page state only: it never clicks, retries, or solves a CAPTCHA. A missing identity dimension remains `unknown`; an observed mismatch is `questionable`; all dimensions must align for `clean_observed`. Set `PROXY_QUALITY_SKIP_BROWSER=1` to omit the browser stages. This still performs proxy connectivity requests and may refresh datasets, so it is not an offline mode.

Proxy artifacts are `report.json`, `sources.json`, and optional top-level `cloudflare.png` / `google.png`; report fields retain screenshot status/path, and PNG metadata is validated and stripped. The report labels the Turnstile endpoint as a third-party demo and links to Pixelscan as a separate check that is not run automatically. `--direct-control` performs one direct-network Google observation in a separate `direct-control/<timestamp>` artifact tree; it neither reads the proxy nor contributes to the proxy report.

Connectivity evidence records all three echo attempts, both endpoint identities, successful IPs/latencies, median latency, agreement, and explicit `country_consistency: unavailable` because the selected echo endpoints do not return geography. Reputation matches include source, list category, and `exact_ip`/`cidr` granularity. Intelligence adapters cache datasets with provenance and checksums. The required IPsum/FireHOL availability map is propagated into verdict aggregation: an unavailable selected source cannot masquerade as an empty negative result. `no_listed_abuse` means only that the exit was absent from the selected available lists. The adapters attribute [ipinfo/cli](https://github.com/ipinfo/cli) (Apache-2.0; optional API), [sapics/ip-location-db](https://github.com/sapics/ip-location-db) (per-dataset licensing), [stamparm/ipsum](https://github.com/stamparm/ipsum) (Unlicense), and [FireHOL blocklist-ipsets](https://github.com/firehol/blocklist-ipsets) (source-specific licenses).

The behavior and intended evidence model are specified in [Proxy Quality Scanner Design](superpowers/specs/2026-07-21-proxy-quality-scanner-design.md); the implementation is in [`benchmarks/proxy_quality.py`](../benchmarks/proxy_quality.py), [`benchmarks/proxy_quality_models.py`](../benchmarks/proxy_quality_models.py), [`benchmarks/proxy_intelligence.py`](../benchmarks/proxy_intelligence.py), and [`benchmarks/proxy_site_checks.py`](../benchmarks/proxy_site_checks.py).

## 10. Primary source map

| Concern | Python | TypeScript | .NET |
|---|---|---|---|
| Public API | `cloakbrowser/__init__.py` | `js/src/index.ts` | `dotnet/src/CloakBrowser/CloakLauncher.cs` |
| Launch and arguments | `cloakbrowser/browser.py`, `cloakbrowser/session.py` | `js/src/playwright.ts`, `js/src/puppeteer.ts`, `js/src/args.ts` | `CloakLauncher.cs`, `LaunchOptions.cs` |
| Version/platform config | `cloakbrowser/config.py` | `js/src/config.ts` | `Config.cs` |
| Binary download/security | `cloakbrowser/download.py` | `js/src/download.ts` | `Download.cs` |
| Proxy | `cloakbrowser/browser.py` | `js/src/proxy.ts` | `ProxyResolver.cs` |
| GeoIP | `cloakbrowser/geoip.py` | `js/src/geoip.ts` | `GeoIp.cs` |
| Licensing | `cloakbrowser/license.py` | `js/src/license.ts` | `License.cs` |
| Widevine | `cloakbrowser/widevine.py` | `js/src/widevine.ts` | `Widevine.cs` |
| Human behavior | `cloakbrowser/human/` | `js/src/human/`, `js/src/human-puppeteer/` | `Human/`, `Wrappers/` |
| CLI | `cloakbrowser/__main__.py` | `js/src/cli.ts` | `dotnet/src/CloakBrowser.Cli/Program.cs` |
| Proxy quality scanner | [`benchmarks/proxy_quality.py`](../benchmarks/proxy_quality.py), [`benchmarks/proxy_quality_models.py`](../benchmarks/proxy_quality_models.py), [`benchmarks/proxy_intelligence.py`](../benchmarks/proxy_intelligence.py), [`benchmarks/proxy_auth_relay.py`](../benchmarks/proxy_auth_relay.py), [`benchmarks/proxy_site_checks.py`](../benchmarks/proxy_site_checks.py) | N/A | N/A |
| Proxy scanner design | [specification](superpowers/specs/2026-07-21-proxy-quality-scanner-design.md), [implementation plan](superpowers/plans/2026-07-21-proxy-quality-scanner.md) | N/A | N/A |
