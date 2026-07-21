from __future__ import annotations

import os
import json
from pathlib import Path

import psutil

from ...errors import ManagerError


class ProfileFileLock:
    def __init__(self, path: Path, profile_id: str):
        self._path = path
        self._profile_id = profile_id
        self._acquired = False

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self._path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            raise ManagerError("profile_locked", "This profile is in use.", 409) from None
        try:
            metadata = {
                "profile_id": self._profile_id,
                "manager_pid": os.getpid(),
                "manager_created_at": psutil.Process(os.getpid()).create_time(),
            }
            os.write(descriptor, json.dumps(metadata, sort_keys=True).encode("utf-8"))
        finally:
            os.close(descriptor)
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        self._acquired = False
