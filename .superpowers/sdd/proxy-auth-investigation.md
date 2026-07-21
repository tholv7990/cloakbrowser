# Proxy-auth argument-exposure investigation

**Scope:** read-only tracing of the proxy-quality scanner's browser path and
CloakBrowser proxy-auth launch code. No production changes or tests were run.

## Finding

The Final Review's Critical credential-in-child-process-arguments finding is
confirmed.  A browser-enabled scanner passes the complete `CLOAK_TEST_PROXY`
value to `launch_persistent_context` at
`benchmarks/proxy_site_checks.py:93-101`.  Python's persistent launcher then
resolves proxy configuration before constructing Chromium arguments
(`cloakbrowser/browser.py:535-541`) and supplies those arguments to Playwright
at `cloakbrowser/browser.py:575-583`.

For SOCKS5/SOCKS5H, the resolver always reconstructs/normalizes a URL with
inline credentials and returns `--proxy-server=<credentialed URL>`
(`cloakbrowser/browser.py:1542-1553`).  The core test explicitly verifies raw
`@` in the password is parsed using the final authority delimiter and becomes
an encoded credential in that argument (`tests/test_proxy.py:316-320`).

For authenticated HTTP/HTTPS, supported binaries likewise use inline
credentials (`cloakbrowser/browser.py:1555-1568`).  This includes Windows x64
at the current capability floor (`cloakbrowser/config.py:348-368`), and is
asserted directly by `tests/test_proxy.py:461-466`.  Thus keeping the scanner
input out of its own command line does not keep it out of Chromium's child
process arguments.  The design explicitly prohibits command-line exposure
(`docs/superpowers/specs/2026-07-21-proxy-quality-scanner-design.md:13-23`).

This is not confined to the persistent entry point: nonpersistent Python
launches use the same resolver and pass `chrome_args` at
`cloakbrowser/browser.py:209-229`; async persistent launches do so at
`cloakbrowser/browser.py:684-690` and `:724-732`.  The matching JavaScript and
.NET ports follow the same policy: `js/src/proxy.ts:235-280`,
`js/src/playwright.ts:302-335`, `dotnet/src/CloakBrowser/ProxyResolver.cs:283-344`,
and `dotnet/src/CloakBrowser/CloakLauncher.cs:153-190`.

## Existing mechanism assessment

There is an existing *partial* credential-free-from-Chromium-arguments path:
HTTP/HTTPS credentials on binaries below the inline-auth floor are parsed into
Playwright's `proxy` object instead of `proxy_extra_args`
(`cloakbrowser/browser.py:1421-1453`, `:1555-1573`; verified at
`tests/test_proxy.py:468-491`).  The resolver comment says this is a fallback
because the legacy path is a Playwright/CDP auth interceptor that breaks on
some proxies and Google domains (`cloakbrowser/browser.py:1530-1534`).

It cannot be reused unchanged for the scanner because:

1. It is automatically bypassed on the scanner's supported modern Windows
   build, and `browser_version` also controls `ensure_binary()`
   (`cloakbrowser/browser.py:535-537`), so spoofing an older version is not a
   safe mode switch.
2. It supports only HTTP/HTTPS. Authenticated SOCKS is deliberately always
   passed inline because Chromium performs SOCKS5 RFC 1929 auth
   (`cloakbrowser/browser.py:1542-1553`).
3. The core records an interoperability reason not to depend on the fallback
   for the scanner's Google result.  The scanner must support HTTP, HTTPS,
   SOCKS5, and SOCKS5H (design `:37-44`) and its primary browser checks include
   Google (plan `docs/superpowers/plans/2026-07-21-proxy-quality-scanner.md:340-347`).

Conclusion: no existing, reusable credential-free launch mechanism covers the
scanner's required protocols and site checks. A scanner-local relay is the
smallest complete remedy; it avoids changing public CloakBrowser behavior or
requiring matched Python/JS/.NET API changes.

## Small scoped localhost relay design

Add a benchmark-private module, e.g. `benchmarks/proxy_auth_relay.py`, with a
context-managed `AuthenticatedProxyRelay`:

