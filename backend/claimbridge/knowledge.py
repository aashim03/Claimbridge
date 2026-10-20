"""Load the hand-authored knowledge YAML into plain Python objects.

Used by the seeders (to write the graph) and by the ground-truth rule engine.
The rule engine never touches Cypher, so it cannot share bugs with the graph tools.
"""
import hashlib
import json

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from claimbridge import config

FLAT_PARAMS = ("referral_exception", "max_sessions", "notify_hours", "wait_months",
               "limit_days", "req_emergency", "no_basis")


@dataclass
class Clause:
    clause_id: str
    lineage_id: str
    version_id: str
    section: str
    type: str
    title: str
    text: str
    requires: list[str]
    params: dict
    governs: list[str]
    routes: list[dict]
    supersedes: str | None = None

    @property
    def fingerprint(self) -> str:
        payload = {"text": " ".join(self.text.split()), "params": self.params,
                   "requires": sorted(self.requires), "type": self.type,
                   "governs": sorted(self.governs), "routes": sorted(self.routes, key=lambda r: json.dumps(r, sort_keys=True))}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @property
    def no_basis(self) -> bool:
        return bool(self.params.get("no_basis", False))

    @property
    def req_emergency(self) -> bool:
        return bool(self.params.get("req_emergency", False))


@dataclass
class FindingSpec:
    finding_id: str
    reason: str
    lineage: str
    service: str
    learned_in: list[str]
    needs: list[str]
    playbook: str
    support: int
    contradicted_by: int = 0
    req_emergency: bool | None = None
    req_in_network: bool | None = None
    flags: dict = field(default_factory=dict)
    enrolled_months: int | None = None
    filing_lag_days: int | None = None
    valid_in: list[str] = field(default_factory=list)   # computed

    @property
    def wins(self) -> int:
        return self.support

    @property
    def status(self) -> str:
        if self.contradicted_by >= self.wins:
            return "CONTRADICTED"
        return "ACTIVE"

    @property
    def confidence(self) -> float:
        return round((self.wins + 1) / (self.wins + self.contradicted_by + 2), 3)


@dataclass
class Knowledge:
    raw: dict
    versions: list[dict]
    clauses: dict[str, Clause]                 # clause_id -> Clause
    by_version: dict[str, dict[str, Clause]]   # version_id -> lineage_id -> Clause
    findings: list[FindingSpec]
    playbooks: list[dict]

    @property
    def latest_version(self) -> str:
        return self.versions[-1]["version_id"]

    def version_for(self, date: int) -> str:
        for v in self.versions:
            if v["effective_from"] <= date < v["effective_to"]:
                return v["version_id"]
        raise ValueError(f"no policy version covers {date}")

    def clause(self, version_id: str, lineage_id: str) -> Clause | None:
        return self.by_version[version_id].get(lineage_id)

    def route(self, reason: str, service: str, version_id: str) -> Clause | None:
        """Which clause a denial for (reason, service) cites under this version."""
        best, best_key = None, None
        for c in self.by_version[version_id].values():
            for r in c.routes:
                if r["reason"] != reason or r["service"] not in (service, "*"):
                    continue
                key = (r["service"] == service, r.get("priority", 0))
                if best_key is None or key > best_key:
                    best, best_key = c, key
        return best

    def name(self, kind: str, code: str) -> str:
        for item in self.raw[kind]:
            if item["code"] == code:
                return item["name"]
        return code


def _read(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _expand_lineages(lineages: list[dict], versions: list[dict]):
    clauses: dict[str, Clause] = {}
    by_version: dict[str, dict[str, Clause]] = {v["version_id"]: {} for v in versions}
    for lin in lineages:
        prev: Clause | None = None
        prev_body = None
        for v in versions:
            vid = v["version_id"]
            body = lin["versions"].get(vid)
            if body is None:
                prev, prev_body = None, None
                continue
            if body == "inherit":
                if prev_body is None:
                    raise ValueError(f"{lin['lineage_id']} {vid}: inherit with no previous version")
                body = prev_body
            suffix = lin["lineage_id"].removeprefix("L-")
            c = Clause(
                clause_id=f"C-{v['label']}-{suffix}",
                lineage_id=lin["lineage_id"], version_id=vid,
                section=lin["section"], type=body["type"], title=lin["title"],
                text=" ".join(body["text"].split()),
                requires=list(body.get("requires", [])),
                params=dict(body.get("params", {})),
                governs=list(lin.get("governs", [])),
                routes=[{"service": "*", "priority": 0, **r} for r in lin.get("routes", [])],
                supersedes=prev.clause_id if prev else None,
            )
            clauses[c.clause_id] = c
            by_version[vid][c.lineage_id] = c
            prev, prev_body = c, body
    return clauses, by_version


@lru_cache(maxsize=1)
def load() -> Knowledge:
    kdir = config.DATA_DIR / "knowledge"
    raw = _read(kdir / "taxonomy.yaml")
    versions = raw["versions"]
    clauses, by_version = _expand_lineages(_read(kdir / "lineages.yaml"), versions)
    playbooks = _read(kdir / "playbooks.yaml")

    findings = [FindingSpec(**f) for f in _read(kdir / "findings.yaml")]
    for f in findings:
        learned = [by_version[v][f.lineage] for v in f.learned_in]
        if any(c.fingerprint != learned[0].fingerprint for c in learned):
            raise ValueError(f"{f.finding_id}: learned_in versions disagree on clause params")
        # VALID_IN: every version whose clause for this lineage has identical params.
        f.valid_in = [v["version_id"] for v in versions
                      if f.lineage in by_version[v["version_id"]]
                      and by_version[v["version_id"]][f.lineage].fingerprint == learned[0].fingerprint]
    return Knowledge(raw, versions, clauses, by_version, findings, playbooks)


def load_eval_claims() -> list[dict]:
    return _read(config.DATA_DIR / "scenarios" / "eval_claims.yaml")


def load_historical_extra() -> list[dict]:
    return _read(config.DATA_DIR / "scenarios" / "historical_extra.yaml")
