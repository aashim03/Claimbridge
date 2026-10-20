"""Credential, tenant and event-stream boundaries over real HTTP. Real FalkorDB; no LLM.

Sharing policy this matrix enforces (docs/06-api-and-ui.md):
  PRIVATE to a tenant: its claims, graphs, packets, notices, events, evidence, mutations.
  SHARED with every signed-in user: the abstract memory (Findings, playbooks, policy versions) and
  aggregate counts of it. A tenant sees only an outcome and a count for other tenants' cases.
  OPERATOR only: worker metadata, agent commands, world resets, recording outcomes."""
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from claimbridge import auth
from claimbridge.api import app
from claimbridge.tools import coordination as coord

from test_hardening import process

A, B, OP = "a" * 40, "b" * 40, "o" * 40          # alice (TEN-01), bob (TEN-03), operator
CREDS = {A: {"subject": "alice", "role": "tenant", "tenant_id": "TEN-01"},
         B: {"subject": "bob", "role": "tenant", "tenant_id": "TEN-03"},
         OP: {"subject": "operator", "role": "admin"}}
ALICE_CLAIM, BOB_CLAIM = "EV-T1-01", "EV-M-A"    # TEN-01's and TEN-03's claims in the synthetic data


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "protected")
    monkeypatch.setenv("AUTH_CREDENTIALS_JSON", json.dumps(CREDS))
    return TestClient(app)


@pytest.fixture(scope="module")
def processed(seeded):
    process(seeded, ALICE_CLAIM)
    process(seeded, BOB_CLAIM)


def test_every_endpoint_denies_the_other_tenants_claim(protected, processed):
    h = bearer(A)
    for method, path, body in [
        ("get", f"/api/claims/{BOB_CLAIM}", None),
        ("get", f"/api/claims/{BOB_CLAIM}/graph", None),
        ("get", f"/api/claims/{BOB_CLAIM}/packet", None),
        ("post", f"/api/claims/{BOB_CLAIM}/approve", {}),
        ("post", f"/api/claims/{BOB_CLAIM}/outcome", {"outcome": "OVERTURNED"}),
        ("post", "/api/claims/inject", {"ids": [BOB_CLAIM]}),
    ]:
        r = getattr(protected, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code in (403, 404), f"{method} {path} -> {r.status_code}"
        assert "Carmen" not in r.text and BOB_CLAIM not in r.text.replace(path, "")
    # Not even a new claim in the other tenant's name.
    new = {"tenant_id": "TEN-03", "service": "MRI", "service_date": "2026-03-02", "filed_date": "2026-03-20",
           "notice": "x" * 60, "evidence": []}
    assert protected.post("/api/claims/new", headers=h, json=new).status_code in (403, 404)
    # Own claim works.
    for suffix in ("", "/graph", "/packet"):
        assert protected.get(f"/api/claims/{ALICE_CLAIM}{suffix}", headers=h).status_code == 200


def test_tenants_see_only_their_own_claims_and_counts(protected, processed):
    alice = protected.get("/api/claims", headers=bearer(A)).json()
    bob = protected.get("/api/claims", headers=bearer(B)).json()
    assert alice and bob
    assert {c["tenant_id"] for c in alice} == {"TEN-01"} and {c["tenant_id"] for c in bob} == {"TEN-03"}
    assert not {c["claim_id"] for c in alice} & {c["claim_id"] for c in bob}
    assert sum(protected.get("/api/overview", headers=bearer(A)).json()["statuses"].values()) == len(alice)


def test_shared_memory_exposes_no_other_tenants_case_details(protected, processed):
    memory = protected.get("/api/memory", headers=bearer(A)).text
    for secret in ("Carmen", "Asha", "TEN-0", BOB_CLAIM, "Notice of claim denial"):
        assert secret not in memory, f"shared memory leaks {secret!r}"
    overview = protected.get("/api/overview", headers=bearer(A)).text
    assert BOB_CLAIM not in overview and "Carmen" not in overview and "world_job" in overview


def test_x_tenant_id_cannot_change_identity(protected, processed):
    rows = {}
    for tenant in ("TEN-01", "TEN-03", "TEN-07", "nonsense"):
        r = protected.get("/api/memory/findings/F-CODING/precedents", headers={**bearer(A), "X-Tenant-Id": tenant}).json()
        assert r["tenant"] == "TEN-01"
        rows[tenant] = r["rows"]
    assert rows["TEN-01"] == rows["TEN-03"] == rows["TEN-07"] == rows["nonsense"]


def test_operator_only_actions_are_enforced_on_the_server(protected, processed):
    tenant = bearer(A)
    assert protected.get("/api/agents", headers=tenant).status_code == 403
    assert protected.post("/api/agents/start", headers=tenant, json={"role": "intake"}).status_code == 403
    assert protected.post("/api/agents/verifier-1/kill", headers=tenant).status_code == 403
    assert protected.post("/api/world", headers=tenant, json={"action": "publish"}).status_code == 403
    assert protected.post(f"/api/claims/{ALICE_CLAIM}/outcome", headers=tenant, json={"outcome": "OVERTURNED"}).status_code == 403
    assert protected.get("/api/agents", headers=bearer(OP)).status_code == 200


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer nope"}, {"Authorization": "Bearer "}, {"Authorization": "Basic " + "a" * 40},
    {"Cookie": "claimbridge_session=nope"}, {"Authorization": "bearer " + "a" * 40},
])
def test_missing_or_invalid_credentials_are_rejected(protected, headers):
    for path in ("/api/claims", "/api/memory", "/api/overview", "/api/stream", f"/api/claims/{ALICE_CLAIM}/packet"):
        assert protected.get(path, headers=headers).status_code == 401, path


