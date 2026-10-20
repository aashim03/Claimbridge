"""Blast radius of a policy clause, computed with FalkorDB graph algorithms (read-only on the live graph).

"If this clause changes, what is affected, how many hops away, and which lineages carry the most memory?"

Why a projection. `algo.BFS` follows outgoing edges only, and the dependency runs the other way
(claim -> finding -> clause). So the dependency edges are copied into a throwaway scratch graph that
sits next to the live one, in both directions under two relationship types, and the algorithms run
there. The live graph is only ever read; the scratch graph is deleted in a `finally`.

Which relationship types carry the dependency (and which do not):

    SUPERSEDES    clause versions of one lineage         both ways (a change touches the whole lineage)
    ON_LINEAGE    finding -> the clause it was learned on
    CONSIDERED    claim -> finding it weighed            live claims only, not REASON_MISMATCH
    DERIVED_FROM  finding -> the verified outcome it rests on
    VALID_IN is left out on purpose: it points at PolicyVersion hubs shared by every finding, so
    walking it would connect unrelated lineages and flood the reach.

Algorithms (both are in the pinned FalkorDB 4.22.1, see `CALL dbms.procedures()`):

    algo.BFS(clause, depth, 'IMPACTS')      who is reached from the clause, and at which hop
    algo.pageRank('N', 'DEPENDS_ON')        how much of the graph depends on each clause

What this gives that a plain COUNT does not: the hop distance of every affected item, and a rank
that counts indirect dependence (a claim leans on a finding that leans on a clause). It does not
change which claims are affected: `trace.clause_impact` reaches the same set with variable-length
Cypher. On this small synthetic graph the ranking mostly follows the counts.
"""
import uuid

from falkordb import FalkorDB

from claimbridge import config, db

MAX_DEPTH = 6
DESCRIPTION = ("If a policy clause changes, what is affected? Runs the FalkorDB graph algorithms BFS (everything reached from the "
               "clause, with its hop distance) and PageRank (how much memory depends on the clause's lineage).")


def _projection(live) -> dict:
    """The dependency edges of the live graph, as plain rows (one read each)."""
    return {
        "clauses": db.run(live, "MATCH (c:Clause) RETURN c.clause_id AS id, c.lineage_id AS lineage, c.version_id AS version, "
                                "c.section AS section, c.title AS title"),
        "supersedes": db.run(live, "MATCH (n:Clause)-[:SUPERSEDES]->(o:Clause) RETURN n.clause_id AS a, o.clause_id AS b"),
        "findings": db.run(live, "MATCH (f:Finding)-[:ON_LINEAGE]->(c:Clause) RETURN f.finding_id AS id, f.status AS status, "
                                 "c.clause_id AS clause"),
        "claims": db.run(live, """MATCH (cl:Claim)-[k:CONSIDERED]->(f:Finding)
                                  WHERE cl.source <> 'historical' AND k.reason_code <> 'REASON_MISMATCH'
                                  RETURN DISTINCT cl.claim_id AS id, cl.tenant_id AS tenant, cl.status AS status, f.finding_id AS finding"""),
        "outcomes": db.run(live, "MATCH (f:Finding)-[:DERIVED_FROM]->(r:Resolution) RETURN f.finding_id AS finding, r.resolution_id AS id"),
    }


def _build(scratch, p: dict):
    nodes = [{"id": c["id"], "kind": "clause", "lineage": c["lineage"]} for c in p["clauses"]]
    nodes += [{"id": f["id"], "kind": "finding", "status": f["status"]} for f in p["findings"]]
    nodes += [{"id": c["id"], "kind": "claim", "tenant": c["tenant"]} for c in {c["id"]: c for c in p["claims"]}.values()]
    nodes += [{"id": r["id"], "kind": "outcome"} for r in {r["id"]: r for r in p["outcomes"]}.values()]
    scratch.query("UNWIND $rows AS r CREATE (:N {id: r.id, kind: r.kind, lineage: r.lineage, status: r.status, tenant: r.tenant})",
                  {"rows": nodes})
    scratch.query("CREATE INDEX FOR (n:N) ON (n.id)")
    depends, impacts = [], []                    # (from, to): dependency direction / direction of effect
    for e in p["supersedes"]:
        depends.append((e["a"], e["b"])); impacts += [(e["a"], e["b"]), (e["b"], e["a"])]
    for f in p["findings"]:
        depends.append((f["id"], f["clause"])); impacts.append((f["clause"], f["id"]))
    for c in p["claims"]:
        depends.append((c["id"], c["finding"])); impacts.append((c["finding"], c["id"]))
    for o in p["outcomes"]:
        depends.append((o["finding"], o["id"])); impacts.append((o["finding"], o["id"]))
    for rel, edges in (("DEPENDS_ON", depends), ("IMPACTS", impacts)):
        scratch.query(f"UNWIND $rows AS e MATCH (a:N {{id: e[0]}}), (b:N {{id: e[1]}}) CREATE (a)-[:{rel}]->(b)",
                      {"rows": [list(e) for e in edges]})


