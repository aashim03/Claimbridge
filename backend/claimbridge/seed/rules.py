"""Independent ground-truth rule engine.

Plain Python over the YAML-derived objects. It never runs Cypher, so the
evaluation is not the graph checking itself. See docs/07-evaluation.md §6.
"""
from claimbridge.knowledge import Knowledge, load


def gates_for(case: dict, clause, kn: Knowledge) -> list[str]:
    """Clause-level reasons why no appeal basis exists."""
    gates = []
    if clause.no_basis:
        gates.append("EXCLUSION_NO_BASIS")
    if clause.req_emergency and not case.get("is_emergency", False):
        gates.append("EMERGENCY_REQUIRED")
    if case["reason"] == "TIMELY_FILING" and case["filing_lag_days"] > clause.params["limit_days"]:
        gates.append("FILED_LATE")
    if case["reason"] == "WAITING_PERIOD" and case.get("enrolled_months", 0) < clause.params["wait_months"]:
        gates.append("WAITING_NOT_MET")
    return gates


def expected(case: dict, kn: Knowledge | None = None) -> dict:
    kn = kn or load()
    version = kn.version_for(case["service_date"])
    clause = kn.route(case["reason"], case["service"], version)
    if clause is None:
        raise ValueError(f"{case['claim_id']}: no clause routes {case['reason']}/{case['service']} in {version}")

    applicable, rejected = [], []
    required = set(clause.requires)
    for f in kn.findings:
        if f.reason != case["reason"]:
            continue
        if f.lineage != clause.lineage_id:
            rejected.append({"finding_id": f.finding_id, "code": "LINEAGE_MISMATCH"})
        elif version not in f.valid_in:
            rejected.append({"finding_id": f.finding_id, "code": "VERSION_DRIFT"})
        elif f.status == "CONTRADICTED":
            rejected.append({"finding_id": f.finding_id, "code": "CONTRADICTED"})
        elif f.req_emergency is not None and f.req_emergency != case.get("is_emergency", False):
            rejected.append({"finding_id": f.finding_id, "code": "CONDITION_UNMET"})
        elif f.req_in_network is not None and f.req_in_network != case.get("in_network", True):
            rejected.append({"finding_id": f.finding_id, "code": "CONDITION_UNMET"})
        else:
            applicable.append(f.finding_id)
            required |= set(f.needs)

    gates = gates_for(case, clause, kn)
    missing = sorted(required - set(case["evidence"]))
    if gates:
        disposition = "NO_BASIS_ESCALATE"
    elif missing:
        disposition = "APPEAL_NEEDS_EVIDENCE"
    else:
        disposition = "APPEAL_VIABLE"

    return {
        "claim_id": case["claim_id"],
        "trap": case.get("trap"),
        "tenant_id": case["tenant_id"],
        "expected_reason": case["reason"],
        "expected_version": version,
        "expected_lineage": clause.lineage_id,
        "expected_clause": clause.clause_id,
        "expected_required_evidence": sorted(required),
        "expected_missing_evidence": missing,
        "expected_applicable_findings": sorted(applicable),
        "expected_rejected_findings": sorted(rejected, key=lambda r: r["finding_id"]),
        "expected_gates": gates,
        "expected_disposition": disposition,
        "tenant_probe": case.get("tenant_probe"),
        "note": case.get("note"),
    }
