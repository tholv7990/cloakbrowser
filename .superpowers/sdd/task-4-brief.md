### Task 4: Browser site-state checks without challenge interaction

Create `benchmarks/proxy_site_checks.py`, `tests/test_proxy_site_checks.py`, and sanitized text fixtures under `tests/fixtures/proxy_quality/`.

Produce exact interfaces:

- `parse_google_state(url: str, body_text: str, *, search_container_visible: bool, recaptcha_visible: bool) -> str`.
- `parse_cloudflare_state(body_text: str, *, token_present: bool, challenge_visible: bool) -> str`.
- `run_browser_checks(proxy: str, profile_dir: Path, screenshot_dir: Path) -> dict[str, object]`.

Google priority: `/sorry/` or visible reCAPTCHA -> `captcha`; explicit access denial -> `blocked`; visible `#search` -> `results`; consent form -> `consent`; otherwise `unknown`. Arbitrary result text mentioning reCAPTCHA must not cause a challenge verdict.

Cloudflare priority: nonempty token plus no visible challenge -> `passed`; visible challenge -> `interactive`; explicit error -> `error`; widget without verdict -> `pending`; otherwise `unknown`.

Required representative tests:

```python
def test_google_results_text_that_mentions_recaptcha_is_not_a_challenge():
    assert parse_google_state(
        "https://www.google.com/search?q=test",
        "A search result discussing reCAPTCHA performance",
        search_container_visible=True,
        recaptcha_visible=False,
    ) == "results"

def test_google_sorry_redirect_is_captcha():
    assert parse_google_state(
        "https://www.google.com/sorry/index?continue=x",
        "Our systems have detected unusual traffic",
        search_container_visible=False,
        recaptcha_visible=True,
    ) == "captcha"

def test_cloudflare_token_without_interaction_passes():
    assert parse_cloudflare_state("Success!", token_present=True, challenge_visible=False) == "passed"
```

Browser flow requirements:

- Launch `launch_persistent_context()` using the supplied temporary `profile_dir`, `fingerprint_preset="consistent"`, `args=["--fingerprint=63003"]`, `geoip=True`, `humanize=True`, and proxy.
- Caller/orchestrator will place profile inside `tempfile.TemporaryDirectory`; this function must close context in `finally` before returning.
- Visit `https://turnstiledemo.lusostreams.com/` once; wait up to 20 seconds for passed/interactive/error; never click. It is a third-party Cloudflare widget demo, not a universal reputation verdict.
- Visit one fixed Google query once; wait up to 15 seconds for results/challenge/consent; never click.
- Capture `cloudflare.png` and `google.png` after state detection.
- Return only verdicts and safe booleans. Never return/persist CAPTCHA token values, cookies, HTML, headers, or storage state.
- Browser navigation errors become per-site `error`/`unknown` results and must still close context.

Global constraints:

- One initial navigation per protected site; no retries and no CAPTCHA interaction.
- Credentials/tokens/cookies/storage never appear in output or exceptions.
- Parser tests require no network; browser launch must be monkeypatchable.
- Follow TDD with RED/GREEN evidence.
- Do not implement CLI orchestration.
- This is not Git; do not commit.

Verification: `python -m pytest tests/test_proxy_site_checks.py -q` and `python -m py_compile benchmarks/proxy_site_checks.py`.

Write full report to `.superpowers/sdd/task-4-report.md`.