def _bfs_depths(scratch, clause_id: str) -> dict[str, int]:
    """Hop distance of everything algo.BFS reaches from the clause (the tree edges give the parents)."""
    res = scratch.query("MATCH (s:N {id: $id}) CALL algo.BFS(s, $d, 'IMPACTS') YIELD nodes, edges RETURN nodes, edges",
                        {"id": clause_id, "d": MAX_DEPTH})
    if not res.result_set:
        return {clause_id: 0}
    nodes, edges = res.result_set[0]
    by_id = {n.id: n.properties["id"] for n in nodes}
    parent = {e.dest_node: e.src_node for e in edges}       # BFS tree edges: one parent per reached node
    def hops(n):
        d = 0
        while n in parent:
            n, d = parent[n], d + 1
        return d
    out = {by_id[i]: hops(i) for i in by_id}
    out[clause_id] = 0                                      # algo.BFS does not list its own source
    return out


def _page_rank(scratch) -> dict[str, float]:
    res = scratch.query("CALL algo.pageRank('N', 'DEPENDS_ON') YIELD node, score RETURN node.id AS id, score")
    return {r[0]: r[1] for r in res.result_set}


def _run(live, fn):
    """Project, run `fn(scratch, projection)`, always drop the scratch graph."""
    name = f"{live.name}__algo_{uuid.uuid4().hex[:8]}"
    scratch = FalkorDB(host=config.FALKORDB_HOST, port=config.FALKORDB_PORT).select_graph(name)
    try:
        p = _projection(live)
        _build(scratch, p)
        return fn(scratch, p)
    finally:
        try:
            scratch.delete()
        except Exception:
            pass


def _lineage_scores(p: dict, rank: dict[str, float]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in p["clauses"]:
        row = out.setdefault(c["lineage"], {"lineage_id": c["lineage"], "score": 0.0, "clause_ids": [], "title": c["title"],
                                            "section": c["section"]})
        row["score"] += rank.get(c["id"], 0.0)
        row["clause_ids"].append(c["id"])
    return out


def rank_lineages(live, tenant: str | None = None) -> list[dict]:
    """Clause lineages ordered by how much memory depends on them (PageRank over the dependency edges)."""
    def work(scratch, p):
        scores = _lineage_scores(p, _page_rank(scratch))
        lineage_of = {c["id"]: c["lineage"] for c in p["clauses"]}
        finding_lineage = {f["id"]: lineage_of[f["clause"]] for f in p["findings"]}
        for s in scores.values():
            s["findings"] = sorted(f for f, l in finding_lineage.items() if l == s["lineage_id"])
            s["claims_total"] = len({c["id"] for c in p["claims"] if finding_lineage.get(c["finding"]) == s["lineage_id"]})
            s["claims_visible"] = len({c["id"] for c in p["claims"] if finding_lineage.get(c["finding"]) == s["lineage_id"]
                                       and (tenant is None or c["tenant"] == tenant)})
            s["score"] = round(s["score"], 4)
            s["clause_ids"].sort()
        ranked = sorted(scores.values(), key=lambda s: (-s["score"], s["lineage_id"]))
        return [{**s, "rank": n + 1} for n, s in enumerate(ranked) if s["findings"]]
    return _run(live, work)


def policy_blast_radius(live, scope, clause_id: str) -> dict:
    """Catalogue tool. `scope` is a catalogue.Scope; other tenants' claims are counted, never named."""
    from claimbridge.catalogue import ToolError

    def work(scratch, p):
        if clause_id not in {c["id"] for c in p["clauses"]}:
            raise ToolError("NOT_FOUND", f"No clause {clause_id}.")
        depth = _bfs_depths(scratch, clause_id)
        info = {c["id"]: c for c in p["clauses"]}
        claims = {c["id"]: c for c in p["claims"]}
        findings = {f["id"]: f for f in p["findings"]}
        mine = lambda c: scope.tenant is None or claims[c]["tenant"] == scope.tenant
        by_depth = sorted(depth.items(), key=lambda kv: (kv[1], kv[0]))
        reached_claims = [{"claim_id": i, "hops": d, "status": claims[i]["status"]} for i, d in by_depth if i in claims and mine(i)]
        withheld = sum(1 for i in depth if i in claims and not mine(i))
        with_memory = {info[f["clause"]]["lineage"] for f in p["findings"]}         # rank only lineages some memory rests on
        scores = sorted((s for s in _lineage_scores(p, _page_rank(scratch)).values() if s["lineage_id"] in with_memory),
                        key=lambda s: (-s["score"], s["lineage_id"]))
        lineage = info[clause_id]["lineage"]
        pos = next((n for n, s in enumerate(scores) if s["lineage_id"] == lineage), None)
        reached_clauses = [{"clause_id": i, "hops": d, "version_id": info[i]["version"]} for i, d in by_depth if i in info]
        reached_findings = [{"finding_id": i, "hops": d, "status": findings[i]["status"]} for i, d in by_depth if i in findings]
        outcome_ids = {o["id"] for o in p["outcomes"]}
        reached_outcomes = [{"resolution_id": i, "hops": d} for i, d in by_depth if i in outcome_ids]
        return {
            "clause_id": clause_id, "lineage_id": lineage, "max_hops": MAX_DEPTH,
            "algorithms": ["algo.BFS over IMPACTS", "algo.pageRank over DEPENDS_ON"],
            "counts": {"clauses": len(reached_clauses), "findings": len(reached_findings), "outcomes": len(reached_outcomes),
                       "claims_visible": len(reached_claims), "claims_withheld": withheld,
                       "farthest_hop": max(depth.values(), default=0)},
            "clauses": reached_clauses, "findings": reached_findings, "outcomes": reached_outcomes, "claims": reached_claims,
            "lineage_rank": {"rank": None if pos is None else pos + 1, "of": len(scores),
                             "score": None if pos is None else round(scores[pos]["score"], 4)},
        }
    return _run(live, work)
