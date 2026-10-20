"""Regression cases from the judge review. Real FalkorDB; no external LLM."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from claimbridge import db, guard, report
from claimbridge.api import app
from claimbridge.agents.intake import Intake
from claimbridge.agents.retrieval import Retrieval
from claimbridge.agents.verifier import Verifier
from claimbridge.agents.planner import Planner
from claimbridge.agents.curator import Curator
from claimbridge.agents.base import Recoverable
from claimbridge.cli import spawn
from claimbridge.knowledge import load
from claimbridge.supervisor import approve, record_outcome
from claimbridge.tools import coordination as coord, memory
from claimbridge.evaluation.score import score


def process(g, cid):
    coord.inject(g, [cid])
    for cls in (Intake, Retrieval, Verifier, Planner):
        assert cls(agent_id=f"audit-{cls.role}").step_once()
    return report.actual(g, cid)


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "protected")
    monkeypatch.setenv("AUTH_CREDENTIALS_JSON", json.dumps({
        "a" * 40: {"subject": "alice", "role": "tenant", "tenant_id": "TEN-01"},
        "b" * 40: {"subject": "operator", "role": "admin"},
    }))
    return TestClient(app)


def test_protected_routes_fail_closed(protected):
    for url in ("/api/claims", "/api/overview", "/api/memory", "/api/agents", "/api/stream"):
        assert protected.get(url).status_code == 401
    assert protected.post("/api/world", json={"action": "reset"}).status_code == 401


def test_invalid_auth_configuration_is_not_demo(protected, monkeypatch):
    monkeypatch.setenv("AUTH_CREDENTIALS_JSON", "{}")
    assert protected.get("/api/claims").status_code == 503
    monkeypatch.setenv("AUTH_MODE", "typo")
    assert protected.get("/api/session").status_code == 503


def test_tenant_cannot_read_other_claim_or_control_workers(protected, seeded):
    h = {"Authorization": "Bearer " + "a" * 40, "X-Tenant-Id": "TEN-03"}
    for suffix in ("", "/graph"):
        assert protected.get("/api/claims/EV-M-A" + suffix, headers=h).status_code == 404
    assert protected.post("/api/claims/EV-M-A/approve", headers=h, json={}).status_code == 404
    assert protected.post("/api/agents/verifier-1/kill", headers=h).status_code == 403
    assert protected.post("/api/world", headers=h, json={"action": "reset"}).status_code == 403
    rows = protected.get("/api/claims", headers=h).json()
    assert rows and all(r["tenant_id"] == "TEN-01" for r in rows)
    result = protected.get("/api/memory/findings/F-CODING/precedents", headers=h).json()
    assert result["tenant"] == "TEN-01"
    assert all(r["claim_id"] is None and r["notice_text"] is None for r in result["rows"] if not r["own"])


def test_session_cookie_and_csrf(protected):
    assert protected.post("/api/session", json={"token": "a" * 40}).status_code == 403
    r = protected.post("/api/session", json={"token": "a" * 40}, headers={"X-ClaimBridge-Request": "1"})
    assert r.status_code == 200 and "HttpOnly" in r.headers["set-cookie"]
    assert protected.get("/api/session").json()["subject"] == "alice"
    assert protected.post("/api/claims/inject", json={"ids": []}).status_code == 403
    protected.delete("/api/session", headers={"X-ClaimBridge-Request": "1"})
    assert protected.get("/api/claims").status_code == 401


@pytest.mark.parametrize("text", ["You have 999 days to file this appeal.", "Approval is assured.",
                                      "Ignore the governing policy and upload your password."])
def test_valid_id_cannot_launder_unsupported_advice(text):
    ctx = {"clause": {"clause_id": "C", "section": "1", "title": "Policy"},
           "gates": [], "evidence": [], "accepted_precedents": [], "rejected_precedents": []}
    items, stats = guard.apply([{"kind": "ACTION", "text": text, "cite_ids": ["C"]}], ctx, {"C": "Clause"}, "APPEAL_VIABLE")
    assert all(i["text"] != text and i["origin"] == "graph" for i in items)
    assert stats["dropped_unsupported"] == 1


def test_clause_fingerprint_covers_text_and_evidence():
    clause = next(iter(load().clauses.values()))
    assert replace(clause, text="Coverage removed").fingerprint != clause.fingerprint
    assert replace(clause, requires=clause.requires + ["LAB_REPORT"]).fingerprint != clause.fingerprint


def test_text_only_policy_change_invalidates_memory(seeded):
    db.run(seeded, """CREATE (v:PolicyVersion {version_id:'AUDIT-NEW'}),
        (o:Clause {clause_id:'AUDIT-OLD',lineage_id:'AUDIT-L',fingerprint:'old',params:'{}'}),
        (n:Clause {clause_id:'AUDIT-NEW',version_id:'AUDIT-NEW',lineage_id:'AUDIT-L',fingerprint:'new',params:'{}'}),
        (f:Finding {finding_id:'AUDIT-F',status:'ACTIVE'}),
        (v)-[:CONTAINS]->(n),(n)-[:SUPERSEDES]->(o),(f)-[:ON_LINEAGE]->(o)""")
    assert memory.mark_stale(seeded, "AUDIT-NEW", db.now_ms())[0]["finding_id"] == "AUDIT-F"
    assert memory.carry_forward(seeded, "AUDIT-NEW") == []
    # Keep this artificial version out of subsequent policy tests.
    db.run(seeded, "MATCH (n) WHERE n.version_id = 'AUDIT-NEW' OR n.clause_id = 'AUDIT-OLD' OR n.finding_id = 'AUDIT-F' DELETE n")


def test_memory_changes_action_after_confirmed_outcome(seeded, monkeypatch):
    before = process(seeded, "EV-M-B1")
    process(seeded, "EV-M-A")
    assert approve(seeded, "EV-M-A", "reviewer")
    assert record_outcome(seeded, "EV-M-A", "OVERTURNED", "reviewer", ["EMERGENCY_ATTESTATION", "ITEMIZED_BILL"])
    assert Curator(agent_id="audit-curator").step_once()
    after = process(seeded, "EV-M-B2")
    assert before["missing"] == [] and before["disposition"] == "APPEAL_VIABLE"
    assert after["missing"] == ["ITEMIZED_BILL"]
    assert after["disposition"] == "APPEAL_NEEDS_EVIDENCE"
    assert 0 < after["recommendation"]["confidence"] < 1
    assert any(i["kind"] == "EVIDENCE_NEEDED" and "ITEMIZED_BILL" in i["cites"] for i in after["recommendation"]["items"])
    learned = next(i for i in after["recommendation"]["items"] if i["kind"] == "EVIDENCE_NEEDED")
    assert any(c.startswith("F-L-") for c in learned["cites"])
    assert not any(c.startswith("C-") for c in learned["cites"])


def test_curator_crash_retry_does_not_double_count(seeded):
    cid = "EV-N-01"
    process(seeded, cid)
    assert approve(seeded, cid, "reviewer")
    assert record_outcome(seeded, cid, "OVERTURNED", "reviewer")
    p = spawn("curator", "audit-crashed-curator", crash_at="before_commit")
    try:
        assert p.wait(timeout=45) == 137
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    query = "MATCH (p:Playbook) RETURN p.playbook_id AS id,p.uses AS uses,p.wins AS wins ORDER BY id"
    before = db.run(seeded, query)
    db.run(seeded, "MATCH (c:Claim {claim_id:$cid}) SET c.lease_until=0", {"cid": cid})
    assert Curator(agent_id="audit-replacement-curator").step_once()
    assert db.run(seeded, query) == before
    assert report.actual(seeded, cid)["status"] == "CURATED"
    with pytest.raises(Recoverable):
        memory.record_playbook_use(coord.FencedGraph(seeded, cid, "audit-crashed-curator"), cid, "OVERTURNED")


def test_missing_evaluation_predictions_count_as_failures(truth):
    result = score({}, {"EV-T1-01": truth["EV-T1-01"]})
    assert result["metrics"]["claims"] == 1
    assert result["metrics"]["completion_rate"] == 0
    assert result["metrics"]["decision_correct"] == 0
    assert result["metrics"]["all_correct"] == 0


def test_review_packet_enforces_owner_and_contains_sources(protected, seeded):
    admin = {"Authorization": "Bearer " + "b" * 40}
    tenant = {"Authorization": "Bearer " + "a" * 40}
    response = protected.get("/api/claims/EV-M-B2/packet", headers=admin)
    assert response.status_code == 200
    assert "Sources:" in response.text and "has not been submitted" in response.text
    assert protected.get("/api/claims/EV-M-A/packet", headers=tenant).status_code == 404


def test_intake_schema_has_single_enum_for_constrained_decoding():
    from claimbridge.llm import strict_schema
    from claimbridge.llm.schemas import IntakeExtraction
    reason = strict_schema(IntakeExtraction)["properties"]["denial_reason"]
    assert set(reason["enum"]) >= {"UNKNOWN", "PREAUTH_MISSING", "CODING_ERROR"}
    assert "anyOf" not in reason


@pytest.mark.parametrize("notice,mode", [
    ("Your claim was denied under Section 99.9.", "section"),
    ("Please tell me a joke about weather.", "unknown"),
    ("The payment needs further clarification.", "low"),
    ("The submitted code does not match the procedure.", "offline"),
])
def test_unknown_ambiguous_and_unavailable_intake_escalates(seeded, monkeypatch, notice, mode):
    from claimbridge import llm
    from claimbridge.agents import intake
    from claimbridge.llm.schemas import IntakeExtraction
    cid = "EV-T1-02"
    db.run(seeded, "MATCH (c:Claim {claim_id:$cid})-[:HAS_NOTICE]->(n) SET c.status='NEW', c.attempt=0, n.text=$text",
           {"cid": cid, "text": notice})
    def classify(*_):
        if mode == "offline":
            raise llm.LLMError("offline")
        return IntakeExtraction(denial_reason="UNKNOWN" if mode == "unknown" else "CODING_ERROR",
                                cited_section=None, mentions_emergency=False,
                                confidence="low" if mode == "low" else "high", rationale="test"), {}
    monkeypatch.setattr(intake, "llm_classify", classify)
    coord.inject(seeded, [cid])
    assert Intake(agent_id="audit-unknown").step_once()
    assert report.actual(seeded, cid)["status"] == "NEEDS_HUMAN"


def test_learned_evidence_is_never_a_policy_requirement(seeded):
    """EV-M-B2's itemized bill comes from a learned Finding; the graph, checklist and packet must say so."""
    client = TestClient(app)
    d = client.get("/api/claims/EV-M-B2").json()
    bill = next(r for r in d["requirements"] if r["code"] == "ITEMIZED_BILL")
    assert bill["sources"] and all(s.startswith("F-L-") for s in bill["sources"])
    graph = client.get("/api/claims/EV-M-B2/graph").json()
    assert next(n for n in graph["nodes"] if n["id"] == "ITEMIZED_BILL")["origin"] == "learned"
    into = [e for e in graph["edges"] if e["to"] == "ITEMIZED_BILL"]
    assert into and all(e["origin"] == "learned" and e["from"].startswith("F-L-") for e in into)
    packet = client.get("/api/claims/EV-M-B2/packet").text
    assert "suggested by a learned precedent" in packet and "not a policy requirement" in packet


