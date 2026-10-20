"""A person corrects an unreadable notice and resumes the claim; documents are declared and withdrawn.
Real FalkorDB; fake LLM."""
import json

import pytest
from fastapi.testclient import TestClient

from claimbridge import db, report
from claimbridge.agents.curator import Curator
from claimbridge.agents.intake import Intake
from claimbridge.agents.planner import Planner
from claimbridge.agents.retrieval import Retrieval
from claimbridge.agents.verifier import Verifier
from claimbridge.api import app
from claimbridge.knowledge import load
from claimbridge.seed.load import load_cases_into
from claimbridge.supervisor import approve, record_outcome
from claimbridge.tools import coordination as coord

ALICE, OP = "a" * 40, "o" * 40
CREDS = {ALICE: {"subject": "alice", "role": "tenant", "tenant_id": "TEN-01"}, OP: {"subject": "operator", "role": "admin"}}
BAD_NOTICE = ("Lumen Health Assurance - Notice of claim denial. Claim {id}. Outpatient MRI on 2026-03-02. Denied under "
              "Section 99.9 (Quantum Coverage Rider) of your LumenCare Silver policy. You may appeal this decision within 180 days.")
GOOD_NOTICE = ("Lumen Health Assurance - Notice of claim denial. Claim {id}. Outpatient MRI on 2026-03-02. This service required "
               "prior authorization from the plan, which was not requested. See Section 4.2 (Prior authorization for outpatient MRI) "
               "of your LumenCare Silver policy. You may appeal this decision within 180 days.")


def bearer(t):
    return {"Authorization": f"Bearer {t}", "X-ClaimBridge-Request": "1"}


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "protected")
    monkeypatch.setenv("AUTH_CREDENTIALS_JSON", json.dumps(CREDS))
    return TestClient(app)


def add_claim(g, cid, notice, tenant="TEN-01", evidence=("ITEMIZED_BILL",)):
    load_cases_into(g, load(), [{
        "claim_id": cid, "tenant_id": tenant, "source": "manual", "service": "MRI", "service_date": 20260302,
        "filed_date": 20260320, "filing_lag_days": 18, "amount": None, "in_network": True, "is_emergency": False,
        "enrolled_months": 12, "session_number": None, "notice_text": notice.format(id=cid), "notice_issued": 20260320,
        "evidence": list(evidence)}])
    db.run(g, "MATCH (c:Claim) WHERE c.claim_id <> $c AND c.status IN ['RECEIVED','CLASSIFIED','RETRIEVED','VERIFIED'] "
              "AND c.lease_owner IS NULL SET c.status = 'NEW'", {"c": cid})


def run_agents(g, *classes):
    for cls in classes:
        assert cls(agent_id=f"human-{cls.role}").step_once()


