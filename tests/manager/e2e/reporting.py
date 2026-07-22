from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SENSITIVE_FRAGMENTS = (
    "password",
    "cookie",
    "csrf",
    "session",
    "license",
    "token",
    "secret",
    "email",
    "authorization",
)


def _sensitive_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def redact(value: Any, *, secrets: tuple[str, ...] | list[str] = ()) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if _sensitive_key(key)
                else redact(item, secrets=secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            if secret:
                result = result.replace(secret, "[redacted]")
        return result
    return value


def write_report(
    report_root: Path,
    payload: dict[str, Any],
    *,
    secrets: tuple[str, ...] | list[str] = (),
) -> tuple[Path, Path]:
    report_root.mkdir(parents=True, exist_ok=True)
    safe = redact(payload, secrets=secrets)
    json_path = report_root / "report.json"
    markdown_path = report_root / "report.md"
    json_path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    steps = safe.get("steps", []) if isinstance(safe, dict) else []
    lines = ["# CloakBrowser Manager E2E", ""]
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            lines.append(f"- {step.get('name', 'step')}: {step.get('status', 'unknown')}")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
