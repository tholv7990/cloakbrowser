# Fingerprint Overrides and Coherence Validation Design

## Goal

Expose the patched Chromium binary's existing per-attribute fingerprint flags through all three CloakBrowser ports, then let the Manager store those optional choices and detect inconsistent identities before launch. Existing callers that omit every override must receive exactly the same Chromium arguments and launch behavior as before.

## Clean-room boundary

This design is based only on CloakBrowser's current repository, its documented `--fingerprint-*` interface, and standard browser fingerprint consistency rules. No external product source is an input to the implementation. The solution remains an all-binary masking design: it adds no page scripts, prototype overrides, or JavaScript injection.

## Scope

The wrapper adds seven optional attributes:

| API attribute | Chromium flag |
|---|---|
| `gpu_vendor` / `gpuVendor` / `GpuVendor` | `--fingerprint-gpu-vendor` |
| `gpu_renderer` / `gpuRenderer` / `GpuRenderer` | `--fingerprint-gpu-renderer` |
| `hardware_concurrency` / `hardwareConcurrency` / `HardwareConcurrency` | `--fingerprint-hardware-concurrency` |
| `device_memory` / `deviceMemory` / `DeviceMemory` | `--fingerprint-device-memory` |
| `screen_width` / `screenWidth` / `ScreenWidth` | `--fingerprint-screen-width` |
| `screen_height` / `screenHeight` / `ScreenHeight` | `--fingerprint-screen-height` |
| `brand` / `brand` / `Brand` | `--fingerprint-brand` |

The Manager remains Windows-only. This task does not add platform selection, behavioral changes, new spoofing surfaces, or viewport emulation.

## Wrapper API and validation

Python adds keyword-only optional parameters to all six public launch functions and to `build_args`. TypeScript adds camel-case optional properties to `LaunchOptions`, automatically covering Playwright and Puppeteer. .NET adds nullable properties to `LaunchOptions` and corresponding optional arguments to `CloakLauncher.BuildArgs`.

Validation is identical across ports:

- String values are trimmed and must remain non-empty.
- `hardware_concurrency` and `device_memory` must be integers from 1 through 1024 inclusive. Booleans are not integers for this API.
- `screen_width` and `screen_height` must be integers from 320 through 16384 inclusive. A caller may supply either dimension independently because the binary supports independent flags; Manager UI requires the pair when explicit screen mode is selected.
- Invalid dedicated values fail before Chromium launch with the port's normal argument-validation exception.

Argument priority becomes:

1. Generated stealth defaults, including the seed and platform.
2. Caller-provided raw arguments.
3. Dedicated timezone and locale parameters.
4. Dedicated fingerprint attribute overrides.
5. Extension and window-management flags.

Each dedicated override removes any existing occurrence of the same flag key and appends one normalized flag. This guarantees exactly one occurrence after the seed even when raw arguments contained the same key. When every new option is omitted, `build_args` returns the same values in the same order as the current implementation.

Screen flags only configure the patched binary. They never create or change a Playwright/Puppeteer viewport.

## Manager persistence and API

A new additive Alembic migration adds these nullable columns to `profiles`:

- `gpu_vendor` and `gpu_renderer`: strings up to 256 characters.
- `hardware_concurrency` and `device_memory`: integers.
- `screen_width` and `screen_height`: integers.
- `browser_brand`: string up to 64 characters. The database name avoids ambiguity with product branding while API/runtime mapping uses `brand`.

The SQLAlchemy model, create/patch/read schemas, profile service serialization, portability representation, backup behavior, and generated OpenAPI contract carry the fields. Schema validators apply the same ranges as the wrappers. Manager screen dimensions are either both null or both present.

These fields participate in `build_fingerprint_identity` and its configuration hash. Changing one therefore records an identity configuration change without changing the stable seed. Existing rows remain null and retain seed-derived behavior.

`profile_launch_snapshot` copies the seven values. The runtime launch adapter passes them into `launch_persistent_context`; no raw flag construction is duplicated in Manager code. Window validation uses the effective masked screen: explicit screen dimensions when present, otherwise the current 1920x1080 manager baseline. A custom browser window cannot exceed that screen.

## Coherence validator

`manager_backend/features/profiles/fingerprint_coherence.py` defines a pure function:

```python
def validate_fingerprint_coherence(profile: Mapping[str, Any]) -> dict[str, Any]:
    ...
```

It returns:

```json
{
  "status": "coherent | warning | error",
  "findings": [
    {"code": "...", "severity": "warning | error", "field": "...", "message": "..."}
  ]
}
```

Findings are deterministic and ordered by rule definition. The function never mutates its input.

Hard errors:

- A custom UA must contain `Windows NT`, the Manager's fixed effective platform token.
- A custom UA Chromium major must equal the pinned browser major when both are present.
- A recognizable NVIDIA, AMD/ATI, or Intel GPU vendor must agree with the renderer family.
- Direct3D is accepted only for Windows. Apple/Metal renderers are rejected for the Windows-only Manager persona.

Warnings:

- A manual timezone differing from a successfully proxy-verified timezone.
- A manual locale whose country subtag is implausible for the successfully verified proxy country.

Geo rules reuse Manager proxy-test/GeoIP data and a single shared country-to-locale mapping rather than creating a second independent geography source. Missing or unverified proxy geography produces no mismatch warning because the validator cannot substantiate one.

The validator runs while editing and again on the backend before launch. Error findings block launch; warnings are returned and displayed but do not block. Existing schema validation remains the first line of defense for malformed values.

## UI

The Browser Identity step adds an optional "Explicit fingerprint attributes" section. Empty controls mean automatic seed-derived values. Screen width and height are edited as a pair. The review step shows only explicit overrides.

The editor calls the backend validation endpoint with the draft profile and renders findings adjacent to the relevant fields plus a compact summary. Errors disable save/start actions; warnings remain visible but allow completion. English and Vietnamese message keys are added together. The UI does not interpret UA, GPU, timezone, or locale itself; backend finding codes are the source of truth.

## Tests

TDD applies independently to each deliverable.

- Python tests prove omitted values preserve the exact baseline list, all supplied values produce exact normalized flags once and after the seed, raw duplicates are displaced, invalid values fail, and no viewport flag is introduced.
- TypeScript Vitest tests cover the same fixture inputs and expected ordered array.
- .NET tests cover the same fixture inputs and expected ordered list.
- A shared parity fixture documents one common input and expected flag sequence consumed or asserted by all ports.
- Manager unit tests cover every validator rule, deterministic ordering, non-mutation, a coherent profile, warnings versus errors, model/schema ranges, migration upgrade, identity-hash changes, snapshot propagation, launch blocking, and API serialization.
- Frontend tests cover field editing, paired screens, inline findings, warning/error presentation, save blocking, and English/Vietnamese key parity.

## Release gates

The change is complete only when these commands succeed:

```text
pytest -m "not slow"
pytest tests/manager -m "not slow" -q
cd js && npm run typecheck && npm run test && npm run build
cd dotnet && dotnet test CloakBrowser.sln
python -m manager_backend.export_openapi
```

After OpenAPI generation, the checked-in contract must have no unexplained diff. A final parity test must demonstrate identical fingerprint override flag sets and ordering for Python, TypeScript, and .NET.

## Error handling and compatibility

Invalid public API arguments fail synchronously before binary resolution or browser startup. Manager validation errors use stable machine-readable codes; user-facing text remains localizable. Existing profiles migrate with null overrides and launch unchanged. Existing wrapper callers compile and behave unchanged because every new parameter/property is optional.