def detail(client, cid, headers=None):
    r = client.get(f"/api/claims/{cid}", headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def events(g, cid):
    return [(e["type"], e["agent"]) for e in coord.timeline(g, cid)]


def test_an_unreadable_notice_waits_for_a_person_who_classifies_it_and_resumes(seeded):
    client, cid = TestClient(app), "HL-CORRECT-1"
    add_claim(seeded, cid, BAD_NOTICE)
    coord.inject(seeded, [cid])
    run_agents(seeded, Intake)
    d = detail(client, cid)
    assert d["claim"]["status"] == "NEEDS_HUMAN"
    assert "not in the governing policy" in d["human_review"]["reason"] and d["human_review"]["step"] == "RECEIVED"
    original = d["notice"]

    r = client.post(f"/api/claims/{cid}/correct", json={"denial_reason": "PREAUTH_MISSING", "reviewer": "pat",
                                                        "note": "Section 99.9 is a typo for 4.2; the scan needed approval."})
    assert r.status_code == 200, r.text
    d = detail(client, cid)
    assert d["claim"]["status"] == "CLASSIFIED" and d["reason"] == "PREAUTH_MISSING"
    assert d["clause"]["clause_id"] == "C-2026-MRI-PREAUTH"                 # routed by the graph, not chosen by the caller
    assert d["notice"] == original                                          # the original notice is never edited
    assert d["corrections"][0]["note"].startswith("Section 99.9") and d["corrections"][0]["reviewer"] == "pat"
    assert ("HUMAN_CORRECTION", "pat") in events(seeded, cid)

    run_agents(seeded, Retrieval, Verifier, Planner)
    d = detail(client, cid)
    assert d["claim"]["status"] == "AWAITING_REVIEW" and d["recommendation"]["disposition"] == "APPEAL_NEEDS_EVIDENCE"
    assert sorted(x["code"] for x in d["requirements"] if not x["satisfied"]) == ["PHYSICIAN_NECESSITY_LETTER", "RETRO_AUTH_REQUEST"]


def test_correcting_again_discards_the_earlier_reading_completely(seeded):
    client, cid = TestClient(app), "HL-CORRECT-2"
    add_claim(seeded, cid, GOOD_NOTICE)
    coord.inject(seeded, [cid])
    run_agents(seeded, Intake, Retrieval, Verifier, Planner)
    before = detail(client, cid)
    assert before["reason"] == "PREAUTH_MISSING" and before["recommendation"]
    assert any("PREAUTH" in c for i in before["recommendation"]["items"] for c in i["cites"])

    assert client.post(f"/api/claims/{cid}/correct", json={"denial_reason": "CODING_ERROR", "note": "The letter was misfiled; it is a coding denial."}).status_code == 200
    mid = detail(client, cid)
    assert mid["claim"]["status"] == "CLASSIFIED"
    assert mid["recommendation"] is None and mid["verdicts"] == []          # nothing from the first reading survives
    run_agents(seeded, Retrieval, Verifier, Planner)
    after = detail(client, cid)
    assert after["reason"] == "CODING_ERROR" and after["recommendation"]["disposition"] == "APPEAL_NEEDS_EVIDENCE"
    assert [x["code"] for x in after["requirements"] if not x["satisfied"]] == ["CORRECTED_CODING_SUBMISSION"]
    cites = {c for i in after["recommendation"]["items"] for c in i["cites"]}
    assert not any("PREAUTH" in c or c in ("RETRO_AUTH_REQUEST", "PHYSICIAN_NECESSITY_LETTER") for c in cites), cites
    assert len(after["corrections"]) == 1 and after["corrections"][0]["previous_reason"] == "PREAUTH_MISSING"


def test_corrections_are_validated_and_restricted(seeded, protected):
    cid = "HL-CORRECT-3"
    add_claim(seeded, cid, BAD_NOTICE, tenant="TEN-01")
    coord.inject(seeded, [cid])
    run_agents(seeded, Intake)
    body = {"denial_reason": "PREAUTH_MISSING", "note": "Section 99.9 is a typo for section 4.2."}
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(ALICE), json=body).status_code == 403   # a policyholder cannot reclassify
    other = "HL-CORRECT-4"
    add_claim(seeded, other, BAD_NOTICE, tenant="TEN-03")
    assert protected.post(f"/api/claims/{other}/correct", headers=bearer(ALICE), json=body).status_code == 404
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json={**body, "denial_reason": "UNKNOWN"}).status_code == 422
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json={**body, "denial_reason": "NOT_A_REASON"}).status_code == 422
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json={**body, "note": "too short"}).status_code == 422
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json={**body, "denial_reason": "WAITING_PERIOD"}).status_code == 422  # no such route for an MRI
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json=body).status_code == 200
    # Mid-flight (the agents are working it again) a claim cannot be corrected; once it awaits review it can, until approved.
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json=body).status_code == 409
    run_agents(seeded, Retrieval, Verifier, Planner)
    assert protected.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json=body).status_code == 200
    assert detail(protected, cid, bearer(OP))["corrections"][-1]["reviewer"] == "operator"                  # identity comes from the credential


def test_declaring_documents_moves_a_claim_from_missing_evidence_to_review_ready_and_keeps_its_history(seeded, protected):
    client, cid = protected, "HL-EVIDENCE-1"
    add_claim(seeded, cid, GOOD_NOTICE, tenant="TEN-01")
    coord.inject(seeded, [cid])
    run_agents(seeded, Intake, Retrieval, Verifier, Planner)
    d = detail(client, cid, bearer(ALICE))
    assert d["recommendation"]["disposition"] == "APPEAL_NEEDS_EVIDENCE"

    first = client.post(f"/api/claims/{cid}/evidence", headers=bearer(ALICE), json={"type": "RETRO_AUTH_REQUEST", "reference": "letter of 3 March"})
    assert first.status_code == 200, first.text
    d = detail(client, cid, bearer(ALICE))
    assert d["claim"]["status"] == "VERIFIED" and d["recommendation"] is None            # the stale checklist is gone at once
    run_agents(seeded, Planner)
    d = detail(client, cid, bearer(ALICE))
    assert d["recommendation"]["disposition"] == "APPEAL_NEEDS_EVIDENCE"
    assert [x["code"] for x in d["requirements"] if not x["satisfied"]] == ["PHYSICIAN_NECESSITY_LETTER"]
    declared = next(x for x in d["evidence"] if x["code"] == "RETRO_AUTH_REQUEST")
    assert declared["declared_by"] == "alice" and declared["verified"] is False and declared["reference"] == "letter of 3 March"

    assert client.post(f"/api/claims/{cid}/evidence", headers=bearer(OP), json={"type": "PHYSICIAN_NECESSITY_LETTER"}).status_code == 200
    run_agents(seeded, Planner)
    d = detail(client, cid, bearer(OP))
    assert d["claim"]["status"] == "AWAITING_REVIEW" and d["recommendation"]["disposition"] == "APPEAL_VIABLE"
    assert all(x["satisfied"] for x in d["requirements"])

    types = [t for t, _ in events(seeded, cid)]
    assert types.count("EVIDENCE_DECLARED") == 2 and types.count("INTAKE_DONE") == 1       # earlier history is still there
    declared_events = [json.loads(e["payload"]) for e in coord.timeline(seeded, cid) if e["type"] == "EVIDENCE_DECLARED"]
    assert declared_events[0]["previous_disposition"] == "APPEAL_NEEDS_EVIDENCE" and declared_events[0]["verified"] is False
    assert declared_events[1]["previous_missing"] == ["PHYSICIAN_NECESSITY_LETTER"]
    seqs = [e["seq"] for e in coord.timeline(seeded, cid)]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    assert "Declared" not in json.dumps(d["recommendation"])                            # advice does not claim documents were verified


