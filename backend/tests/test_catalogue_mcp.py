"""The tool catalogue and the MCP server that exposes it.

Run just these:  uv run pytest tests/test_catalogue_mcp.py -q
Every call goes through a real MCP client connected in-process to the real server and real FalkorDB.
"""
import asyncio
import json

import pytest
from mcp import Client

from claimbridge import catalogue, db
from claimbridge.catalogue import Scope
from claimbridge.mcp_server import build_server
from claimbridge.tools import applicability, retrieval, versions

CLAIM, FINDING, CLAUSE = "EV-T1-01", "F-MRI-REFERRAL", "C-2026-MRI-PREAUTH"
EXPECTED = {"get_claim", "select_version", "find_candidates", "check_applicability", "evidence_gap",
            "explain_path", "what_rests_on_clause", "policy_blast_radius"}


@pytest.fixture(scope="module")
def world(seeded, truth):
    g = seeded
    for cid, t in truth.items():
        versions.select_version(g, cid)
        versions.write_classification(g, cid, t["expected_reason"], t["expected_clause"])
        retrieval.write_candidates(g, cid, [{"finding_id": c["finding_id"], "source": "graph", "score": 1.0}
                                            for c in retrieval.graph_candidates(g, cid)])
        applicability.check_applicability(g, cid)
        applicability.gates(g, cid)
    owner = db.one(g, "MATCH (c:Claim {claim_id: $c}) RETURN c.tenant_id AS t", {"c": CLAIM})["t"]
    other = db.one(g, "MATCH (t:Tenant) WHERE t.tenant_id <> $o RETURN t.tenant_id AS t ORDER BY t", {"o": owner})["t"]
    return {"g": g, "graph": g.name, "owner": owner, "other": other}


def ask(world, tenant, name, args):
    """One tool call through an MCP client connected to a server that runs as `tenant`."""
    async def go():
        async with Client(build_server(world["graph"], tenant)) as client:
            return await client.call_tool(name, args)
    return asyncio.run(go())


def listing(world, tenant):
    async def go():
        async with Client(build_server(world["graph"], tenant)) as client:
            return (await client.list_tools()).tools
    return asyncio.run(go())


def test_lists_every_tool_with_a_schema(world):
    tools = listing(world, world["owner"])
    assert {t.name for t in tools} == EXPECTED
    for t in tools:
        assert t.description
        assert t.input_schema["type"] == "object" and t.input_schema["additionalProperties"] is False
        assert t.input_schema["required"] == list(t.input_schema["properties"])
        assert t.annotations.read_only_hint is True


def test_there_is_no_write_tool(world):
    names = {t.name for t in listing(world, world["owner"])}
    assert not any(w in n for n in names for w in ("write", "set_", "delete", "approve", "update", "create"))


def test_every_tool_answers_on_a_seeded_claim(world):
    calls = {"get_claim": {"claim_id": CLAIM}, "select_version": {"claim_id": CLAIM},
             "find_candidates": {"claim_id": CLAIM}, "evidence_gap": {"claim_id": CLAIM},
             "check_applicability": {"claim_id": CLAIM, "finding_id": FINDING},
             "explain_path": {"claim_id": CLAIM, "finding_id": FINDING},
             "what_rests_on_clause": {"clause_id": CLAUSE}, "policy_blast_radius": {"clause_id": CLAUSE}}
    assert set(calls) == EXPECTED
    for name, args in calls.items():
        r = ask(world, world["owner"], name, args)
        assert not r.is_error, (name, r.structured_content)
        body = r.structured_content
        assert body["ok"] and body["tool"] == name and body["ids"], name
        assert json.loads(r.content[0].text) == body


def test_the_2025_precedent_is_rejected_for_the_2026_clause(world):
    v = ask(world, world["owner"], "check_applicability", {"claim_id": CLAIM, "finding_id": FINDING}).structured_content["data"]
    assert v["verdict"] == "VERSION_DRIFT" and v["broken_hop"] == "version" and v["agrees_with_verifier"]
    path = ask(world, world["owner"], "explain_path", {"claim_id": CLAIM, "finding_id": FINDING}).structured_content["data"]
    assert [h["check"] for h in path["hops"] if h["first_broken"]] == ["version"]
    assert "C-2026-MRI-PREAUTH" in catalogue.ids_in(path)
    ver = ask(world, world["owner"], "select_version", {"claim_id": CLAIM}).structured_content["data"]
    assert ver["version_in_force"] == "V2026" and ver["pinned_matches"]


