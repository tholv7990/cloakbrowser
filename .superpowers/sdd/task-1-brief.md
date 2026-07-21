### Task 1: Deterministic report model and secret guard

Create `benchmarks/proxy_quality_models.py` and `tests/test_proxy_quality_models.py`.

Produce these exact interfaces:

- `NetworkType`, `Confidence`, `Reputation`, and `Suitability` string enums.
- `classify_network(signals: list[dict[str, object]]) -> dict[str, object]`.
- `summarize_report(report: dict[str, object]) -> dict[str, str]`.
- `redact_proxy(proxy: str) -> str`, supporting URI and host:port:user:password forms.
- `assert_no_secrets(value: object, secrets: set[str]) -> None`.

Required tests and behavior:

```python
def test_two_mobile_signals_are_high_confidence():
    result = classify_network([
        {"source": "ipinfo", "is_mobile": True, "carrier": "Example Mobile"},
        {"source": "asn", "asn_type": "isp", "mcc": "452"},
    ])
    assert result == {"type": "mobile", "type_confidence": "high", "conflicts": []}

def test_hosting_asn_name_heuristic_is_low_confidence():
    result = classify_network([
        {"source": "sapics", "asn": "AS64500", "organization": "Example Cloud Hosting"},
    ])
    assert result["type"] == "datacenter_or_hosting"
    assert result["type_confidence"] == "low"

def test_clean_observed_requires_all_live_signals():
    summary = summarize_report({
        "connectivity": {"success": True, "exit_ip_agreement": True},
        "reputation_intelligence": {"high_confidence_matches": [], "other_matches": []},
        "identity_alignment": {"aligned": True},
        "site_outcomes": {"cloudflare": "passed", "google": "results"},
    })
    assert summary["reputation"] == "clean_observed"
    assert summary["suitable_for_protected_sites"] == "yes"

def test_secret_guard_rejects_nested_password():
    with pytest.raises(ValueError, match="secret"):
        assert_no_secrets({"nested": ["sample-password"]}, {"sample-password"})

def test_proxy_redaction_supports_uri_and_colon_formats():
    assert redact_proxy("socks5://u:p@203.0.113.8:1080") == "socks5://***:***@203.0.113.8:1080"
    assert redact_proxy("203.0.113.8:1080:u:p") == "203.0.113.8:1080:***:***"
```

Summary precedence:

```python
if google in {"captcha", "blocked"} or cloudflare in {"interactive", "blocked"} or high_matches:
    reputation = "blocked"
elif other_matches or not exit_ip_agreement or not identity_aligned:
    reputation = "questionable"
elif all_required_checks_pass:
    reputation = "clean_observed"
else:
    reputation = "unknown"
```

Classification must count independent structured sources, record conflicts, and use ASN-name terms only as a low-confidence fallback. Hosting terms are `hosting`, `cloud`, `datacenter`, `data center`, and `vps`. Mobile structured fields are `is_mobile`, `carrier`, `mcc`, and `mnc`; an arbitrary organization containing `telecom` is not sufficient for mobile classification.

Global constraints:

- Never log or serialize proxy usernames, passwords, authentication headers, cookies, CAPTCHA tokens, or browser storage.
- Classification based only on ASN-name heuristics has low confidence.
- Follow TDD: record RED and GREEN evidence.
- This is not a Git repository; do not commit. Use compilation/tests as the checkpoint.

Verification:

```powershell
python -m pytest tests/test_proxy_quality_models.py -q
python -m py_compile benchmarks/proxy_quality_models.py
```

Write the full implementation report to `.superpowers/sdd/task-1-report.md`.
