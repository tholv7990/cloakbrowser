"""The desktop sidecar entrypoint binds loopback on the shell-chosen port."""

from __future__ import annotations

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
