# Authenticated proxy relay implementation report

## Scope

Implemented the scanner-private relay in the two authorized new code files:

- `benchmarks/proxy_auth_relay.py`
- `tests/test_proxy_auth_relay.py`

No existing production or test file was edited. Test authentication strings are
documentation-only samples and are not usable credentials.

## TDD evidence

RED was recorded after adding the test file and before adding the production
module:

```text
python -m pytest tests/test_proxy_auth_relay.py -q
ERROR tests/test_proxy_auth_relay.py
ModuleNotFoundError: No module named 'benchmarks.proxy_auth_relay'
Exit code: 1
```

The first implementation run passed 10 tests and exposed a Windows port-reuse
race in the failure fixture. The fixture was changed to use an accepting server
that deterministically closes the upstream connection. The final focused run:

```text
python -m pytest tests/test_proxy_auth_relay.py -q
...............                                                          [100%]
15 passed in 1.00s
Exit code: 0
```

## Requirements evidence

- The listener is hard-bound to `127.0.0.1` with port `0`; the browser-facing
  URL contains only the allocated loopback endpoint.
- HTTP and TLS-wrapped HTTPS upstream CONNECT use Basic authentication only on
  the relay-to-upstream leg. Tests cover encoded and raw `@`, `:`, `%`, `=`, and
  an empty password.
- SOCKS5 and SOCKS5H use RFC 1929 username/password negotiation and CONNECT.
  Socket tests assert local resolution/address literals for SOCKS5 and upstream
  hostname delegation for SOCKS5H.
- DNS observations contain only delegation mode and destination kind; they do
  not retain destination or upstream hostnames.
- Configuration errors, `repr`, browser error responses, and the browser proxy
  URL contain no upstream identity or credential material.
- Listener, client, and upstream sockets close on context exit. Shutdown is
  idempotent, active tunnels are interrupted, and listener/worker joins share a
  bounded deadline.
- Ordinary absolute-form HTTP is intentionally rejected with a safe 405; HTTPS
  CONNECT is the required browser path and is fully exercised offline.

## Concerns / integration boundary

This isolated subtask does not modify `benchmarks/proxy_site_checks.py`; a
separate integration change must construct this relay around browser launch and
pass `relay.browser_proxy_url` instead of the authenticated upstream URL.
