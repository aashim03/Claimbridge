"""Generate the synthetic case dataset and its ground truth.

Output (committed, so every run is reproducible):
  data/generated/cases.jsonl        historical + evaluation claims
  data/generated/ground_truth.json  expected answers for evaluation claims
"""
import json
import random
from datetime import date, timedelta

from claimbridge import config
from claimbridge.knowledge import load, load_eval_claims, load_historical_extra
from claimbridge.seed.notices import notice_text
from claimbridge.seed.rules import expected

SEED = 42
DATA_CUTOFF = 20260930  # latest service date we generate (today is Oct 2026)


def _d(i: int) -> date:
    return date(i // 10000, i // 100 % 100, i % 100)


def _i(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def add_days(i: int, n: int) -> int:
    return _i(_d(i) + timedelta(days=n))


def date_in(rng: random.Random, version: dict, months: tuple[int, int] = (1, 12)) -> int:
    year = version["effective_from"] // 10000
    for _ in range(100):
        d = _i(date(year, rng.randint(*months), rng.randint(1, 28)))
        if version["effective_from"] <= d < version["effective_to"] and d <= DATA_CUTOFF:
            return d
    raise ValueError("could not place date")


class Builder:
    def __init__(self):
        self.kn = load()
        self.rng = random.Random(SEED)
        self.tenants = [t["tenant_id"] for t in self.kn.raw["tenants"]]
        self.versions = {v["version_id"]: v for v in self.kn.versions}
        self.cases: list[dict] = []
        self._n = 0

    def _service_name(self, code: str) -> str:
        return self.kn.name("service_categories", code)

    def make_case(self, *, claim_id, source, service, reason, service_date, evidence,
                  tenant_id=None, filing_lag_days=None, in_network=True, is_emergency=False,
                  enrolled_months=None, session_number=None, notice_style="cited",
                  trap=None, note=None, tenant_probe=None) -> dict:
        version = self.kn.version_for(service_date)
        clause = self.kn.route(reason, service, version)
        lag = filing_lag_days if filing_lag_days is not None else self.rng.randint(5, 40)
        case = {
            "claim_id": claim_id, "source": source, "trap": trap, "note": note,
            "tenant_id": tenant_id or self.rng.choice(self.tenants),
            "service": service, "reason": reason,
            "service_date": service_date, "filed_date": add_days(service_date, lag),
            "filing_lag_days": lag,
            "in_network": in_network, "is_emergency": is_emergency,
            "enrolled_months": enrolled_months, "session_number": session_number,
            "amount": round(self.rng.uniform(250, 24000), 2),
            "evidence": list(evidence),
            "notice_style": notice_style,
            "tenant_probe": tenant_probe,
        }
        case["notice_text"] = notice_text(self.rng, claim_id, self._service_name(service),
                                          service_date, reason, clause, notice_style)
        case["notice_issued"] = add_days(case["filed_date"], self.rng.randint(10, 30))
        return case

    def next_hist_id(self) -> str:
        self._n += 1
        return f"HC-{self._n:03d}"

    def historical(self):
        # Supporting (and contradicting) cases for each seeded Finding.
        for f in self.kn.findings:
            for i in range(f.support):
                v = self.versions[f.learned_in[i % len(f.learned_in)]]
                c = self.make_case(
                    claim_id=self.next_hist_id(), source="historical", service=f.service,
                    reason=f.reason, service_date=date_in(self.rng, v, (1, 8)),
                    evidence=f.needs, filing_lag_days=f.filing_lag_days,
                    in_network=f.flags.get("in_network", True),
                    is_emergency=f.flags.get("is_emergency", bool(f.req_emergency)),
                    enrolled_months=f.enrolled_months,
                    notice_style=self.rng.choice(["cited", "cited", "paraphrase", "vague"]))
                self._resolve(c, "OVERTURNED", f.playbook, supports=f.finding_id)
            for _ in range(f.contradicted_by):
                v = self.versions[f.learned_in[-1]]
                c = self.make_case(
                    claim_id=self.next_hist_id(), source="historical", service=f.service,
                    reason=f.reason, service_date=date_in(self.rng, v, (9, 12)),
                    evidence=f.needs, notice_style="cited")
                self._resolve(c, "UPHELD", f.playbook, contradicts=f.finding_id)
        # Losses, partial wins and look-alikes with no Finding.
        for spec in load_historical_extra():
            for i in range(spec["count"]):
                v = self.versions[spec["versions"][i % len(spec["versions"])]]
                c = self.make_case(
                    claim_id=self.next_hist_id(), source="historical", service=spec["service"],
                    reason=spec["reason"], service_date=date_in(self.rng, v),
                    evidence=spec["evidence"], filing_lag_days=spec.get("filing_lag_days"),
                    in_network=spec.get("in_network", True),
                    is_emergency=spec.get("is_emergency", False),
                    enrolled_months=spec.get("enrolled_months"),
                    notice_style=self.rng.choice(["cited", "paraphrase", "vague"]))
                self._resolve(c, spec["outcome"], None)

    def _resolve(self, case: dict, outcome: str, playbook: str | None,
                 supports: str | None = None, contradicts: str | None = None):
        version = self.kn.version_for(case["service_date"])
        clause = self.kn.route(case["reason"], case["service"], version)
        case["resolution"] = {
            "resolution_id": "R-" + case["claim_id"],
            "outcome": outcome,
            "verified_on": add_days(case["notice_issued"], self.rng.randint(20, 75)),
            "relied_on": clause.clause_id,
            "playbook": playbook,
            "supports_finding": supports,
            "contradicts_finding": contradicts,
        }
        self.cases.append(case)

    def evaluation(self) -> list[dict]:
        truths = []
        for i, spec in enumerate(load_eval_claims()):
            spec = dict(spec)
            spec.setdefault("tenant_id", spec.pop("tenant", None) or self.tenants[i % len(self.tenants)])
            c = self.make_case(source="eval", **spec)
            self.cases.append(c)
            truths.append(expected(c, self.kn))
        return truths


def generate() -> tuple[int, int]:
    b = Builder()
    b.historical()
    truths = b.evaluation()
    config.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.GENERATED_DIR / "cases.jsonl", "w", encoding="utf-8") as f:
        for c in b.cases:
            f.write(json.dumps(c) + "\n")
    with open(config.GENERATED_DIR / "ground_truth.json", "w", encoding="utf-8") as f:
        json.dump(truths, f, indent=2)
    hist = sum(1 for c in b.cases if c["source"] == "historical")
    return hist, len(truths)


def load_cases() -> list[dict]:
    with open(config.GENERATED_DIR / "cases.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_truth() -> dict[str, dict]:
    with open(config.GENERATED_DIR / "ground_truth.json", encoding="utf-8") as f:
        return {t["claim_id"]: t for t in json.load(f)}
