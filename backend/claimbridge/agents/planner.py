"""Resolution Planner: VERIFIED -> AWAITING_REVIEW.

The disposition and evidence gap come from the graph. LLM drafts are audited;
published items always use graph templates and reviewed playbook steps. A valid
citation ID alone cannot establish that arbitrary model prose is supported.
"""
import json
import logging

from claimbridge import config, db, guard, llm
from claimbridge.agents.base import Context, StepResult, Worker
from claimbridge.llm.schemas import PlanDraft
from claimbridge.tools import coordination as coord
from claimbridge.tools import recommendation as recs

log = logging.getLogger("claimbridge.planner")

SYSTEM = """You are a caseworker assistant helping a policyholder respond to a denied health-insurance claim.
You receive the facts the claims graph established (CONTEXT) and the IDs you may cite (ALLOWED_IDS).

Write a short, practical plan:
- one EVIDENCE_NEEDED item per missing evidence type, citing its evidence code and the governing clause;
- ACTION items for the next steps (use the playbook steps of accepted precedents when present, citing their step IDs);
- one REJECTED_PRECEDENT item per rejected precedent, explaining in plain words why it does not apply, citing its ID
  (and the governing clause for VERSION_DRIFT);
- WARNING items for gates (no appeal basis) or uncertainty.

Rules: use only facts from CONTEXT; every item must cite at least one ID from ALLOWED_IDS; never cite anything else;
never promise approval or payment; the disposition is already decided, do not change it."""


def decide_disposition(ctx: dict) -> str:
    if ctx["gates"]:
        return "NO_BASIS_ESCALATE"
    if any(not e["satisfied"] for e in ctx["evidence"]):
        return "APPEAL_NEEDS_EVIDENCE"
    return "APPEAL_VIABLE"


def assess(ctx: dict, disposition: str, intake: dict | None) -> tuple[float, list[str], str]:
    acc, rej = ctx["accepted_precedents"], ctx["rejected_precedents"]
    notes = []
    if not acc:
        notes.append("No verified precedent applies to this claim.")
    for a in acc:
        if (a["support"] or 0) < 3:
            notes.append(f"Only {a['support']} verified case(s) support {a['finding_id']}.")
    for r in rej:
        if r["code"] == "CONTRADICTED":
            notes.append(f"{r['finding_id']} was contradicted by later verified cases "
                         f"({', '.join(r['contradicted_by'])}).")
        if r["code"] == "VERSION_DRIFT":
            notes.append(f"{r['finding_id']} was learned under {r['learned_on']}; "
                         f"{r['governing']} governs this claim.")
    if intake and intake.get("needs_llm_review"):
        notes.append("The denial reason was inferred with low confidence; confirm it against the notice.")
    # The support score is a smoothed count of recorded outcomes, not an approval probability. When there is
    # nothing to count it is not 0%: it is absent, and `support_state` says why so no screen shows a number.
    if disposition == "NO_BASIS_ESCALATE":
        confidence, state = 0.0, "NO_APPEAL_BASIS"      # a policy gate is not evidence of appeal success
    elif acc:
        confidence, state = max(a["confidence"] or 0 for a in acc), "RECORDED_OUTCOMES"
    else:
        confidence, state = 0.0, "NO_PRECEDENT"
    return round(confidence, 3), notes, state


def draft_plan(ctx: dict, allowed: dict, disposition: str) -> tuple[list[dict], str, dict]:
    user = (f"CONTEXT:\n{json.dumps({**ctx, 'disposition': disposition}, indent=1)}\n"
            f"ALLOWED_IDS:\n{json.dumps(sorted(allowed))}\n"
            "Write the plan.")
    task = "planner_nomem" if config.NO_MEMORY else "planner"
    draft, meta = llm.complete(task, SYSTEM, user, PlanDraft, effort="medium")
    items = [i.model_dump() for i in draft.items]
    return items, draft.summary, {"platform": meta.platform, "model": meta.model, "cached": meta.cached}


class Planner(Worker):
    role = "planner"
    input_state = "VERIFIED"
    output_state = "AWAITING_REVIEW"

    def work(self, ctx: Context) -> StepResult:
        g, cid, me = ctx.g, ctx.claim_id, ctx.me
        pctx = recs.planner_context(g, cid)
        disposition = decide_disposition(pctx)
        allowed = recs.allowed_ids(pctx)
        intake = coord.load_checkpoint(g, cid, "RECEIVED")

        cp = ctx.checkpoint or {}
        if not config.PLANNER_DRAFT_AUDIT:
            draft_items, summary, llm_meta = [], "", {"mode": "graph_templates"}
        elif cp.get("draft_done"):
            draft_items, summary, llm_meta = cp["items"], cp["summary"], cp["llm"]
            ctx.notes.append("resumed from checkpoint; skipped the LLM call")
        else:
            try:
                draft_items, summary, llm_meta = draft_plan(pctx, allowed, disposition)
            except llm.LLMError as e:
                log.warning("%s: LLM unavailable (%s); deterministic plan", cid, e)
                draft_items, summary, llm_meta = [], "", {"error": str(e)}
            coord.save_checkpoint(g, cid, me, self.input_state,
                                  {"draft_done": True, "items": draft_items, "summary": summary, "llm": llm_meta})

        items, stats = guard.apply(draft_items, pctx, allowed, disposition)
        summary = (guard.no_basis_summary(pctx) if disposition == "NO_BASIS_ESCALATE" else
                   {"APPEAL_NEEDS_EVIDENCE": "A caseworker should review the missing evidence before preparing an appeal.",
                    "APPEAL_VIABLE": "The modeled evidence requirements are met. A caseworker should review the appeal."}[disposition])
        confidence, uncertainty, support_state = assess(pctx, disposition, intake)
        for n, it in enumerate(items):
            it["order"], it["item_id"] = n + 1, f"REC-{cid}-{n + 1}"
        rec = {"disposition": disposition, "summary": summary, "confidence": confidence,
               "support_state": support_state, "uncertainty": uncertainty, "created_at": db.now_ms(),
               "llm_platform": llm_meta.get("platform"), "llm_model": llm_meta.get("model"),
               "guard_dropped": (stats["dropped_uncited"] + stats["dropped_unknown_id"] + stats["dropped_promise"]
                                 + stats["dropped_moot"] + stats["dropped_unsupported"]),
               "guard_added": stats["added_required"]}
        recs.write_recommendation(g, cid, me, rec, items, allowed)
        payload = {"disposition": disposition, "confidence": confidence, "items": len(items),
                   "guard": stats, "llm": llm_meta, "notes": ctx.notes}
        return StepResult(payload=payload, checkpoint={"disposition": disposition, "guard": stats})
