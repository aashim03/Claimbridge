# 03 — Synthetic Dataset and Trap Cases

> **Status (updated 17 Oct 2026): current for the seeded data; one addition.** Besides the seeded scenarios, `data/scenarios/generalization.yaml` holds 19 pre-registered unseen letters (see `07-evaluation.md`). They are separately authored by the AI assistant that helped build the system, not independent, and are kept out of the benchmark.

Everything here is **fictional**: the insurer, the plan, the people, and the claims. Nothing is loaded from real insurers or patients, which meets the rules and avoids privacy risk.

## 1. Fictional world

- **Insurer:** Lumen Health Assurance (fictional)
- **Plan:** LumenCare Silver (`PLAN-SILVER`)
- **Policy versions:**

| version_id | label | effective_from | effective_to |
|---|---|---|---|
| `V2024` | 2024 | 20240101 | 20250101 |
| `V2025` | 2025 | 20250101 | 20260101 |
| `V2026` | 2026 | 20260101 | 99991231 |

## 2. Taxonomies

### Denial reasons (9)
| code | name |
|---|---|
| `PREAUTH_MISSING` | Prior authorization not obtained |
| `NOT_MED_NECESSARY` | Not medically necessary |
| `EXCLUDED_SERVICE` | Service excluded by the policy |
| `WAITING_PERIOD` | Waiting period not satisfied |
| `OUT_OF_NETWORK` | Provider out of network |
| `INCOMPLETE_DOCS` | Incomplete documentation |
| `CODING_ERROR` | Billing or coding error |
| `DUPLICATE_CLAIM` | Duplicate submission |
| `TIMELY_FILING` | Filed after the deadline |

### Service categories (10)
`MRI`, `PHYSIO`, `ER_VISIT`, `INPATIENT_SURGERY`, `BARIATRIC`, `MATERNITY`, `GENETIC_TEST`, `AMBULANCE`, `SLEEP_STUDY`, `DME` (durable medical equipment)

### Evidence types (15)
`PREAUTH_APPROVAL`, `RETRO_AUTH_REQUEST`, `SPECIALIST_REFERRAL`, `PHYSICIAN_NECESSITY_LETTER`, `PROGRESS_NOTES`, `ITEMIZED_BILL`, `CORRECTED_CODING_SUBMISSION`, `DISCHARGE_SUMMARY`, `EMERGENCY_ATTESTATION`, `BMI_RECORD`, `SUPERVISED_PROGRAM_RECORD`, `GENETIC_COUNSELOR_REFERRAL`, `LAB_REPORT`, `ENROLLMENT_RECORD`, `PROOF_OF_TIMELY_FILING`

## 3. Clause lineages (about 25)

### Lineages that change between versions (these power the traps)

| lineage_id | 2024 | 2025 | 2026 |
|---|---|---|---|
| `L-MRI-PREAUTH` | Outpatient MRI needs preauth, **unless** there's a specialist referral | same | Preauth required for **all** outpatient MRI. The referral exception is removed. |
| `L-PHYSIO-LIMIT` | 20 sessions a year | 20 | 12 sessions. More need a necessity letter and progress notes. |
| `L-OON-EMERGENCY` | Out-of-network emergencies covered with an emergency attestation filed within 72h | 72h | **48h** |
| `L-BARIATRIC` | **Excluded** | Covered with a BMI record and a supervised-program record | same as 2025 |
| `L-MATERNITY-WAIT` | 12-month waiting period | 12 | **9** months |
| `L-TIMELY-FILING` | File within 180 days | 180 | **90** days |
| `L-GENETIC-TEST` | *(absent, so excluded under experimental)* | Covered with a genetic counselor referral | same |

### Stable lineages (same text in every version)
`L-ER-COVERAGE`, `L-INPATIENT-PREAUTH`, `L-MED-NECESSITY-DEF`, `L-NETWORK-DEF`, `L-ITEMIZED-BILL`, `L-CODING-CORRECTION`, `L-DUPLICATE`, `L-APPEAL-WINDOW`, `L-COSMETIC-EXCL`, `L-EXPERIMENTAL-EXCL`, `L-AMBULANCE`, `L-SLEEP-STUDY-PREAUTH`, `L-DME-NECESSITY`, `L-RETRO-AUTH`, `L-ENROLLMENT`, `L-ER-NOTIFY`, `L-PEER-REVIEW`, `L-DISCHARGE-DOCS`

