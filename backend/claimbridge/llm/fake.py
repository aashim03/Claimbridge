"""Deterministic stand-in for an LLM (LLM_PLATFORM=fake). Used by tests and offline demos.

It builds outputs from the structured context the agents already pass in the prompt,
so the rest of the pipeline (validation, citation guard, graph writes) runs for real.
"""
import json
import re

from pydantic import BaseModel

from claimbridge.llm.schemas import BaselineAnswer, BaselineItem, IntakeExtraction, PlanDraft, PlanItem

KEYWORDS = [
    ("TIMELY_FILING", ("filing deadline", "timely filing", "too late")),
    ("DUPLICATE_CLAIM", ("duplicate", "already processed")),
    ("CODING_ERROR", ("code", "billed")),
    ("WAITING_PERIOD", ("waiting period", "continuous enrollment", "not yet eligible")),
    ("OUT_OF_NETWORK", ("network", "non-participating", "this provider")),
    ("INCOMPLETE_DOCS", ("documentation", "records", "not received")),
    ("PREAUTH_MISSING", ("authorization", "pre-approval", "precertification", "approval")),
    ("EXCLUDED_SERVICE", ("not a covered", "excluded", "exclusion", "outside what")),
    ("NOT_MED_NECESSARY", ("medically necessary", "criteria")),
]


class FakeProvider:
    def complete(self, model, system, user, schema: type[BaseModel], effort, max_tokens=None):
        if schema is IntakeExtraction:
            return self._intake(user), (None, None)
        if schema is PlanDraft:
            return self._plan(user), (None, None)
        if schema is BaselineAnswer:
            return self._baseline(user), (None, None)
        raise NotImplementedError(schema.__name__)

    def _baseline(self, user: str) -> BaselineAnswer:
        """Naive RAG behaviour: reuse the first retrieved past case, as a weak retriever would."""
        ext = self._intake(user)
        year = re.search(r"Service date: (\d{4})", user)
        cases = re.findall(r"\[(CS-(HC-\d+))\]", user)
        passages = re.findall(r"\[((?:CL|CS)-[^\]]+)\]", user)
        return BaselineAnswer(
            denial_reason=ext.denial_reason,
            policy_version=f"V{year.group(1)}" if year else "V2026",
            cited_section=ext.cited_section, required_evidence=[], missing_evidence=[],
            precedent_case_ids=[cases[0][1]] if cases else [],
            disposition="APPEAL_VIABLE", summary="naive",
            items=[BaselineItem(kind="ACTION", text="Appeal.", cite_ids=passages[:1])])

    def _intake(self, user: str) -> IntakeExtraction:
        low = user.lower()
        reason = next((r for r, kws in KEYWORDS if any(k in low for k in kws)), "NOT_MED_NECESSARY")
        m = re.search(r"Section\s+(\d+\.\d+)", user)
        return IntakeExtraction(denial_reason=reason, cited_section=m.group(1) if m else None,
                                mentions_emergency="emergency" in low, confidence="medium",
                                rationale="keyword match (fake provider)")

    def _plan(self, user: str) -> PlanDraft:
        ctx = json.loads(user.split("CONTEXT:", 1)[1].split("ALLOWED_IDS:", 1)[0])
        items = []
        for e in ctx["evidence"]:
            if not e["satisfied"]:
                items.append(PlanItem(kind="EVIDENCE_NEEDED", text=f"Obtain the {e['name']}.",
                                      cite_ids=[e["code"], ctx["clause"]["clause_id"]]))
        for f in ctx["accepted_precedents"]:
            for s in f["playbook_steps"]:
                items.append(PlanItem(kind="ACTION", text=s["action"], cite_ids=[s["step_id"], f["finding_id"]]))
        for r in ctx["rejected_precedents"]:
            items.append(PlanItem(kind="REJECTED_PRECEDENT",
                                  text=f"Do not rely on {r['finding_id']} ({r['code']}).",
                                  cite_ids=[r["finding_id"]]))
        return PlanDraft(summary=f"Disposition: {ctx['disposition']}.", items=items)