@pytest.mark.parametrize("config", [
    "not json", "[]", "{}", json.dumps({"short": {"subject": "x", "role": "admin"}}),
    json.dumps({"s" * 40: {"subject": "x", "role": "root"}}),
    json.dumps({"s" * 40: {"subject": "x", "role": "tenant"}}),
    json.dumps({"s" * 40: {"role": "admin"}}),
])
def test_malformed_protected_configuration_fails_closed(protected, monkeypatch, config):
    monkeypatch.setenv("AUTH_CREDENTIALS_JSON", config)
    for path in ("/api/claims", "/api/memory", "/api/stream"):
        assert protected.get(path, headers=bearer("s" * 40)).status_code == 503, path


def test_cookie_mutations_need_the_same_origin_header(protected, processed):
    cookie = {"Cookie": f"claimbridge_session={A}"}
    assert protected.post(f"/api/claims/{ALICE_CLAIM}/approve", headers=cookie, json={}).status_code == 403
    csrf = {**cookie, "X-ClaimBridge-Request": "1"}
    assert protected.post(f"/api/claims/{ALICE_CLAIM}/approve", headers=csrf, json={}).status_code in (200, 409)
    assert protected.get("/api/claims", headers=cookie).status_code == 200          # reads need no header


def test_session_endpoint_never_reveals_other_credentials(protected):
    assert protected.get("/api/session").json() == {"mode": "protected", "authenticated": False}
    r = protected.get("/api/session", headers=bearer(A)).json()
    assert r == {"mode": "protected", "authenticated": True, "subject": "alice", "role": "tenant", "tenant_id": "TEN-01"}
    assert A not in json.dumps(r)


# ------------------------------------------------------------------ the live event stream

@pytest.fixture(scope="module")
def server(seeded):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/api/session", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)


def read_stream(url, headers, until, timeout=15):
    """Collect SSE lines until `until(lines)` or the server ends the stream."""
    lines, deadline = [], time.time() + timeout
    with httpx.stream("GET", url + "/api/stream", headers=headers, timeout=timeout) as r:
        assert r.status_code == 200, r.status_code
        for line in r.iter_lines():
            lines.append(line)
            if until(lines) or time.time() > deadline:
                break
    return lines


def test_a_tenant_stream_carries_only_its_own_tick(protected, server, processed):
    lines = read_stream(server, bearer(A), lambda ls: any(l.startswith("data:") for l in ls))
    payload = json.loads(next(l for l in lines if l.startswith("data:"))[5:])
    assert set(payload) == {"ev"}                                   # a timestamp, no ids, no worker metadata


def test_an_open_stream_ends_when_its_credential_is_revoked(protected, server, monkeypatch):
    ended = {}

    def revoke_soon():
        time.sleep(1.5)
        monkeypatch.setenv("AUTH_CREDENTIALS_JSON", json.dumps({k: v for k, v in CREDS.items() if k != A}))

    threading.Thread(target=revoke_soon, daemon=True).start()
    t0 = time.time()
    lines = []
    with httpx.stream("GET", server + "/api/stream", headers=bearer(A), timeout=20) as r:
        for line in r.iter_lines():
            lines.append(line)
        ended["after"] = time.time() - t0                            # the loop ended by itself
    assert "event: auth" in lines
    assert 1.5 <= ended["after"] < 8, ended


def test_an_open_stream_ends_when_the_session_lifetime_is_over(protected, server, monkeypatch):
    monkeypatch.setattr(auth, "SESSION_SECONDS", 1)
    lines = read_stream(server, bearer(OP), lambda ls: "event: auth" in ls, timeout=10)
    assert "event: auth" in lines


def test_the_stream_is_reached_with_the_session_cookie_too(protected, server):
    lines = read_stream(server, {"Cookie": f"claimbridge_session={A}"}, lambda ls: any(l.startswith("data:") for l in ls))
    assert any(l.startswith("event: tick") for l in lines)


def test_session_cookie_is_secure_over_https_deployments(protected, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "1")
    r = protected.post("/api/session", json={"token": A}, headers={"X-ClaimBridge-Request": "1"})
    cookie = r.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    monkeypatch.setenv("COOKIE_SECURE", "0")
    plain = protected.post("/api/session", json={"token": A}, headers={"X-ClaimBridge-Request": "1"}).headers["set-cookie"]
    assert "Secure" not in plain                                    # local http development keeps working
