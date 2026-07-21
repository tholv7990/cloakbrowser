from __future__ import annotations

import os
from pathlib import Path

from ...errors import ManagerError


class ProfileFileLock:
    def __init__(self, path: Path):
        self._path = path
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
            os.write(descriptor, str(os.getpid()).encode("ascii"))
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
