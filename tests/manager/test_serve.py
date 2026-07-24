"""The desktop sidecar entrypoint binds loopback on the shell-chosen port."""

from __future__ import annotations

import sys

import uvicorn

from manager_backend import serve
from manager_backend.main import create_app


def test_serve_binds_loopback_on_the_env_port(monkeypatch):
    captured: dict = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("PLASMA_PORT", "54321")

    serve.main()

    assert captured["app"] is create_app  # factory
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 54321
    assert captured["factory"] is True


def test_serve_defaults_to_8765(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.delenv("PLASMA_PORT", raising=False)
    serve.main()
    assert captured["port"] == 8765


def test_serve_routes_frozen_google_seed_args_to_the_seed(monkeypatch):
    """Frozen onefile re-runs serve.py for `-m ...google_seed <dir>`; main() must
    dispatch it to the seed, never start a second uvicorn server."""
    from manager_backend.features.runtime import google_seed

    seeded: dict = {}
    monkeypatch.setattr(google_seed, "seed", lambda d: seeded.setdefault("dir", d))
    ran_server = {"called": False}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran_server.update(called=True))
    monkeypatch.setattr(
        sys,
        "argv",
        ["plasma-backend.exe", "-m",
         "manager_backend.features.runtime.google_seed", r"C:\some\profile"],
    )

    serve.main()

    assert seeded["dir"] == r"C:\some\profile"
    assert ran_server["called"] is False