def test_unknown_ids_are_clean_errors(world):
    for name, args in [("get_claim", {"claim_id": "NOPE-1"}), ("explain_path", {"claim_id": CLAIM, "finding_id": "F-NOPE"}),
                       ("what_rests_on_clause", {"clause_id": "C-NOPE"}), ("policy_blast_radius", {"clause_id": "C-NOPE"})]:
        r = ask(world, world["owner"], name, args)
        assert r.is_error
        body = r.structured_content
        assert body["ok"] is False and body["error"]["code"] == "NOT_FOUND" and body["ids"] == []
        assert "Traceback" not in r.content[0].text and "File " not in r.content[0].text


def test_bad_arguments_and_unknown_tools_are_rejected(world):
    cases = [("get_claim", {}), ("get_claim", {"claim_id": "x", "tenant_id": "TEN-02"}),
             ("get_claim", {"claim_id": "a b; MATCH (n) DETACH DELETE n"}), ("get_claim", {"claim_id": 7}),
             ("delete_claim", {"claim_id": CLAIM})]
    for name, args in cases:
        body = catalogue.call(world["g"], Scope(world["owner"]), name, args)
        assert body["ok"] is False and body["error"]["code"] in ("BAD_ARGUMENTS", "UNKNOWN_TOOL"), (name, args)
    assert ask(world, world["owner"], "get_claim", {"claim_id": "x", "tenant_id": "TEN-02"}).is_error


def test_tenant_cannot_read_another_tenants_claim(world):
    # The server runs as `other`; the claim belongs to `owner`.
    for name, args in [("get_claim", {"claim_id": CLAIM}), ("select_version", {"claim_id": CLAIM}),
                       ("find_candidates", {"claim_id": CLAIM}), ("evidence_gap", {"claim_id": CLAIM}),
                       ("check_applicability", {"claim_id": CLAIM, "finding_id": FINDING}),
                       ("explain_path", {"claim_id": CLAIM, "finding_id": FINDING})]:
        r = ask(world, world["other"], name, args)
        assert r.is_error and r.structured_content["error"]["code"] == "NOT_FOUND", name
        assert set(r.structured_content) == {"ok", "tool", "error", "ids"}      # no data at all
    same = ask(world, world["other"], "get_claim", {"claim_id": CLAIM}).structured_content["error"]["message"]
    nothing = ask(world, world["other"], "get_claim", {"claim_id": "EV-DOES-NOT-EXIST"}).structured_content["error"]["message"]
    assert same.replace(CLAIM, "X") == nothing.replace("EV-DOES-NOT-EXIST", "X")     # indistinguishable from a missing claim


def _claim_ids(data):
    rows = data.get("claims", data.get("claims_you_can_see"))
    return {c["claim_id"] if isinstance(c, dict) else c for c in rows}


def test_clause_tools_do_not_name_other_tenants_claims(world):
    for tool in ("what_rests_on_clause", "policy_blast_radius"):
        as_owner = _claim_ids(ask(world, world["owner"], tool, {"clause_id": CLAUSE}).structured_content["data"])
        as_other = _claim_ids(ask(world, world["other"], tool, {"clause_id": CLAUSE}).structured_content["data"])
        assert CLAIM in as_owner, tool
        assert CLAIM not in as_other, tool


def test_calls_never_change_the_graph(world):
    def size():
        return (db.one(world["g"], "MATCH (n) RETURN count(n) AS n")["n"],
                db.one(world["g"], "MATCH ()-[r]->() RETURN count(r) AS n")["n"],
                db.one(world["g"], "MATCH ()-[k:CONSIDERED]->() RETURN count(k) AS n, collect(k.verdict)[0] AS v"))
    before = size()
    values = {"claim_id": CLAIM, "finding_id": FINDING, "clause_id": CLAUSE}
    for spec in catalogue.specs():
        ask(world, world["owner"], spec["name"], {p: values[p] for p in spec["input_schema"]["properties"]})
    assert size() == before


def test_the_cli_command_serves_over_stdio(world):
    """The exact command a Claude Desktop config runs, as a real subprocess speaking MCP on stdin/stdout."""
    import os
    import sys

    from mcp import StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "claimbridge.cli", "mcp"],
                                   env={**os.environ, "CLAIMBRIDGE_MCP_GRAPH": world["graph"],
                                        "CLAIMBRIDGE_MCP_TENANT": world["owner"]})

    async def go():
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            got = await client.call_tool("get_claim", {"claim_id": CLAIM})
            return tools, got

    tools, got = asyncio.run(go())
    assert {t.name for t in tools} == EXPECTED
    assert got.structured_content["data"]["claim_id"] == CLAIM


def test_an_unreachable_database_is_a_clean_error(world, monkeypatch):
    from claimbridge import config
    monkeypatch.setattr(config, "FALKORDB_PORT", 1)           # nothing listens there
    r = ask(world, world["owner"], "get_claim", {"claim_id": CLAIM})
    assert r.is_error and r.structured_content["error"]["code"] in ("INTERNAL", "UNAVAILABLE")
    assert "Traceback" not in r.content[0].text and "Connection" not in r.content[0].text