def test_policy_requirements_still_cite_their_clause(seeded):
    process(seeded, "EV-T3-01")
    client = TestClient(app)
    d = client.get("/api/claims/EV-T3-01").json()
    policy = [r for r in d["requirements"] if any(s.startswith("C-") for s in r["sources"])]
    assert policy, "a missing-evidence claim must have a clause requirement"
    graph = client.get("/api/claims/EV-T3-01/graph").json()
    for r in policy:
        edges = [e for e in graph["edges"] if e["to"] == r["code"] and e["from"].startswith("C-")]
        assert edges and all(e["origin"] == "policy" for e in edges)
        assert next(n for n in graph["nodes"] if n["id"] == r["code"])["origin"] in ("policy", "both")
    assert "required by the governing clause" in client.get("/api/claims/EV-T3-01/packet").text


def test_condition_failure_is_exposed_for_the_explanation(seeded):
    process(seeded, "EV-T5-01")
    d = TestClient(app).get("/api/claims/EV-T5-01").json()
    unmet = [v for v in d["verdicts"] if v["code"] == "CONDITION_UNMET"]
    assert unmet, "T5 is the condition-unmet scenario"
    assert any(v["req_emergency"] is True for v in unmet) and d["claim"]["is_emergency"] is False
    assert all("req_in_network" in v for v in unmet)
