"""A claim entered by hand gets the seeded graph shape and runs through the same agents."""
from fastapi.testclient import TestClient

from claimbridge import db
from claimbridge.api import app
from claimbridge.cli import run_pipeline

client = TestClient(app)

BASE = {"tenant_id": "TEN-03", "service": "MRI", "service_date": "2026-03-02", "filed_date": "2026-03-20",
        "evidence": ["ITEMIZED_BILL"]}


def test_rejects_bad_input(seeded):
    assert client.post("/api/claims/new", json={**BASE, "notice": "x" * 60, "tenant_id": "REAL-PERSON"}).status_code == 422
    assert client.post("/api/claims/new", json={**BASE, "notice": "x" * 60, "filed_date": "2026-02-01"}).status_code == 422
    assert client.post("/api/claims/new", json={**BASE, "notice": "too short"}).status_code == 422
    assert client.post("/api/claims/new", json={**BASE, "notice": "x" * 60, "evidence": ["NOPE"]}).status_code == 422


def test_manual_claim_runs_end_to_end(seeded):
    sample = client.post("/api/claims/sample-notice",
                         json={"service": "MRI", "reason": "CODING_ERROR", "service_date": BASE["service_date"]}).json()
    assert sample["cites"] and "(new)" in sample["text"]

    r = client.post("/api/claims/new", json={**BASE, "notice": sample["text"]})
    assert r.status_code == 200, r.text
    cid = r.json()["claim_id"]
    assert cid.startswith("NC-") and r.json()["filed"]

    shape = db.one(seeded, """
        MATCH (t:Tenant)-[:FILED]->(c:Claim {claim_id: $cid})-[:FOR_SERVICE]->(:ServiceCategory {code: 'MRI'})
        MATCH (c)-[:HAS_NOTICE]->(n:DenialNotice)
        MATCH (c)-[:HAS_EVIDENCE]->(:Evidence)-[:OF_TYPE]->(:EvidenceType {code: 'ITEMIZED_BILL'})
        RETURN t.tenant_id AS t, c.filing_lag_days AS lag, c.source AS src, n.text CONTAINS $cid AS named""", {"cid": cid})
    assert shape == {"t": "TEN-03", "lag": 18, "src": "manual", "named": True}

    run_pipeline([cid], quiet=True)
    d = client.get(f"/api/claims/{cid}").json()
    assert d["claim"]["status"] == "AWAITING_REVIEW"
    assert d["reason"] == "CODING_ERROR"
    assert d["version"]["label"] == "2026"
    assert d["recommendation"]["items"]
    assert any(c["claim_id"] == cid for c in client.get("/api/claims").json())
