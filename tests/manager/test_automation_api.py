from __future__ import annotations

import json
import time

from manager_backend.features.proxies.credentials import MemoryCredentialStore


# --- fake browser controller ------------------------------------------------
class FakeController:
    """Stands in for the live recorder/replay so orchestration is deterministic."""

    def __init__(self):
        self._recordings: dict[str, int] = {}
        self.recorded_steps = [{"type": "goto", "url": "https://example.com"}]
        self.behaviors: dict[str, callable] = {}  # profile_id -> fn(ctx)

    def start_recording(self, recording_id, profile_id):
        self._recordings[recording_id] = 0

    def recording_step_count(self, recording_id):
        self._recordings[recording_id] = self._recordings.get(recording_id, 0) + 1
        return self._recordings[recording_id]

    def finish_recording(self, recording_id):
        return list(self.recorded_steps)

    def cancel_recording(self, recording_id):
        return None

    def run_item(self, ctx):
        behavior = self.behaviors.get(ctx.profile_id)
        if behavior is not None:
            behavior(ctx)


def _setup(client):
    store = MemoryCredentialStore()
    client.app.state.credential_store = store
    fake = FakeController()
    client.app.state.automation_controller = fake
    client.app.state.automation_runs._controller = fake
    client.app.state.automation_runs._store = store
    return fake, store


SIMPLE_STEPS = [
    {"type": "goto", "url": "https://example.com"},
    {"type": "click", "selectors": [{"text": "Go"}]},
]
CRED_STEPS = [
    {"type": "goto", "url": "https://example.com/login"},
    {"type": "fill", "selectors": [{"css": "#email"}], "variable": "email"},
    {"type": "fill", "selectors": [{"css": "#password"}], "variable": "password"},
    {"type": "click", "selectors": [{"role": "button"}]},
]
CUSTOM_STEPS = [{"type": "fill", "selectors": [{"css": "#code"}], "variable": "promo"}]


def _profile(client, auth_headers, name):
    return client.post("/api/v1/profiles", headers=auth_headers, json={"name": name}).json()


def _save_template(client, auth_headers, template_id, steps, name="Flow"):
    return client.put(
        f"/api/v1/automations/templates/{template_id}",
        headers=auth_headers,
        json={"name": name, "description": "", "steps": steps},
    )


def _poll_run(client, run_id, until, timeout=8.0):
    deadline = time.time() + timeout
    run = client.get(f"/api/v1/automations/runs/{run_id}").json()
    while time.time() < deadline:
        if until(run):
            return run
        time.sleep(0.05)
        run = client.get(f"/api/v1/automations/runs/{run_id}").json()
    return run


# --- templates --------------------------------------------------------------
def test_template_upsert_list_get_delete(client, auth_headers):
    saved = _save_template(client, auth_headers, "tmpl-1", CRED_STEPS, name="Login")
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["id"] == "tmpl-1"
    assert body["variables"] == ["email", "password"]  # derived from steps
    assert len(body["steps"]) == len(CRED_STEPS)

    assert [t["id"] for t in client.get("/api/v1/automations/templates").json()] == ["tmpl-1"]
    assert client.get("/api/v1/automations/templates/tmpl-1").json()["name"] == "Login"

    assert client.delete("/api/v1/automations/templates/tmpl-1", headers=auth_headers).status_code == 204
    assert client.get("/api/v1/automations/templates").json() == []


# --- credentials ------------------------------------------------------------
def test_credential_import_dedupes_and_never_leaks(client, auth_headers):
    _setup(client)
    imported = client.post(
        "/api/v1/automations/credentials/import",
        headers=auth_headers,
        json={"text": "a@x.com:secret1\nb@x.com:secret2\na@x.com:secret1\n"},
    )
    assert imported.status_code == 200
    summary = imported.json()
    assert summary == {"available": 2, "reserved": 0, "used": 0, "failed": 0, "total": 2}
    assert "secret1" not in imported.text
    assert client.get("/api/v1/automations/credentials").json()["available"] == 2


