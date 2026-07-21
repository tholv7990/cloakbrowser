from __future__ import annotations

import os
import time

import psutil
import pytest

from cloakbrowser.config import get_binary_path
from manager_backend.features.runtime.manager import RuntimeManager
from manager_backend.models import Profile, RuntimeSession


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.name != "nt", reason="Windows runtime integration only"),
    pytest.mark.skipif(
        os.environ.get("CLOAK_RUN_RUNTIME_SLOW") != "1",
        reason="set CLOAK_RUN_RUNTIME_SLOW=1 to launch a real browser",
    ),
]


def test_real_runtime_owns_and_persists_profile(db_session_factory, settings):
    if not get_binary_path().is_file():
        pytest.skip("CloakBrowser binary is not installed")
    with db_session_factory() as session:
        profile = Profile(
            name="Windows runtime integration",
            fingerprint_seed="987654321",
            fingerprint_config_hash="b" * 64,
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id

    manager = RuntimeManager(db_session_factory, settings)
    runtime = manager.start(profile_id)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with db_session_factory() as session:
            stored = session.get(RuntimeSession, runtime.id)
            if stored.state in {"running", "crashed"}:
                break
        time.sleep(0.1)
    assert stored.state == "running", stored.last_message
    assert (settings.profile_root / profile_id / "user-data").is_dir()
    assert stored.browser_pid is not None
    assert psutil.Process(stored.browser_pid).is_running()

    manager.stop(profile_id)
    manager.shutdown()
    assert (settings.profile_root / profile_id / "user-data").is_dir()