### YAML format (`data/knowledge/lineages.yaml`)
All versions of a lineage live in one entry. `inherit` means "unchanged from the previous version," and a missing version means the lineage doesn't exist in it. The loader expands each entry into one `Clause` per version (`C-<year>-<suffix>`) linked by `SUPERSEDES`.
```yaml
- lineage_id: L-MRI-PREAUTH
  section: "4.2"
  title: Prior authorization for outpatient MRI
  governs: [MRI]
  routes: [{reason: PREAUTH_MISSING, service: MRI}]
  versions:
    V2024: {type: CONDITION, text: "...unless ordered on a specialist referral.",
            requires: [SPECIALIST_REFERRAL], params: {referral_exception: true}}
    V2025: inherit
    V2026: {type: CONDITION, text: "...No referral exception applies...",
            requires: [RETRO_AUTH_REQUEST, PHYSICIAN_NECESSITY_LETTER],
            params: {referral_exception: false}}
```

`params` is what the rule engine and Cypher compare. `text` is what humans and the LLM read. `requires` is the evidence an appeal under that clause needs. `routes` say which (denial reason, service) denials cite the clause.

Files: `taxonomy.yaml` (versions, taxonomies, tenants), `lineages.yaml`, `playbooks.yaml`, `findings.yaml` (seed memory), and `data/scenarios/eval_claims.yaml` and `historical_extra.yaml`.

## 4. Playbooks (procedural memory, about 8)

| playbook_id | For reason | Steps |
|---|---|---|
| `PB-RETRO-AUTH` | PREAUTH_MISSING | 1. File a retro-auth request → 2. Attach a specialist referral (if the version allows it) → 3. Submit an appeal |
| `PB-NECESSITY-APPEAL` | NOT_MED_NECESSARY | 1. Physician necessity letter → 2. Progress notes → 3. Request peer review |
| `PB-CODING-FIX` | CODING_ERROR | 1. Itemized bill → 2. Corrected coding submission |
| `PB-OON-EMERGENCY` | OUT_OF_NETWORK | 1. Emergency attestation (within the window) → 2. Discharge summary → 3. Appeal at the in-network rate |
| `PB-DOCS-COMPLETE` | INCOMPLETE_DOCS | 1. Itemized bill → 2. Discharge summary → 3. Resubmit |
| `PB-WAITING-CHECK` | WAITING_PERIOD | 1. Enrollment record → 2. Recompute the waiting period under the governing version |
| `PB-TIMELY-PROOF` | TIMELY_FILING | 1. Proof of timely filing, if it exists. Otherwise there is no basis, so escalate. |
| `PB-BARIATRIC-COVERAGE` | EXCLUDED_SERVICE (bariatric) | 1. BMI record → 2. Supervised program record → 3. Appeal citing the coverage clause |

`Playbook.wins / uses` is updated by the Curator from verified outcomes. That is the "procedural memory gets better" signal.

## 5. Historical claims (about 50, all with verified outcomes)

The generator is seeded (`seed=42`), so output is reproducible. The distribution is:

- Across versions: 15 in 2024, 20 in 2025, 15 in 2026.
- Outcomes: about 60% OVERTURNED, 25% UPHELD, 15% PARTIAL.
- Every denial reason appears at least 3 times. MRI preauth, physio, and out-of-network emergency appear more often because they feed the traps.

Each historical claim gets:
- a tenant, service, dates, network and emergency flags, and an amount;
- a denial notice (text written by an LLM from structured fields once, then **frozen** in `cases.jsonl`);
- submitted evidence;
- a resolution with `RELIED_ON` clauses, `SUPPORTED_BY` evidence, and `FOLLOWED` playbook.

### Initial Findings (seeded from historical data by running the Curator once)