def test_evidence_rules_who_what_and_when(seeded, protected):
    client, cid = protected, "HL-EVIDENCE-2"
    add_claim(seeded, cid, GOOD_NOTICE, tenant="TEN-01")
    coord.inject(seeded, [cid])
    run_agents(seeded, Intake, Retrieval, Verifier, Planner)
    other = "HL-EVIDENCE-3"
    add_claim(seeded, other, GOOD_NOTICE, tenant="TEN-03")
    assert client.post(f"/api/claims/{other}/evidence", headers=bearer(ALICE), json={"type": "LAB_REPORT"}).status_code == 404
    assert client.post(f"/api/claims/{cid}/evidence", headers=bearer(ALICE), json={"type": "NOT_A_TYPE"}).status_code == 422
    assert client.post(f"/api/claims/{cid}/evidence", headers=bearer(ALICE), json={"type": "ITEMIZED_BILL"}).status_code == 422   # already on file
    assert client.post(f"/api/claims/{cid}/evidence", headers=bearer(ALICE), json={"type": "LAB_REPORT", "reference": "x" * 201}).status_code == 422

    assert client.post(f"/api/claims/{cid}/evidence", headers=bearer(ALICE), json={"type": "LAB_REPORT"}).status_code == 200
    run_agents(seeded, Planner)
    doc = next(x for x in detail(client, cid, bearer(ALICE))["evidence"] if x["code"] == "LAB_REPORT")["doc_id"]
    assert client.delete(f"/api/claims/{cid}/evidence/{doc}", headers=bearer(ALICE)).status_code == 403     # only an operator withdraws
    assert client.delete(f"/api/claims/{cid}/evidence/{doc}", headers=bearer(OP)).status_code == 200
    d = detail(client, cid, bearer(OP))
    assert "LAB_REPORT" not in [x["code"] for x in d["evidence"]]
    assert d["evidence_withdrawn"][0]["by"] == "operator" and d["evidence_withdrawn"][0]["name"] == "Lab report"
    run_agents(seeded, Planner)
    assert client.delete(f"/api/claims/{cid}/evidence/{doc}", headers=bearer(OP)).status_code == 404            # already withdrawn
    # Once a claim is approved its evidence is frozen.
    assert approve(seeded, cid, "reviewer")
    assert client.post(f"/api/claims/{cid}/evidence", headers=bearer(OP), json={"type": "LAB_REPORT"}).status_code == 409
    assert client.post(f"/api/claims/{cid}/correct", headers=bearer(OP), json={"denial_reason": "CODING_ERROR", "note": "Not allowed any more."}).status_code == 409


def test_a_declared_document_is_still_a_learned_suggestion_not_a_policy_requirement(seeded):
    """EV-M-B2's itemized bill comes from a learned Finding. Declaring it clears the item; provenance stays truthful."""
    client = TestClient(app)
    run_agents_for = lambda cid: (coord.inject(seeded, [cid]), run_agents(seeded, Intake, Retrieval, Verifier, Planner))   # noqa: E731
    run_agents_for("EV-M-A")
    assert approve(seeded, "EV-M-A", "reviewer")
    assert record_outcome(seeded, "EV-M-A", "OVERTURNED", "reviewer", ["EMERGENCY_ATTESTATION", "ITEMIZED_BILL"])
    assert Curator(agent_id="human-curator").step_once()
    run_agents_for("EV-M-B2")
    d = detail(client, "EV-M-B2")
    bill = next(r for r in d["requirements"] if r["code"] == "ITEMIZED_BILL")
    assert not bill["satisfied"] and all(s.startswith("F-L-") for s in bill["sources"])

    assert client.post("/api/claims/EV-M-B2/evidence", json={"type": "ITEMIZED_BILL"}).status_code == 200
    run_agents(seeded, Planner)
    d = detail(client, "EV-M-B2")
    bill = next(r for r in d["requirements"] if r["code"] == "ITEMIZED_BILL")
    assert bill["satisfied"] and all(s.startswith("F-L-") for s in bill["sources"])      # still suggested, never a clause mandate
    assert d["recommendation"]["disposition"] == "APPEAL_VIABLE"
    graph = client.get("/api/claims/EV-M-B2/graph").json()
    assert all(e["origin"] == "learned" for e in graph["edges"] if e["to"] == "ITEMIZED_BILL")
    assert "suggested by a learned precedent" in client.get("/api/claims/EV-M-B2/packet").text
