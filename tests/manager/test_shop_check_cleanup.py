"""Shop-check cleanup: delete a run's OWNED profiles only, from provenance.

Ownership is the immutable `shop_check_workers.profile_id` row — never a name,
tag, or client-supplied id/path. Owned runtimes are stopped before deletion,
directories are contained under the profile root, and a filesystem failure
leaves a retryable result (the DB row stays).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.profiles.directories import resolve_profile_directory
from manager_backend.features.shop_check.cleanup import cleanup_run, resolve_owned_profile_ids
from manager_backend.models import Profile, ShopCheckRun, ShopCheckWorker


class FakeRuntimeManager:
    def __init__(self):
        self.stopped: list[str] = []

    def stop(self, profile_id: str):
        self.stopped.append(profile_id)
        return None


def _run(session, status="running") -> str:
    run = ShopCheckRun(
        status=status, emails_per_profile=5, max_parallel=1,
        target_url="https://shop.app/", total_emails=0,
    )
    session.add(run)
    session.flush()
    return run.id


def _owned_profile(session, settings, run_id, ordinal) -> str:
    pid = str(uuid4())
    session.add(Profile(
        id=pid, name=f"shopchk {ordinal}",
        fingerprint_seed=uuid4().hex, fingerprint_config_hash="0" * 64,
    ))
    session.add(ShopCheckWorker(
        run_id=run_id, ordinal=ordinal, state="terminal", profile_id=pid, assigned_count=0,
    ))
    session.commit()
    directory = resolve_profile_directory(settings, pid)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "marker").write_text("x", encoding="utf-8")
    return pid


def _bare_profile(session, name) -> str:
    pid = str(uuid4())
    session.add(Profile(
        id=pid, name=name, fingerprint_seed=uuid4().hex, fingerprint_config_hash="0" * 64,
    ))
    session.commit()
    return pid


def test_deletes_owned_profiles_only(db_session_factory, settings):
    with db_session_factory() as session:
        run_id = _run(session)
        owned = [_owned_profile(session, settings, run_id, i) for i in range(2)]
        # A manual profile with the SAME name/tag as an owned one must survive.
        manual = _bare_profile(session, "shopchk 0")
        # Another run's owned profile must survive.
        other_run = _run(session)
        other = _owned_profile(session, settings, other_run, 0)
        session.commit()

    runtime = FakeRuntimeManager()
    with db_session_factory() as session:
        result = cleanup_run(session, settings, runtime, run_id, expected_profile_count=2)

    assert result["deleted"] == 2 and result["failed"] == 0
    assert result["cleanup_state"] == "done"
    # Owned runtimes were stopped before deletion.
    assert set(runtime.stopped) == set(owned)
    with db_session_factory() as session:
        assert all(session.get(Profile, pid) is None for pid in owned)
        assert session.get(Profile, manual) is not None      # survived
        assert session.get(Profile, other) is not None       # other run survived
    for pid in owned:
        assert not resolve_profile_directory(settings, pid).exists()
    assert resolve_profile_directory(settings, other).exists()


def test_count_mismatch_is_rejected(db_session_factory, settings):
    with db_session_factory() as session:
        run_id = _run(session)
        _owned_profile(session, settings, run_id, 0)
        session.commit()
    runtime = FakeRuntimeManager()
    with db_session_factory() as session:
        with pytest.raises(ManagerError) as excinfo:
            cleanup_run(session, settings, runtime, run_id, expected_profile_count=5)
    assert excinfo.value.status_code == 409
    # Nothing deleted on a mismatch.
    with db_session_factory() as session:
        assert len(resolve_owned_profile_ids(session, run_id)) == 1


def test_filesystem_failure_leaves_retryable_result(db_session_factory, settings, monkeypatch):
    with db_session_factory() as session:
        run_id = _run(session)
        good = _owned_profile(session, settings, run_id, 0)
        bad = _owned_profile(session, settings, run_id, 1)
        session.commit()

    bad_dir = str(resolve_profile_directory(settings, bad))
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path, *args, **kwargs):
        if str(path) == bad_dir:
            raise OSError("file in use")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("manager_backend.features.shop_check.cleanup.shutil.rmtree", flaky_rmtree)

    runtime = FakeRuntimeManager()
    with db_session_factory() as session:
        result = cleanup_run(session, settings, runtime, run_id, expected_profile_count=2)

    assert result["deleted"] == 1 and result["failed"] == 1
    assert result["cleanup_state"] == "partial"
    with db_session_factory() as session:
        assert session.get(Profile, good) is None       # cleaned
        assert session.get(Profile, bad) is not None     # row kept -> retryable
    assert resolve_profile_directory(settings, bad).exists()


def test_no_owned_profiles_is_a_clean_done(db_session_factory, settings):
    with db_session_factory() as session:
        run_id = _run(session)
        session.commit()
    with db_session_factory() as session:
        result = cleanup_run(session, settings, FakeRuntimeManager(), run_id, expected_profile_count=0)
    assert result["requested"] == 0 and result["cleanup_state"] == "done"