| finding_id | Statement (generated from structure) | Valid in | Conditions | Purpose |
|---|---|---|---|---|
| `F-MRI-REFERRAL` | PREAUTH_MISSING on `L-MRI-PREAUTH` is overturned with a specialist referral | V2024, V2025 | — | Becomes STALE when V2026 drops the exception (T1) |
| `F-PHYSIO-NECESSITY` | NOT_MED_NECESSARY on physio sessions 13–20 is overturned with a necessity letter and progress notes | V2026 | — | T3 |
| `F-OON-ER` | OUT_OF_NETWORK is overturned with an emergency attestation within the window | V2024–V2026 | `is_emergency: true` | T5 |
| `F-SLEEP-RETRO` | PREAUTH_MISSING for a sleep study is overturned via a retro-auth | V2024–V2026 | — | T4 (later contradicted) |
| `F-CODING` | CODING_ERROR is overturned with a corrected coding submission | all | — | A clean positive case |
| … | about 10 more covering every reason | | | |

## 6. Trap cases

Every trap is a fixed evaluation claim in `data/scenarios/traps.yaml`, with stable IDs, so tests, demo, and video all reference the same thing. Each trap type has 2–3 variants, about 18 claims in total. The remaining ~12 evaluation claims are "normal" cases.

| Trap | Name | Setup | Nearest text match says | Correct behavior | Rejection code |
|---|---|---|---|---|---|
| **T1** | Version drift | MRI preauth denial, service date 2026-03, specialist referral attached | "Overturn with referral" (F-MRI-REFERRAL, a near-identical 2025 case) | Reject: V2026 `C-2026-MRI-PREAUTH` supersedes and removes the exception. Recommend a retro-auth path and flag low odds. | `VERSION_DRIFT` |
| **T2** | Same reason, wrong lineage | PREAUTH_MISSING for **inpatient surgery** | MRI preauth precedents (same words) | Don't transfer MRI Findings, because the lineage is `L-INPATIENT-PREAUTH`. Use the inpatient Playbook. | `LINEAGE_MISMATCH` |
| **T3** | Missing evidence | Physio session 15 in 2026, no necessity letter | "Overturned" (F-PHYSIO-NECESSITY) | The Finding applies but its evidence is missing. The answer is "obtain the necessity letter and progress notes" and not a promise of success. | *(applies with a gap)* |
| **T4** | Contradicted memory | Sleep study PREAUTH_MISSING | F-SLEEP-RETRO says overturn | An injected later verified case was UPHELD under the same conditions, so the Finding is CONTRADICTED. Show both and lower confidence. | `CONTRADICTED` |
| **T5** | Condition unmet | OUT_OF_NETWORK, **not** an emergency (elective MRI) | F-OON-ER says overturn | Reject because `is_emergency=false` fails the Finding condition. The disposition is upheld-likely, with an explanation. | `CONDITION_UNMET` |
| **T6** | No basis | TIMELY_FILING, filed after 120 days under V2026 (limit 90) | Old 180-day cases overturned | Reject the 2024 and 2025 precedents (version drift). With no valid path, the answer is "insufficient basis, escalate to a human." | `NO_VALID_PATH` |
| **T7** | Tenant leakage | Tenant A's claim. The request asks for Tenant B's similar case details. | Baseline happily shows B's text | Return only the anonymized Finding and outcome, never B's claim, notice, or evidence | `TENANT_SCOPE` |

**Design rule for traps:** the most text-similar historical case should be the **wrong** answer. That is what separates graph reasoning from vector RAG. `cli selfcheck` measures it rather than asserting it.

**Measured result: 12 of 17 traps (T1–T6) fool nearest-neighbour reuse.** In the other 5 (T2-02, T5-01, T5-02, T6-02, T6-03), the nearest case is a realistic look-alike loss or the correct precedent, so naive reuse happens to be right. We keep them, because hiding them would overstate the result. The graph pipeline gets all 17 right.

Clause-level **gates** decide "no appeal basis" independently of precedent: `EXCLUSION_NO_BASIS` (an exclusion clause), `EMERGENCY_REQUIRED` (the out-of-network clause for a non-emergency), `FILED_LATE` (lag over the governing limit), and `WAITING_NOT_MET` (enrollment shorter than the governing wait).

## 7. Ground truth

