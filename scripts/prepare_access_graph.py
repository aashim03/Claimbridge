"""Seed an ISOLATED graph for the browser access matrix: two tenants, each with one processed claim.

Uses the fake LLM, so it needs no provider key and makes no network calls. It resets the graph named
by GRAPH (default `claimbridge_access`) and never touches the demo graph.

    GRAPH=claimbridge_access python scripts/prepare_access_graph.py
"""
import os

os.environ.setdefault("GRAPH", "claimbridge_access")
os.environ["LLM_PLATFORM"] = "fake"
os.environ["LLM_MODE"] = "live"

from claimbridge import config, db  # noqa: E402
from claimbridge.agents.intake import Intake  # noqa: E402
from claimbridge.agents.planner import Planner  # noqa: E402
from claimbridge.agents.retrieval import Retrieval  # noqa: E402
from claimbridge.agents.verifier import Verifier  # noqa: E402
from claimbridge.seed.load import reset  # noqa: E402
from claimbridge.tools import coordination as coord  # noqa: E402

assert config.GRAPH != "claimbridge", "refusing to reset the demo graph"
reset()
g = db.connect()
for cid in ("EV-T1-01", "EV-M-A"):                 # TEN-01 (Asha Varma) and TEN-03 (Carmen Ruiz)
    coord.inject(g, [cid])
    for cls in (Intake, Retrieval, Verifier, Planner):
        assert cls(agent_id=f"prep-{cls.role}").step_once(), f"{cid}: {cls.role} did nothing"
print(f"ready: graph {config.GRAPH} with EV-T1-01 (TEN-01) and EV-M-A (TEN-03) at AWAITING_REVIEW")
