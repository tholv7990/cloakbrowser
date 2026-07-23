"""The seam between the automation orchestration and the live browser.

The coordinator owns all DB state, credential handling, and human-gate blocking.
The controller does the actual browser work — inject the recorder, drive replay —
and reports back only through the callbacks on RunItemContext.

The default StubAutomationController raises a clear 501 for anything that needs a
browser: orchestration (templates, credential pool, run/factory bookkeeping) is
real and tested, but record/replay is a follow-up that wires a Playwright
command queue into ProfileWorker. Tests inject a fake controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ...errors import ManagerError


@dataclass
class RunItemContext:
    run_id: str
    profile_id: str
    steps: list[dict]
    variables: dict[str, str]
    # (email, password) resolved from the secure store at run time; NEVER persisted.
    secret: tuple[str, str] | None
    start_step: int
    # set_progress(step_index): record last_completed_step.
    set_progress: Callable[[int], None]
    # request_attention(reason) -> True to continue, False if the run was cancelled.
    request_attention: Callable[[str], bool]
    # is_cancelled() -> True once the run is cancelled; poll it in long replays so a
    # cancel aborts promptly instead of running to completion (and holding a credential).
    is_cancelled: Callable[[], bool]


class AutomationController(Protocol):
    def start_recording(self, recording_id: str, profile_id: str) -> None: ...

    def recording_step_count(self, recording_id: str) -> int: ...

    def finish_recording(self, recording_id: str) -> list[dict]: ...

    def cancel_recording(self, recording_id: str) -> None: ...

    def run_item(self, ctx: RunItemContext) -> None: ...


def _unavailable() -> ManagerError:
    return ManagerError(
        "automation_runtime_unavailable",
        "The automation browser runtime (recorder/replay) is not available in this build.",
        501,
    )


class StubAutomationController:
    def start_recording(self, recording_id: str, profile_id: str) -> None:
        raise _unavailable()

    def recording_step_count(self, recording_id: str) -> int:
        return 0

    def finish_recording(self, recording_id: str) -> list[dict]:
        raise _unavailable()

    def cancel_recording(self, recording_id: str) -> None:
        return None

    def run_item(self, ctx: RunItemContext) -> None:
        raise _unavailable()