### Rule engine (`backend/seed/rules.py`)
A small, **independent** Python implementation over dataclasses loaded from YAML. It never touches Cypher, so it can't share bugs with the graph tools.

```
def expected(claim, knowledge, findings):
    version = version_for(claim.service_date)
    lineage = lineage_for(claim.denial_reason, claim.service, version)
    clause  = knowledge.clause(version, lineage)
    required = clause.requires ∪ playbook_evidence(claim.denial_reason, lineage)
    applicable, rejected = [], []
    for f in findings:
        if f.reason != claim.denial_reason:            continue
        if f.lineage != lineage:                        rejected += (f, LINEAGE_MISMATCH); continue
        if version not in f.valid_in:                   rejected += (f, VERSION_DRIFT);    continue
        if f.status == CONTRADICTED:                    rejected += (f, CONTRADICTED);     continue
        if not conditions_hold(f.conditions, claim):    rejected += (f, CONDITION_UNMET);  continue
        applicable += f;  required |= f.needs_evidence
    missing = required - claim.evidence_types
    disposition = (NO_BASIS_ESCALATE   if not applicable and not playbook_viable(...)
                   else APPEAL_NEEDS_EVIDENCE if missing
                   else APPEAL_VIABLE)
    return GroundTruth(...)
```

### Ground truth record (`data/generated/ground_truth.json`)
```json
{
  "claim_id": "EV-T1-01",
  "trap": "T1",
  "expected_reason": "PREAUTH_MISSING",
  "expected_version": "V2026",
  "expected_lineage": "L-MRI-PREAUTH",
  "expected_clause": "C-2026-MRI-PREAUTH",
  "expected_required_evidence": ["PHYSICIAN_NECESSITY_LETTER", "RETRO_AUTH_REQUEST"],
  "expected_missing_evidence": ["PHYSICIAN_NECESSITY_LETTER", "RETRO_AUTH_REQUEST"],
  "expected_applicable_findings": [],
  "expected_rejected_findings": [
    {"finding_id": "F-INPATIENT-RETRO", "code": "LINEAGE_MISMATCH"},
    {"finding_id": "F-MRI-REFERRAL", "code": "VERSION_DRIFT"},
    {"finding_id": "F-SLEEP-RETRO", "code": "LINEAGE_MISMATCH"}],
  "expected_gates": [],
  "expected_disposition": "APPEAL_NEEDS_EVIDENCE"
}
```

## 8. Generation pipeline

| Step | Script | Output | Deterministic? |
|---|---|---|---|
| 1 | Hand-author the YAML (knowledge, findings, scenarios) | `data/knowledge/*`, `data/scenarios/*` | Yes |
| 2 | `cli generate`: seeded sampling of historical claims (support cases for each Finding, contradicting cases, extra losses), evaluation claims from YAML, and denial-notice text from templates (`seed/notices.py`: cited, paraphrase, vague, misleading) | `cases.jsonl` (52 historical + 32 evaluation) | Yes (`seed=42`) |
| 3 | `seed/rules.py`: compute ground truth | `ground_truth.json` | Yes |
| 4 | `cli reset`: load into FalkorDB. Historical claims are loaded resolved, and evaluation claims as NEW. Findings come from `findings.yaml`, linked to their supporting and contradicting resolutions, with `VALID_IN` computed from clause params. | Graph | Yes |
| 5 | `cli selfcheck`: does the nearest historical case give the wrong answer? | Report | Yes |

`make reset` drops and reseeds the graph in about 20 seconds (most of that is loading the embedding model).

Phase 1 uses template notices, not LLM-written ones, so the dataset is exactly reproducible. An optional LLM rewrite of the notice text can come later. Seed Findings are authored as specs and the matching historical cases are generated from them. The runtime Curator (Phase 2) derives new Findings from new verified outcomes.

## 9. Writing tips for the denial notices

- Write them like real denial letters: some cite the section number, some only paraphrase it, and some are vague ("services not covered as submitted"). Intake has to do real extraction work.
- Include 3–4 notices whose wording is misleading (for example, they mention "authorization" but the actual reason is coding). This tests the graph/embedding cross-check.
- Don't include any real insurer names, real CPT/ICD codes that imply real cases, or real people's names.
