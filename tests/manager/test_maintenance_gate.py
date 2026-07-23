"""Unit tests for the process-wide maintenance gate (F2)."""
from __future__ import annotations

import threading
import time

import pytest

from manager_backend.errors import ManagerError
from manager_backend.maintenance import MaintenanceGate


def test_operation_allowed_when_idle():
    gate = MaintenanceGate()
    with gate.operation():
        pass  # no raise


def test_operation_rejected_during_exclusive():
    gate = MaintenanceGate()
    with gate.exclusive():
        with pytest.raises(ManagerError) as exc:
            with gate.operation():
                pass
    assert exc.value.status_code == 409
    assert exc.value.code == "maintenance_in_progress"


def test_second_exclusive_rejected_while_one_is_held():
    gate = MaintenanceGate()
    with gate.exclusive():
        with pytest.raises(ManagerError) as exc:
            with gate.exclusive():
                pass
    assert exc.value.status_code == 409


def test_exclusive_waits_for_active_operations_to_drain():
    gate = MaintenanceGate()
    started, release, entered = threading.Event(), threading.Event(), threading.Event()

    def op():
        with gate.operation():
            started.set()
            release.wait(3)

    def restore():
        with gate.exclusive(drain_timeout=3):
            entered.set()

    t = threading.Thread(target=op)
    t.start()
    assert started.wait(2)
    r = threading.Thread(target=restore)
    r.start()
    assert not entered.wait(0.3)  # blocked while the operation is active
    release.set()
    assert entered.wait(2)  # proceeds once it drains
    t.join()
    r.join()


def test_exclusive_times_out_if_operations_never_drain():
    gate = MaintenanceGate()
    release = threading.Event()

    def op():
        with gate.operation():
            release.wait(3)

    t = threading.Thread(target=op)
    t.start()
    time.sleep(0.1)
    with pytest.raises(ManagerError) as exc:
        with gate.exclusive(drain_timeout=0.3):
            pass
    assert exc.value.status_code == 409
    assert exc.value.code == "maintenance_busy"
    release.set()
    t.join()
    # gate is usable again after a failed acquisition
    with gate.operation():
        pass
