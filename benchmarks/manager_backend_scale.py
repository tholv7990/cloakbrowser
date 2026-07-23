"""Repeatable local SQLite read benchmark for the Profile Manager.

Run from the repository root:
    python benchmarks/manager_backend_scale.py
"""

from __future__ import annotations

import tempfile
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manager_backend.features.media.service import list_assets
from manager_backend.features.profiles.service import list_profiles
from manager_backend.features.proxies.service import list_proxies
from manager_backend.features.resources.service import list_sessions
from manager_backend.features.runtime.snapshots import RuntimeSnapshotCache
from manager_backend.models import (
    Base,
    MediaAsset,
    Profile,
    Proxy,
    RuntimeSession,
    profile_media_assets,
)


T = TypeVar("T")
PROFILE_COUNT = 1_000
SESSIONS_PER_PROFILE = 100
PROXY_COUNT = 1_000
MEDIA_COUNT = 100


class QueryCounter:
    def __init__(self, engine: Engine) -> None:
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._increment)

    def _increment(self, *_args) -> None:
        self.count += 1


def _measure(
    name: str, counter: QueryCounter, operation: Callable[[], T]
) -> T:
    counter.count = 0
    started = perf_counter()
    result = operation()
    elapsed_ms = (perf_counter() - started) * 1_000
    print(f"{name:24} {elapsed_ms:9.2f} ms  {counter.count:3} SQL statements")
    return result


def _seed(engine: Engine) -> None:
    now = datetime.now(timezone.utc)
    proxy_ids = [str(uuid4()) for _ in range(PROXY_COUNT)]
    profile_ids = [str(uuid4()) for _ in range(PROFILE_COUNT)]
    media_ids = [str(uuid4()) for _ in range(MEDIA_COUNT)]

    with engine.begin() as connection:
        connection.execute(
            Proxy.__table__.insert(),
            [
                {
                    "id": proxy_id,
                    "label": f"proxy-{index:04}",
                    "scheme": "http",
                    "host": "127.0.0.1",
                    "port": 8000 + index,
                }
                for index, proxy_id in enumerate(proxy_ids)
            ],
        )
        connection.execute(
            Profile.__table__.insert(),
            [
                {
                    "id": profile_id,
                    "name": f"profile-{index:04}",
                    "fingerprint_seed": f"{index:020x}",
                    "fingerprint_config_hash": "0" * 64,
                    "proxy_id": proxy_ids[index],
                }
                for index, profile_id in enumerate(profile_ids)
            ],
        )
        for session_offset in range(SESSIONS_PER_PROFILE):
            created_at = now - timedelta(minutes=SESSIONS_PER_PROFILE - session_offset)
            connection.execute(
                RuntimeSession.__table__.insert(),
                [
                    {
                        "id": str(uuid4()),
                        "profile_id": profile_id,
                        "state": "stopped",
                        "last_message": "stopped",
                        "created_at": created_at,
                        "updated_at": created_at,
                    }
                    for profile_id in profile_ids
                ],
            )
        connection.execute(
            MediaAsset.__table__.insert(),
            [
                {
                    "id": media_id,
                    "name": f"asset-{index:03}",
                    "kind": "camera",
                    "format": "video/mp4",
                    "size_bytes": 0,
                }
                for index, media_id in enumerate(media_ids)
            ],
        )
        connection.execute(
            profile_media_assets.insert(),
            [
                {
                    "profile_id": profile_ids[index],
                    "media_asset_id": media_id,
                }
                for index, media_id in enumerate(media_ids)
            ],
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cloak-manager-benchmark-") as directory:
        database = Path(directory) / "manager.db"
        engine = create_engine(f"sqlite:///{database.as_posix()}")
        Base.metadata.create_all(engine)

        seed_started = perf_counter()
        _seed(engine)
        print(
            f"Seeded {PROFILE_COUNT:,} profiles, "
            f"{PROFILE_COUNT * SESSIONS_PER_PROFILE:,} sessions, "
            f"{PROXY_COUNT:,} proxies, and {MEDIA_COUNT:,} media assets "
            f"in {perf_counter() - seed_started:.2f} s.\n"
        )

        counter = QueryCounter(engine)
        with Session(engine) as session:
            profiles = _measure(
                "profile page (100)",
                counter,
                lambda: list_profiles(
                    session,
                    query=None,
                    folder_id=None,
                    tag_id=None,
                    workflow_status_id=None,
                    pinned=None,
                    sort="name",
                    page=1,
                    page_size=100,
                ),
            )
            assert counter.count == 4
            proxies = _measure("proxy list (1,000)", counter, lambda: list_proxies(session))
            assert counter.count == 2
            media = _measure("media list (100)", counter, lambda: list_assets(session))
            assert counter.count == 2
            sessions = _measure(
                "recent sessions (100)", counter, lambda: list_sessions(session, 100)
            )
            assert counter.count == 1
            cache = RuntimeSnapshotCache()
            initial_snapshot = _measure(
                "initial runtime snapshot",
                counter,
                lambda: cache.poll(session),
            )
            assert counter.count == 4
            idle_snapshot = _measure(
                "unchanged snapshot poll",
                counter,
                lambda: cache.poll(session),
            )
            assert counter.count == 3

        assert len(profiles["items"]) == 100
        assert len(proxies) == PROXY_COUNT
        assert len(media) == MEDIA_COUNT
        assert len(sessions) == 100
        assert initial_snapshot.changed is True
        assert len(initial_snapshot.runtimes) == PROFILE_COUNT
        assert idle_snapshot.changed is False
        engine.dispose()


if __name__ == "__main__":
    main()
