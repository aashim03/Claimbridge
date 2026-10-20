"""Retrieval: CLASSIFIED -> RETRIEVED.

Collects candidate precedents (Findings). The graph proposes by structure, and
vector similarity of denial notices adds recall. Nothing is accepted here.
"""
from claimbridge import config
from claimbridge.agents.base import Context, StepResult, Worker
from claimbridge.tools import retrieval


class Retrieval(Worker):
    role = "retrieval"
    input_state = "CLASSIFIED"
    output_state = "RETRIEVED"

    def work(self, ctx: Context) -> StepResult:
        g, cid, me = ctx.g, ctx.claim_id, ctx.me
        cands: dict[str, dict] = {}
        if config.NO_MEMORY:  # evaluation ablation: semantic memory hidden
            retrieval.write_candidates(g, cid, [], me)
            return StepResult(payload={"candidates": [], "written": 0, "no_memory": True})
        for c in retrieval.graph_candidates(g, cid):
            cands[c["finding_id"]] = {"finding_id": c["finding_id"], "source": "graph",
                                      "score": 1.0 if c["same_lineage"] else 0.5}
        for c in retrieval.vector_candidates(g, cid):
            if c["finding_id"] in cands:
                cands[c["finding_id"]]["source"] = "graph+vector"
            elif len(cands) < config.MAX_CANDIDATES:
                cands[c["finding_id"]] = {"finding_id": c["finding_id"], "source": "vector",
                                          "score": round(1.0 - c["distance"], 4)}
        chosen = list(cands.values())
        n = retrieval.write_candidates(g, cid, chosen, me)
        payload = {"candidates": chosen, "written": n}
        return StepResult(payload=payload, checkpoint={"candidates": [c["finding_id"] for c in chosen]})
