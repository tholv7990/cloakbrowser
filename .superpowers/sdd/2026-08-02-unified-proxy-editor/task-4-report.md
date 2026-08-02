# Task 4 report: unified proxy editor release gates

## Status

Task 4 cleanup is complete. The duplicate inline proxy editor is removed, the
Vietnamese clear-credential copy uses proper diacritics, and the proxy-focused
release gates pass. The broader manager and root non-slow gates retain unrelated
pre-existing/platform failures documented below.

## Reference and coverage proof

- Before deletion, `rg -n "ProxyInlineForm|OneProxy" manager/frontend/src
  --glob "!**/*.test.*"` found references only inside
  `manager/frontend/src/features/proxies/ProxyInlineForm.tsx`; there were no
  production consumers.
- After deletion, the same production search returned no matches. A second
  search including tests also returned no matches, so no stale imports or
  obsolete tests remain.
- There was no `ProxyInlineForm` test to relocate. Its useful behavior is already
  preserved by `src/schemas/proxy.test.ts` (9 schema/payload tests) and
  `src/features/proxies/ProxyEditorDrawer.test.tsx` (14 editor tests), including
  parsing, ad-hoc Quick Test of unsaved/current values, stored-credential clear
  and replacement, create-before-quality-test, and dirty-value preservation.
- Assignment removal without deleting a reusable proxy remains covered by
  `quickAddProxy.test.tsx` and `NewProfileModal.test.tsx`.

## Changes

- Deleted the unused `ProxyInlineForm.tsx` / `OneProxy` implementation.
- Changed the Vietnamese strings to:
  - `Xóa thông tin đăng nhập đã lưu`
  - `Xóa tên đăng nhập và mật khẩu đã lưu khi bạn lưu.`

## OpenAPI regeneration and diff

- `python -m manager_backend.export_openapi`: exit 0.
- Regeneration produced no working-tree diff, so there is no unrelated schema
  drift. The checked-in contract was already synchronized by the preceding
  proxy work.
- Semantic inspection of `components.schemas.ProxyRead.properties` confirms
  `password` is absent and `has_password` is present. Write/request schemas
  retain write-only password fields where required.

## Release gates

| Gate | Result |
| --- | --- |
| Frontend typecheck (`npm run typecheck`) | PASS, exit 0 |
| Full frontend tests (`npm run test`) | PASS: 36 files, 185 tests |
| Frontend build (`npm run build`) | PASS: 1,791 modules, built in 6.83s; existing >500 kB chunk warning |
| Focused proxy backend suite | PASS: 71 tests in 19.84s; 1 upstream Starlette/httpx deprecation warning |
| Manager non-slow (`pytest tests/manager -m "not slow" -q`) | FAIL: 1 failed, 1,086 passed, 4 skipped, 1 deselected, 1 warning in 287.37s |
| Root non-slow (`pytest -m "not slow" -q`) | FAIL: 22 failed, 2,083 passed, 11 skipped, 41 deselected, 3 warnings in 391.58s |

### Manager non-slow failure

`tests/manager/test_runtime_manager.py::test_launch_queue_limits_concurrent_browser_starts`
expected exactly one runtime in `queued`, but observed all three in `starting`.
An isolated rerun reproduced the same failure in 0.67s. Neither the runtime
manager nor this test is changed by Task 4; the proxy-focused suite passes.

### Root non-slow failures

The repository-wide failures are outside Task 4 and are reported verbatim by
test node/category rather than hidden:

- `tests/test_build_args.py::test_override_logs_debug` (expected debug capture)
- `tests/test_cloakserve.py::TestParseCliArgs::test_default_data_dir_bare_metal`
  (POSIX separator expectation on Windows)
- `tests/test_extract.py::TestPermissions::test_is_executable_false` (POSIX
  executable-bit expectation on Windows)
- `tests/test_geoip.py::test_maybe_resolve_geoip_timeout_returns_existing_values`
  (0.521s exceeded the 0.5s threshold)
- `tests/test_launch_context.py::test_default_viewport`
- `tests/test_launch_context.py::test_async_default_viewport`
- `tests/test_license.py::TestResolveLicenseKey::test_returns_none_when_absent`
- `tests/test_license.py::TestResolveLicenseKey::test_file_fallback`
- `tests/test_license.py::TestBuildLaunchEnv::test_explicit_param_injects_env`
- `tests/test_persistent_context.py::test_persistent_context_default_viewport`
- `tests/test_persistent_context.py::test_persistent_context_proxy_string`
- `tests/test_proxy.py::TestResolveProxyConfig::test_socks5_string_logs_info_when_reencoding`
- `tests/test_proxy.py::TestResolveProxyConfig::test_socks5_string_malformed_port_passes_through`
- `tests/test_proxy.py::TestResolveProxyConfig::test_http_string_with_creds_on_macos_falls_back`
- `tests/test_proxy.py::TestResolveProxyConfig::test_http_dict_with_creds_on_macos_falls_back`
- `tests/test_proxy.py::TestResolveProxyConfig::test_http_string_with_creds_on_linux_arm_falls_back`
- `tests/test_update.py::TestDownloadUrl::test_default_url_format`
- `tests/test_update.py::TestGetLatestVersion::test_parses_chromium_tag_with_platform_asset`
- `tests/test_update.py::TestGetLatestVersion::test_skips_release_without_platform_asset`
- `tests/test_update.py::TestGetLatestVersion::test_skips_draft_releases`
- `tests/test_update.py::TestGetLatestVersion::test_skips_non_chromium_tags`
- `tests/test_update.py::TestWrapperUpdateCheck::test_warns_when_newer_version_available`

These are Windows/platform/environment or unrelated wrapper-behavior failures;
none involves a Task 4 file. The manager queue failure did not recur in the root
run, consistent with its scheduling-sensitive assertion.

## Authenticated smoke test

Blocked safely: no authorized local-manager endpoint or authentication was
supplied for this task. Performing mutations against a guessed endpoint would
violate the instruction to use only an authorized supplied endpoint. No live
proxy was created, modified, or deleted, and no credentials were logged.

Automated authenticated API/UI coverage does verify the requested paths:
unsaved/current-value SOCKS5 Quick Test, create/save, label-only edits preserving
credentials, assignment removal without reusable-proxy deletion, explicit test
proxy deletion behavior, and password omission from API responses/UI models.
This automated evidence is not represented as a live smoke test.

## Commit

This report and the cleanup are committed together as
`test(proxy): close unified editor release gates`.

## Self-review

- Re-read the Task 4 brief and checked every requirement against the diff and
  recorded evidence.
- `git diff --check` passes.
- The final diff is scoped to the obsolete component deletion, two Vietnamese
  translations, and this report.
- No competitor archive or `.impeccable/hook.cache.json` content was inspected
  or modified.

## Concerns

- Manager and root non-slow suites are not fully green for the unrelated reasons
  above.
- Live authenticated smoke evidence remains unavailable until an authorized
  endpoint/session is supplied.
