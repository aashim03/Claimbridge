"""Policy Verifier: RETRIEVED -> VERIFIED.

Decides, in Cypher, which precedents apply and which do not (and why), then checks
the clause-level gates. It saves a checkpoint between the two, so a replacement
verifier resumes without redoing the applicability pass.
"""
from claimbridge.agents.base import Context, StepResult, Worker
from claimbridge.tools import applicability
from claimbridge.tools import coordination as coord


class Verifier(Worker):
    role = "verifier"
    input_state = "RETRIEVED"
    output_state = "VERIFIED"

    def work(self, ctx: Context) -> StepResult:
        g, cid, me = ctx.g, ctx.claim_id, ctx.me
        cp = ctx.checkpoint or {}
        if cp.get("verdicts_done"):
            verdicts = cp["verdicts"]
            ctx.notes.append(f"resumed from checkpoint written by {cp.get('_agent_id')}; "
                             "skipped applicability pass")
        else:
            verdicts = applicability.check_applicability(g, cid, me)
            coord.save_checkpoint(g, cid, me, self.input_state,
                                  {"verdicts_done": True, "verdicts": verdicts})
            self.pause()
            self.maybe_crash("after_verdicts")

        gate = applicability.gates(g, cid, me) or {}
        payload = {
            "accepted": [v["finding_id"] for v in verdicts if v["code"] == "ACCEPTED"],
            "rejected": [{"finding_id": v["finding_id"], "code": v["code"],
                          "learned_on": v["learned_on_clause"], "governing": v["governing_clause"],
                          "contradicted_by": v["contradicted_by"]}
                         for v in verdicts if v["code"] != "ACCEPTED"],
            "gates": gate.get("gates", []),
            "resumed": bool(cp.get("verdicts_done")),
            "notes": ctx.notes,
        }
        return StepResult(payload=payload, checkpoint=payload)
