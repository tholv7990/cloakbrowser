# Task 1 report: deterministic report model and secret guard

## Delivered files

- `benchmarks/proxy_quality_models.py`
- `tests/test_proxy_quality_models.py`

The implementation provides the requested string enums, deterministic network
classification, report summarization, proxy credential redaction, and recursive
secret detection. It performs no logging, serialization, network access, or
other I/O.

## TDD evidence

### RED 1: requested public interface

I first added the requested tests (plus enum and security regression coverage)
before creating the production module.

Command:

```powershell
python -m pytest tests/test_proxy_quality_models.py -q
```

Observed result:

```text
ModuleNotFoundError: No module named 'benchmarks.proxy_quality_models'
```

This was the expected failure: the requested module and interfaces did not yet
exist.

### GREEN 1: minimal model implementation

After adding `benchmarks/proxy_quality_models.py`, I ran:

```powershell
python -m pytest tests/test_proxy_quality_models.py -q
python -m py_compile benchmarks/proxy_quality_models.py
```

Observed result:

```text
8 passed in 0.03s
```

Compilation exited successfully.

### RED 2: ASN-name fallback cannot outweigh structured evidence

During self-review I added a regression test showing that two independent
structured mobile signals must remain decisive when separate ASN organization
names contain hosting terms. Before the correction, the test failed because the
result was `unknown` with low confidence instead of `mobile` with high
confidence.

Command:

```powershell
python -m pytest tests/test_proxy_quality_models.py -q
```

Observed result:

```text
1 failed, 8 passed
```

### GREEN 2: heuristic evidence is fallback-only

I changed the classifier so ASN-name terms are considered only when there is no
structured classification evidence. They are still retained as a recorded
conflict when appropriate, but cannot offset structured source votes.

Final verification commands:

```powershell
python -m pytest tests/test_proxy_quality_models.py -q
python -m py_compile benchmarks/proxy_quality_models.py
```

Observed result:

```text
9 passed in 0.04s
```

Compilation exited successfully.

## Self-review

- Independent source IDs prevent multiple fields from one named source from
  inflating confidence.
- Mobile classification uses only the specified structured fields; an arbitrary
  organization name containing `telecom` is not mobile evidence.
- Hosting ASN-name terms are low-confidence fallback evidence only.
- Summary precedence is ordered blocked, questionable, clean observed, then
  unknown exactly as required.
- Proxy redaction replaces URI and colon-format credentials without emitting
  them.
- The secret guard recursively checks nested mappings and containers, including
  secret substrings in authorization-style strings, while avoiding arbitrary
  object stringification.

## Concerns

None. The workspace is not a Git repository; no commit was attempted.
