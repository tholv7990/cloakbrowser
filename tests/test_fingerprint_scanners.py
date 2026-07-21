from benchmarks.fingerprint_scanners import parse_pixelscan_verdict, redact_proxy


def test_redact_proxy_hides_uri_credentials():
    value = "socks5://sample-user:sample-password@203.0.113.10:50101"
    assert redact_proxy(value) == "socks5://***:***@203.0.113.10:50101"


def test_redact_proxy_hides_colon_format_credentials():
    value = "203.0.113.10:50101:sample-user:sample-password"
    assert redact_proxy(value) == "203.0.113.10:50101:***:***"


def test_parse_pixelscan_verdict_accepts_clean_persistent_profile():
    text = """
    Consistent
    No masking detected
    No automated behavior detected
    Proxy detected: no
    Incognito Window: no
    """
    verdict = parse_pixelscan_verdict(text)
    assert verdict == {
        "consistent": True,
        "masking_detected": False,
        "automation_detected": False,
        "incognito": False,
    }


def test_parse_pixelscan_verdict_detects_failures():
    text = """
    Inconsistent
    Masking detected
    Automated behavior detected
    Incognito Window: yes
    """
    verdict = parse_pixelscan_verdict(text)
    assert verdict == {
        "consistent": False,
        "masking_detected": True,
        "automation_detected": True,
        "incognito": True,
    }


def test_parse_pixelscan_verdict_supports_redesigned_result_page():
    text = """
    Your Browser Fingerprint
    Fingerprint Check
    Verify your browser fingerprint
    No masking detected
    No automated behavior detected
    """
    verdict = parse_pixelscan_verdict(text)
    assert verdict["consistent"] is True
    assert verdict["masking_detected"] is False
