"""Publish recommendations from graph facts and reviewed playbook steps only."""
import re

PROMISE = re.compile(r"\b(guarantee[sd]?|will (definitely |certainly )?be (approved|paid|overturned|covered))\b",
                     re.I)


GATE_TEXT = {
    "EXCLUSION_NO_BASIS": "the governing clause excludes this service",
    "EMERGENCY_REQUIRED": "out-of-network care is covered only in emergencies, and this was not one",
    "FILED_LATE": "the claim was filed after the limit in force on the service date",
    "WAITING_NOT_MET": "the member had not completed the waiting period in force on the service date",
}


def no_basis_summary(ctx: dict) -> str:
    reasons = "; ".join(GATE_TEXT.get(g, g.replace("_", " ").lower()) for g in ctx["gates"])
    return (f"No appeal basis under §{ctx['clause']['section']} {ctx['clause']['title']}: {reasons}. "
            "Escalate to a human reviewer rather than gathering evidence.")


def canonical_items(ctx: dict, disposition: str) -> list[dict]:
    """Construct published advice from graph facts; ID membership is not entailment."""
    items = []
    cid = ctx["clause"]["clause_id"]
    def add(kind, text, cites):
        item = {"kind": kind, "text": text, "cite_ids": list(dict.fromkeys(cites)), "origin": "graph"}
        if item not in items:
            items.append(item)
    if disposition == "NO_BASIS_ESCALATE":
        add("WARNING", no_basis_summary(ctx), [cid])
        add("ACTION", "Escalate to a human reviewer; do not treat this recommendation as a final coverage decision.", [cid])
    else:
        for e in ctx["evidence"]:
            if not e["satisfied"]:
                sources = e.get("sources", [cid])
                learned_only = cid not in sources
                wording = (f"A similar resolved case used the {e['name'].lower()}; ask a caseworker whether to include it."
                           if learned_only else f"Obtain and submit the {e['name'].lower()}.")
                add("EVIDENCE_NEEDED", wording, [e["code"], *sources])
        add("ACTION", "Ask a caseworker to review the evidence and governing clause before submitting an appeal.", [cid])
        for f in ctx.get("accepted_precedents", []):
            for step in f.get("playbook_steps", []):
                add("ACTION", step["action"], [step["step_id"], f["finding_id"]])
    for r in ctx["rejected_precedents"]:
        why = {"VERSION_DRIFT": f"it was learned under {r['learned_on']}, but {r['governing']} governs this claim",
               "LINEAGE_MISMATCH": "it concerns a different policy clause",
               "CONTRADICTED": "later verified outcomes contradict it",
               "CONDITION_UNMET": "the required conditions are not met"}.get(r["code"], r["code"])
        cites = [r["finding_id"]]
        if r["code"] == "VERSION_DRIFT" and r["governing"]:
            cites.append(r["governing"])
        add("REJECTED_PRECEDENT", f"Do not rely on precedent {r['finding_id']}: {why}.", cites)
    return items


def apply(draft_items: list[dict], ctx: dict, allowed: dict[str, str], disposition: str) -> tuple[list[dict], dict]:
    canonical = canonical_items(ctx, disposition)
    stats = dict.fromkeys(("dropped_uncited", "dropped_unknown_id", "dropped_promise",
                          "dropped_moot", "dropped_unsupported", "kept_llm"), 0)
    stats["drafted"] = len(draft_items)
    matched = set()
    for it in draft_items:
        cites = set(it.get("cite_ids", []))
        if disposition == "NO_BASIS_ESCALATE" and it["kind"] in ("ACTION", "EVIDENCE_NEEDED"):
            stats["dropped_moot"] += 1
        elif not cites:
            stats["dropped_uncited"] += 1
        elif not cites <= allowed.keys():
            stats["dropped_unknown_id"] += 1
        elif PROMISE.search(it["text"]):
            stats["dropped_promise"] += 1
        else:
            hits = [i for i, c in enumerate(canonical) if c["kind"] == it["kind"]
                    and c["text"] == it["text"] and set(c["cite_ids"]) == cites]
            if hits:
                matched.add(hits[0])
            else:
                stats["dropped_unsupported"] += 1
    stats["matched_graph_statements"] = len(matched)
    stats["added_required"] = len(canonical) - len(matched)
    return [i for i in canonical if set(i["cite_ids"]) <= allowed.keys()], stats