* Parse and validate the raw upstream proxy once. Reuse the scanner's strict
  parser after it is fixed to reject path/query/fragment; retain decoded
  username/password only in the relay object, never in `repr`, exception text,
  logs, or results. The current validator permits suffixes
  (`benchmarks/proxy_intelligence.py:96-115`) and the current redactor's
  first-`@` regex leaks a raw-password suffix (`benchmarks/proxy_quality_models.py:52-55`,
  `:194-209`), so those two parsing fixes are prerequisites.
* Bind a TCP HTTP forward proxy only to `127.0.0.1` on port `0`; expose exactly
  `http://127.0.0.1:<allocated-port>` to Chromium. Do not use `0.0.0.0`, do
  not implement inbound authentication, and do not put credentials or the
  upstream hostname into the browser proxy URL.
* Accept ordinary absolute-form HTTP requests and `CONNECT`; tunnel each to
  the parsed upstream proxy. For HTTP/HTTPS upstream proxies, send the
  `Proxy-Authorization: Basic ...` header only on the relay-to-upstream leg
  (TLS-wrap the upstream connection for `https://` proxies). For SOCKS5 use
  the SOCKS5 username/password negotiation; for SOCKS5H send destination names
  to the upstream and for SOCKS5 preserve its documented local-resolution
  semantics. Stream bytes in both directions after connection establishment.
  This covers the scanner's required proxy schemes while Chromium sees only a
  loopback endpoint.
* In `run_browser_checks`, create the relay before `launch_persistent_context`
  and pass `relay.browser_proxy_url`, not `proxy`, at
  `benchmarks/proxy_site_checks.py:93-101`.  Keeping `geoip=True` means the
  core's preliminary exit-IP lookup (`cloakbrowser/browser.py:1146-1163`) also
  travels through the relay, so no raw credentials enter the browser launcher.
  The scanner's non-browser connectivity/intelligence adapters may continue to
  receive the raw in-memory proxy because they do not create Chromium child
  processes; their exception/serialization guards remain required.

### Lifecycle and failure cleanup

Use nested `try/finally` (or two context managers) so ordering is deterministic:

1. Start listener and workers; if startup fails, close any partially-created
   socket and raise a scrubbed configuration/launch error.
2. Launch the browser with the credential-free loopback URL.
3. Close the BrowserContext first (the existing scanner already attempts this
   at `benchmarks/proxy_site_checks.py:105-116`; core close also stops
   Playwright at `cloakbrowser/browser.py:594-603`).
4. Then close the relay listener, close active client/upstream sockets, signal
   workers, and join them with a bounded timeout. If browser launch fails, the
   relay must still close. Relay cleanup must never replace the scanner's safe
   all-error site outcome or emit raw exception text.

The relay must be per scan/browser invocation, never cached, and should leave
no profile, credential file, environment variable, or temporary artifact.

### Test seams and acceptance tests

Keep upstream parsing/handshake construction pure, and inject both the relay
factory and browser-launch callable into `run_browser_checks` (defaults retain
the public signature). This permits deterministic tests without a real browser.

* Unit: special-character credentials (`@`, `:`, `%`, `=`), IPv6, empty
  password, and invalid path/query/fragment never appear in a redacted value,
  exception, or relay `repr`.
* Unit: launch spy receives only `http://127.0.0.1:<port>` without username,
  password, or upstream host; it preserves the existing fingerprint/geoip
  arguments. Replace the current raw-proxy expectation at
  `tests/test_proxy_site_checks.py:249-279`.
* Unit: launch failure and page failure close the relay exactly once, after any
  context close; no credential appears in returned outcomes. Preserve the
  error-scrubbing scenario at `tests/test_proxy_site_checks.py:287-301`.
* Socket integration: a local authenticated HTTP upstream observes a correct
  authorization header while a local browser-side client never receives it;
  separate SOCKS5 and SOCKS5H fixtures assert RFC 1929 auth and destination
  address type. Verify the listener is unreachable after cleanup and workers
  have terminated.
* Resolver regression: inspect the arguments handed to the launcher and assert
  no `--proxy-server` value contains userinfo; do not rely solely on report
  serialization tests such as `tests/test_proxy_quality_models.py:82-84`.

## Recommendation

Fix strict parsing/redaction first, then add the benchmark-only loopback relay
and switch only the browser stage to it. Do not force the existing legacy
Playwright proxy-auth fallback: it is protocol-incomplete and documented as
unreliable for the exact Google check the scanner performs.
