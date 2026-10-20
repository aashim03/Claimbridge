"""Intake refuses to trust a section number that the rest of the notice contradicts. Real FalkorDB; fake LLM."""
import pytest

from claimbridge import db, report
from claimbridge.agents.intake import Intake
from claimbridge.knowledge import load
from claimbridge.seed.load import load_cases_into
from claimbridge.tools import coordination as coord

HEAD = "Lumen Health Assurance - Notice of claim denial. Claim {cid}. Service: Outpatient MRI. Date of service: 2026-03-02."
TAIL = " You may appeal this decision within 180 days of this notice."

NOTICES = {
    # (notice text, expected status, a phrase the escalation reason must contain)
    "control-consistent": (HEAD + " This service required prior authorization from the plan, which was not requested."
                           " See Section 4.2 (Prior authorization for outpatient MRI) of your LumenCare Silver policy." + TAIL,
                           "CLASSIFIED", None),
    "section-contradicts-wording": (HEAD + " The billing code submitted does not match the procedure performed."
                                    " See Section 4.2 (Prior authorization for outpatient MRI) of your LumenCare Silver policy." + TAIL,
                                    "NEEDS_HUMAN", "implies PREAUTH_MISSING"),
    "wording-contradicts-section": (HEAD + " This service required prior authorization from the plan, which was not requested."
                                    " See Section 6.3 (Out-of-network services) of your LumenCare Silver policy." + TAIL,
                                    "NEEDS_HUMAN", "implies OUT_OF_NETWORK"),
    "another-insurer": ("Acme Mutual Insurance - Denial of benefits. Claim {cid}. Under Section 4.2 of your Acme Gold plan we "
                        "cannot pay: the billing code submitted does not match the procedure performed.",
                        "NEEDS_HUMAN", "does not name this insurer"),
    "section-for-another-service": (HEAD + " Bariatric surgery is excluded. See Section 7.4 (Bariatric surgery) of your "
                                    "LumenCare Silver policy." + TAIL, "NEEDS_HUMAN", "does not govern this service"),
    "section-does-not-exist": (HEAD + " Denied under Section 99.9 (Quantum Coverage Rider)." + TAIL,
                               "NEEDS_HUMAN", "not in the governing policy"),
}


@pytest.mark.parametrize("name", list(NOTICES))
def test_intake_checks_a_cited_section_against_the_rest_of_the_notice(seeded, name):
    text, expected, phrase = NOTICES[name]
    cid = "GEN-" + name.upper().replace("-", "")[:12]
    load_cases_into(seeded, load(), [{
        "claim_id": cid, "tenant_id": "TEN-02", "source": "generalization", "service": "MRI",
        "service_date": 20260302, "filed_date": 20260320, "filing_lag_days": 18, "amount": None, "in_network": True,
        "is_emergency": False, "enrolled_months": 12, "session_number": None,
        "notice_text": text.format(cid=cid), "notice_issued": 20260320, "evidence": ["ITEMIZED_BILL"]}])
    db.run(seeded, "MATCH (c:Claim) WHERE c.claim_id <> $c AND c.status = 'RECEIVED' SET c.status = 'NEW'", {"c": cid})
    coord.inject(seeded, [cid])
    assert Intake(agent_id="consistency-intake").step_once()
    status = report.actual(seeded, cid)["status"]
    assert status == expected, (name, status)
    if phrase:
        events = [e for e in coord.timeline(seeded, cid) if e["type"] == "NEEDS_HUMAN"]
        assert events and phrase in events[-1]["payload"], events