# --- recordings -------------------------------------------------------------
def test_recording_lifecycle_stop_creates_template(client, auth_headers):
    _setup(client)
    profile = _profile(client, auth_headers, "Recorder")
    started = client.post(
        "/api/v1/automations/recordings",
        headers=auth_headers,
        json={"name": "Signup", "profile_id": profile["id"], "description": ""},
    )
    assert started.status_code == 202, started.text
    recording_id = started.json()["id"]
    assert started.json()["status"] == "recording"

    polled = client.get(f"/api/v1/automations/recordings/{recording_id}").json()
    assert polled["step_count"] >= 1  # controller reports progress

    stopped = client.post(
        f"/api/v1/automations/recordings/{recording_id}/stop", headers=auth_headers
    )
    assert stopped.status_code == 200
    template = stopped.json()
    assert template["name"] == "Signup"
    assert len(template["steps"]) == 1

    after = client.get(f"/api/v1/automations/recordings/{recording_id}").json()
    assert after["status"] == "stopped"
    assert after["template_id"] == template["id"]


# --- run validation ---------------------------------------------------------
def test_run_rejects_duplicate_profiles(client, auth_headers):
    _setup(client)
    profile = _profile(client, auth_headers, "Dup")
    _save_template(client, auth_headers, "t-dup", SIMPLE_STEPS)
    response = client.post(
        "/api/v1/automations/templates/t-dup/runs",
        headers=auth_headers,
        json={
            "assignments": [
                {"profile_id": profile["id"], "variables": {}},
                {"profile_id": profile["id"], "variables": {}},
            ],
            "max_parallel": 1,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_profile"


def test_run_rejects_missing_custom_variable(client, auth_headers):
    _setup(client)
    profile = _profile(client, auth_headers, "NoVar")
    _save_template(client, auth_headers, "t-var", CUSTOM_STEPS)
    response = client.post(
        "/api/v1/automations/templates/t-var/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_variables"


def test_run_requires_a_credential_per_profile(client, auth_headers):
    _setup(client)
    one = _profile(client, auth_headers, "One")
    two = _profile(client, auth_headers, "Two")
    _save_template(client, auth_headers, "t-cred", CRED_STEPS)
    client.post(
        "/api/v1/automations/credentials/import",
        headers=auth_headers,
        json={"text": "only@x.com:pw"},  # a single credential for two profiles
    )
    response = client.post(
        "/api/v1/automations/templates/t-cred/runs",
        headers=auth_headers,
        json={
            "assignments": [
                {"profile_id": one["id"], "variables": {}},
                {"profile_id": two["id"], "variables": {}},
            ],
            "max_parallel": 2,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "credential_unavailable"
    # Reservation rolled back — the credential is still available.
    assert client.get("/api/v1/automations/credentials").json()["available"] == 1


# --- run execution ----------------------------------------------------------
def test_run_completes_every_item(client, auth_headers):
    _setup(client)  # default behavior: complete
    profiles = [_profile(client, auth_headers, f"P{i}")["id"] for i in range(3)]
    _save_template(client, auth_headers, "t-run", SIMPLE_STEPS)
    started = client.post(
        "/api/v1/automations/templates/t-run/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": pid, "variables": {}} for pid in profiles], "max_parallel": 3},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    run = _poll_run(client, run_id, lambda r: r["status"] == "completed")
    assert run["status"] == "completed"
    assert run["completed_count"] == 3
    assert all(item["status"] == "completed" for item in run["items"])


def test_human_gate_blocks_then_continue_resumes(client, auth_headers):
    fake, _ = _setup(client)
    profile = _profile(client, auth_headers, "Gated")
    fake.behaviors[profile["id"]] = lambda ctx: ctx.request_attention("captcha detected")
    _save_template(client, auth_headers, "t-gate", SIMPLE_STEPS)
    run_id = client.post(
        "/api/v1/automations/templates/t-gate/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    ).json()["id"]

    run = _poll_run(client, run_id, lambda r: r["attention_count"] == 1)
    assert run["items"][0]["status"] == "attention"
    assert run["items"][0]["attention_reason"] == "captcha detected"

    resumed = client.post(
        f"/api/v1/automations/runs/{run_id}/profiles/{profile['id']}/continue",
        headers=auth_headers,
    )
    assert resumed.status_code == 200
    run = _poll_run(client, run_id, lambda r: r["status"] == "completed")
    assert run["status"] == "completed"


def test_human_gate_resumes_from_persisted_state_if_wakeup_is_lost(client, auth_headers):
    # A continue that lands between publishing attention and the gate's wait must
    # not be lost. The worker keys off the persisted item status, so even a
    # wakeup event that never arrives still resumes it.
    from sqlalchemy import update

    from manager_backend.models import AutomationRunItem

    fake, _ = _setup(client)
    profile = _profile(client, auth_headers, "Gated")
    fake.behaviors[profile["id"]] = lambda ctx: ctx.request_attention("captcha detected")
    _save_template(client, auth_headers, "t-lost", SIMPLE_STEPS)
    run_id = client.post(
        "/api/v1/automations/templates/t-lost/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    ).json()["id"]
    run = _poll_run(client, run_id, lambda r: r["attention_count"] == 1)
    assert run["items"][0]["status"] == "attention"

    # Simulate a continue whose wakeup event was lost: flip the persisted status to
    # running WITHOUT setting the gate event.
    with client.app.state.session_factory() as session:
        session.execute(
            update(AutomationRunItem)
            .where(AutomationRunItem.run_id == run_id)
            .values(status="running", attention_reason=None)
        )
        session.commit()

    run = _poll_run(client, run_id, lambda r: r["status"] == "completed", timeout=5)
    assert run["status"] == "completed"


def test_retry_resumes_from_last_completed_step(client, auth_headers):
    fake, _ = _setup(client)
    profile = _profile(client, auth_headers, "Flaky")
    attempts = {"n": 0}

    def flaky(ctx):
        if attempts["n"] == 0:
            attempts["n"] = 1
            ctx.set_progress(1)
            raise RuntimeError("network blip")
        assert ctx.start_step == 1  # resumed from the checkpoint
        ctx.set_progress(2)

    fake.behaviors[profile["id"]] = flaky
    _save_template(client, auth_headers, "t-retry", SIMPLE_STEPS)
    run_id = client.post(
        "/api/v1/automations/templates/t-retry/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    ).json()["id"]

    run = _poll_run(client, run_id, lambda r: r["status"] == "failed")
    assert run["items"][0]["status"] == "failed"
    assert run["items"][0]["last_completed_step"] == 1

    client.post(
        f"/api/v1/automations/runs/{run_id}/profiles/{profile['id']}/retry", headers=auth_headers
    )
    run = _poll_run(client, run_id, lambda r: r["status"] == "completed")
    assert run["status"] == "completed"


def test_cancel_holds_credential_until_worker_releases_it(client, auth_headers):
    # A credential must never be returned to the pool while a worker still owns it
    # (mid-replay), or a concurrent run could reserve and use the same login.
    import threading

    fake, _ = _setup(client)
    profile = _profile(client, auth_headers, "Holder")
    _save_template(client, auth_headers, "t-hold", CRED_STEPS)
    client.post(
        "/api/v1/automations/credentials/import",
        headers=auth_headers,
        json={"text": "victim@x.com:s3cr3tPW"},
    )

    entered, release = threading.Event(), threading.Event()

    def hold(ctx):
        entered.set()
        release.wait(5)  # worker keeps ownership of the credential until released

    fake.behaviors[profile["id"]] = hold

    run_id = client.post(
        "/api/v1/automations/templates/t-hold/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    ).json()["id"]
    assert entered.wait(3)  # worker is inside run_item, owns the credential
    assert client.get("/api/v1/automations/credentials").json()["reserved"] == 1

    # Cancel while the worker still owns the credential.
    client.post(f"/api/v1/automations/runs/{run_id}/cancel", headers=auth_headers)
    time.sleep(0.3)
    summary = client.get("/api/v1/automations/credentials").json()
    assert summary["available"] == 0  # NOT released while a worker holds it
    assert summary["reserved"] == 1

    # Once the worker terminates, it releases the credential exactly once.
    release.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        if client.get("/api/v1/automations/credentials").json()["available"] == 1:
            break
        time.sleep(0.05)
    final = client.get("/api/v1/automations/credentials").json()
    assert final["available"] == 1 and final["reserved"] == 0


def test_cancel_token_lets_a_worker_abort_promptly(client, auth_headers):
    # The controller gets a cancellation token so a long replay can stop itself
    # rather than running to completion after a cancel.
    import threading

    fake, _ = _setup(client)
    profile = _profile(client, auth_headers, "Abortable")
    _save_template(client, auth_headers, "t-token", SIMPLE_STEPS)

    entered = threading.Event()

    def wait_for_cancel(ctx):
        entered.set()
        for _ in range(200):  # ~10s ceiling; should break far sooner via the token
            if ctx.is_cancelled():
                return
            time.sleep(0.05)
        raise AssertionError("cancel token never signalled")

    fake.behaviors[profile["id"]] = wait_for_cancel
    run_id = client.post(
        "/api/v1/automations/templates/t-token/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    ).json()["id"]
    assert entered.wait(3)
    client.post(f"/api/v1/automations/runs/{run_id}/cancel", headers=auth_headers)
    # The worker aborts via the token (no release event set) and cancels its item.
    run = _poll_run(client, run_id, lambda r: r["items"][0]["status"] == "cancelled")
    assert run["items"][0]["status"] == "cancelled"


def test_shutdown_awaits_running_workers_before_reporting_clean(client, auth_headers):
    # Shutdown must not report done (and let the engine be disposed) while a worker
    # still owns a DB session / credential — it has to await the worker first.
    import threading

    fake, _ = _setup(client)
    profile = _profile(client, auth_headers, "Slow")
    _save_template(client, auth_headers, "t-sd", SIMPLE_STEPS)

    entered, release = threading.Event(), threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(3)  # worker owns its resources until released

    fake.behaviors[profile["id"]] = slow
    client.post(
        "/api/v1/automations/templates/t-sd/runs",
        headers=auth_headers,
        json={"assignments": [{"profile_id": profile["id"], "variables": {}}], "max_parallel": 1},
    )
    assert entered.wait(3)

    coord = client.app.state.automation_runs
    done, result = threading.Event(), {}

    def do_shutdown():
        result["clean"] = coord.shutdown(timeout=5)
        done.set()

    t = threading.Thread(target=do_shutdown)
    t.start()
    assert not done.wait(0.5)  # blocked: still awaiting the running worker
    release.set()
    assert done.wait(5)  # returns once the worker finishes
    assert result["clean"] is True
    t.join()


# --- startup recovery -------------------------------------------------------
def test_startup_recovery_fails_runs_and_releases_credentials(client, auth_headers):
    from manager_backend.features.automation.coordinator import recover_interrupted_runs
    from manager_backend.models import (
        AutomationCredential,
        AutomationRun,
        AutomationRunItem,
        AutomationTemplate,
    )

    with client.app.state.session_factory() as session:
        template = AutomationTemplate(name="T", description="", steps_json=[])
        session.add(template)
        session.flush()
        run = AutomationRun(template_id=template.id, status="running", total=1)
        session.add(run)
        session.flush()
        session.add(AutomationRunItem(run_id=run.id, profile_id="p1", status="running"))
        session.add(
            AutomationCredential(
                fingerprint_sha256="fp", status="reserved",
                reserved_run_id=run.id, reserved_profile_id="p1", credential_ref="ref",
            )
        )
        session.commit()
        run_id = run.id

    assert recover_interrupted_runs(client.app.state.session_factory) == 1

    with client.app.state.session_factory() as session:
        assert session.get(AutomationRun, run_id).status == "failed"
        item = session.query(AutomationRunItem).filter_by(run_id=run_id).one()
        assert item.status == "failed"
        credential = session.query(AutomationCredential).filter_by(fingerprint_sha256="fp").one()
        assert credential.status == "available"
        assert credential.reserved_run_id is None


# --- factory ----------------------------------------------------------------
def test_factory_creates_profiles(client, auth_headers):
    _setup(client)
    started = client.post(
        "/api/v1/automations/factory/jobs",
        headers=auth_headers,
        json={"quantity": 2, "name_prefix": "Bot", "start_automation": False},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]

    deadline = time.time() + 8.0
    job = client.get(f"/api/v1/automations/factory/jobs/{job_id}").json()
    while time.time() < deadline and job["status"] == "running":
        time.sleep(0.05)
        job = client.get(f"/api/v1/automations/factory/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["created_count"] == 2
    assert all(item["profile_id"] for item in job["items"])
    # The profiles really exist.
    assert client.get("/api/v1/profiles", headers=auth_headers).json()["total"] == 2


# --- F1: no plaintext fill values / secret variables ------------------------
def _put_template(client, auth_headers, tid, steps, name="T"):
    return client.put(
        f"/api/v1/automations/templates/{tid}",
        headers=auth_headers,
        json={"name": name, "description": "", "steps": steps},
    )


def test_fill_step_rejects_literal_value(client, auth_headers):
    r = _put_template(client, auth_headers, "t-literal", [
        {"type": "fill", "selectors": [{"css": "#u"}], "value": "hunter2"}
    ])
    assert r.status_code == 422
    assert "hunter2" not in r.text  # never echo the secret back


def test_fill_step_requires_a_variable(client, auth_headers):
    r = _put_template(client, auth_headers, "t-novar", [
        {"type": "fill", "selectors": [{"css": "#u"}]}
    ])
    assert r.status_code == 422


def test_template_rejects_secret_carrying_variable_names(client, auth_headers):
    for bad in ["pass", "token", "api_key", "client_secret", "access_token", "cookie",
                "authorization", "csrf_token", "user_password", "sessionCookie"]:
        r = _put_template(client, auth_headers, f"t-{abs(hash(bad))}", [
            {"type": "fill", "selectors": [{"css": "#x"}], "variable": bad}
        ])
        assert r.status_code == 422, bad


def test_email_password_credential_and_public_vars_allowed(client, auth_headers):
    r = _put_template(client, auth_headers, "t-ok", [
        {"type": "fill", "selectors": [{"css": "#e"}], "variable": "email"},
        {"type": "fill", "selectors": [{"css": "#p"}], "variable": "password"},
        {"type": "fill", "selectors": [{"css": "#promo"}], "variable": "promo_code"},
    ])
    assert r.status_code == 200, r.text
    assert r.json()["variables"] == ["email", "password", "promo_code"]


def test_run_never_persists_credentials_or_stray_secrets(client, auth_headers):
    _setup(client)
    profile = _profile(client, auth_headers, "SecVars")
    _put_template(client, auth_headers, "t-sec", [
        {"type": "fill", "selectors": [{"css": "#e"}], "variable": "email"},
        {"type": "fill", "selectors": [{"css": "#p"}], "variable": "password"},
        {"type": "fill", "selectors": [{"css": "#promo"}], "variable": "promo_code"},
    ])
    client.post("/api/v1/automations/credentials/import", headers=auth_headers,
                json={"text": "victim@x.com:s3cr3tPW"})

    # A stray secret-carrying key in the assignment is rejected outright.
    bad = client.post("/api/v1/automations/templates/t-sec/runs", headers=auth_headers, json={
        "assignments": [{"profile_id": profile["id"], "variables": {"promo_code": "SAVE10", "token": "leak"}}],
        "max_parallel": 1})
    assert bad.status_code in (400, 422)
    assert "leak" not in bad.text

    run = client.post("/api/v1/automations/templates/t-sec/runs", headers=auth_headers, json={
        "assignments": [{"profile_id": profile["id"], "variables": {"promo_code": "SAVE10"}}],
        "max_parallel": 1}).json()
    _poll_run(client, run["id"], lambda r: r["status"] in ("completed", "failed"))

    # Adversarial DB dump: no credential value, no stray secret, only the public var.
    from manager_backend.models import AutomationRunItem, AutomationTemplate
    with client.app.state.session_factory() as s:
        for item in s.query(AutomationRunItem).all():
            dumped = json.dumps(item.variables_json or {})
            assert "s3cr3tPW" not in dumped and "victim@x.com" not in dumped
            assert "email" not in (item.variables_json or {})
            assert "password" not in (item.variables_json or {})
            assert (item.variables_json or {}).get("promo_code") == "SAVE10"
        for t in s.query(AutomationTemplate).all():
            assert "hunter2" not in json.dumps(t.steps_json or [])
