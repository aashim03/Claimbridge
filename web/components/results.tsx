"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { TRAPS, pct } from "@/lib/vocab";
import { SignalMark } from "./signal";
import { useAccess } from "./session-gate";
import { ErrorNote, Mono, SectionHead } from "./ui";

type GainSide = {
  accepted?: string[];
  confidence?: number | null;
  precedent_cases?: string[] | null;
  disposition?: string | null;
  missing?: string[];
};

type Access = { policy_clauses?: string; abstract_findings?: string; raw_cases?: string; decided_by?: string };

type GenResult = { id: string; kind: string; purpose: string; passed: boolean; not_evaluated?: boolean; mismatches: string[] };

export type EvalData = {
  generated_at: string;
  llm: string;
  valid?: boolean;
  scored_claims?: number;
  total_claims?: number;
  ground_truth?: string;
  limitations?: string;
  run?: {
    run_id: string;
    label?: string | null;
    started_at: string;
    git?: { revision?: string; dirty?: boolean } | null;
    source_sha256: string;
    dataset: { all: string };
    config: { llm_mode: string; cache_policy: string };
    invalid_reasons: string[];
  };
  llm_calls?: { fresh: number; replayed: number; fake: number };
  access?: Record<string, Access | null>;
  not_run?: Record<string, string[]>;
  errors?: Record<string, Record<string, { kind: string; message?: string }>>;
  systems: Record<
    string,
    {
      label: string;
      embedding_model?: string | null;
      metrics: Record<string, number | null>;
      by_group: Record<string, [number, number]>;
      per_claim?: Record<string, { ok: boolean; checks: Record<string, boolean> }>;
      abstained?: string[];
      wrong_precedent_by_code: Record<string, number>;
      memory_gain?: { before: GainSide; after: GainSide } | null;
    }
  >;
  chaos?: {
    claims: number;
    kills: number;
    steps_interrupted: number;
    recovery_seconds: number[];
    mean_recovery_seconds: number | null;
    lease_ttl_s: number;
    correct: number;
    duplicate_step_outputs: number;
    fenced_writes_rejected?: number;
    stale_worker_scenario?: {
      stale_attempts: { what: string; accepted: boolean }[];
      fenced_write_rejected_events: number;
      stale_checkpoint_survived: boolean;
      step_done_events: [string, string][];
    } | null;
  } | null;
  generalization?: {
    file: string;
    total: number;
    passed: number;
    authorship: string;
    by_kind: Record<string, { total: number; evaluated?: number; passed: number; not_evaluated?: number }>;
    results: GenResult[];
  } | null;
};

const ROWS: [string, string, "up" | "down" | "none", boolean][] = [
  ["completion_rate", "Completed claims (failures stay in the denominator)", "up", true],
  ["abstained_to_human", "Escalated to a person (safe abstention)", "none", false],
  ["no_output", "No output (cause listed below)", "none", false],
  ["decision_correct", "Correct decisions, excluding precedent recall", "up", true],
  ["all_correct", "Claims fully correct", "up", true],
  ["M6_disposition_accuracy", "Disposition accuracy", "up", true],
  ["M4_wrong_precedent_rate", "Claims relying on a precedent that does not apply", "down", true],
  ["M8_stale_precedent_avoided", "Superseded or contradicted precedent avoided", "up", true],
  ["M8_stale_precedent_explained", "…and refused with the right reason", "up", true],
  ["M3_precedent_precision", "Precedent precision", "up", true],
  ["M3_precedent_recall", "Precedent recall (all expected)", "up", true],
  ["M3_precedent_recall_reachable", "Precedent recall (only what the system's corpus can reach)", "up", true],
  ["M5_missing_evidence_f1", "Missing-evidence F1", "up", true],
  ["M7_unsupported_item_rate", "Plan items without a valid citation ID", "down", true],
  ["M9_tenant_fields_leaked", "Other policyholders' case details exposed", "down", false],
  ["M2_version_accuracy", "Governing policy version", "up", true],
  ["M1_reason_accuracy", "Denial reason", "up", true],
  ["M12_tokens_per_claim", "LLM tokens per claim", "down", false],
];

const ORDER = ["claimbridge", "no_memory", "baseline_rag_findings", "baseline_rag", "baseline_rag_strong"];
const SHORT: Record<string, string> = {
  claimbridge: "ClaimBridge",
  baseline_rag: "Plain RAG",
  baseline_rag_strong: "Plain RAG, large embeddings",
  baseline_rag_findings: "RAG + findings",
  no_memory: "ClaimBridge without memory",
};

function fmt(v: number | null | undefined, isPct: boolean) {
  if (v == null) return "n/a";
  return isPct ? pct(v) : v.toLocaleString("en-US");
}

export function useEval() {
  return useSWR<EvalData>("/api/eval", fetcher, { revalidateOnFocus: false });
}

export function HeadlineTable({ data, compact = false }: { data: EvalData; compact?: boolean }) {
  const systems = ORDER.filter((s) => data.systems[s] && (!compact || s !== "baseline_rag_strong"));
  const rows = compact
    ? ROWS.filter((r) => ["completion_rate", "decision_correct", "all_correct", "M6_disposition_accuracy", "M4_wrong_precedent_rate"].includes(r[0]))
    : ROWS;
  return (
    <div className="overflow-x-auto">
      <table className={`w-full border-collapse text-left ${compact ? "" : "min-w-[720px]"}`}>
        <thead>
          <tr className="border-b border-rule-2">
            <th className="py-2 pr-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">
              {data.scored_claims ?? ""} authored synthetic claims
            </th>
            {systems.map((s) => (
              <th
                key={s}
                className={`py-2 pl-3 text-right align-bottom text-[13px] font-semibold sm:pl-4 ${s === "claimbridge" ? "text-ink" : "text-ink-2"} ${
                  compact && s === "baseline_rag_findings" ? "hidden md:table-cell" : ""
                }`}
              >
                {SHORT[s] ?? s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, label, dir, isPct]) => {
            const vals = systems.map((s) => data.systems[s].metrics[key]);
            const best =
              dir === "up" ? Math.max(...vals.map((v) => v ?? -1)) : dir === "down" ? Math.min(...vals.map((v) => v ?? Infinity)) : null;
            return (
              <tr key={key} className="border-b border-rule">
                <th scope="row" className="py-2 pr-4 text-[13.5px] font-normal text-ink-2">
                  {label}
                </th>
                {systems.map((s, i) => {
                  const v = vals[i];
                  const isBest = best != null && v != null && v === best;
                  return (
                    <td
                      key={s}
                      className={`py-2 pl-3 text-right text-[16px] tabular sm:pl-4 ${
                        s === "claimbridge" ? "bg-wash-2 font-semibold text-ink" : isBest ? "text-ink" : "text-ink-3"
                      } ${compact && s === "baseline_rag_findings" ? "hidden md:table-cell" : ""}`}
                    >
                      {fmt(v, isPct)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const groupOf = (cid: string) => (cid.startsWith("EV-T") ? cid.slice(3, 5) : cid.startsWith("EV-M") ? "M" : "normal");

export function EvaluationView() {
  const { data, error } = useEval();
  const { operator } = useAccess();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <div className="mx-auto h-96 max-w-[1280px] animate-pulse rounded-[12px] bg-wash" />;
  const systems = ORDER.filter((s) => data.systems[s]);
  const cb = data.systems.claimbridge;
  const ch = data.chaos;
  const run = data.run;
  const groups = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "M", "normal"];
  const claimIds = Object.keys(cb.per_claim ?? {});
  const missing = Object.entries(data.not_run ?? {}).filter(([, v]) => v.length);
  const st = ch?.stale_worker_scenario;
  const gen = data.generalization;

  return (
    <div className="mx-auto max-w-[1280px]">
      <h1 className="text-[26px] font-semibold leading-[1.15] tracking-[-0.03em]">Evaluation</h1>
      <p className="mt-1.5 max-w-[78ch] text-[13.5px] text-ink-2">
        Every system answers the same {data.scored_claims} authored synthetic claims with the same LLM ({data.llm.split("/").slice(1).join("/")}). This is a{" "}
        <strong className="font-medium text-ink">whole-system comparison</strong>: the systems differ in what they can see and in what decides their
        answers, not only in how data is stored. Read the access table before the numbers. Expected answers come from {data.ground_truth ?? "a separately implemented rule engine"}.
      </p>

      {run && (
        <section className="mt-5 rounded-[12px] border border-rule bg-wash px-4 py-3 text-[12.5px] text-ink-2" aria-label="Run identity">
          {data.valid === false && (
            <p role="alert" className="mb-2 font-medium text-neg">
              This run is marked invalid: {run.invalid_reasons.join(" ")}
            </p>
          )}
          <dl className="grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            <div className="flex gap-2">
              <dt className="text-ink-3">Run</dt>
              <dd className="min-w-0 truncate"><Mono className="text-ink">{run.run_id}</Mono></dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-ink-3">Started</dt>
              <dd>{run.started_at}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-ink-3">Code</dt>
              <dd>
                <Mono>{(run.git?.revision ?? "unknown").slice(0, 10)}</Mono>
                {run.git?.dirty ? " + uncommitted changes" : ""} · source <Mono>{run.source_sha256.slice(0, 10)}</Mono>
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-ink-3">Data</dt>
              <dd>
                {data.scored_claims} synthetic claims · digest <Mono>{run.dataset.all.slice(0, 10)}</Mono>
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-ink-3">Model mode</dt>
              <dd>
                {run.config.llm_mode}
                {data.llm_calls ? ` · ${data.llm_calls.fresh} fresh, ${data.llm_calls.replayed} replayed` : ""}
              </dd>
            </div>
          </dl>
        </section>
      )}

      <SectionHead title="What each system can see" aside="differences here explain differences below" />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-[12.5px]">
          <thead>
            <tr className="border-b border-rule-2 text-[11px] uppercase tracking-[0.06em] text-ink-3">
              <th className="py-2 pr-3 font-medium">System</th>
              <th className="py-2 pr-3 font-medium">Abstract findings</th>
              <th className="py-2 pr-3 font-medium">Raw case records</th>
              <th className="py-2 font-medium">What decides the answer</th>
            </tr>
          </thead>
          <tbody>
            {systems.map((s) => {
              const a = data.access?.[s];
              return (
                <tr key={s} className="border-b border-rule align-top">
                  <td className="py-2 pr-3 font-medium text-ink">{SHORT[s] ?? s}</td>
                  <td className="py-2 pr-3 text-ink-2">{a?.abstract_findings ?? "—"}</td>
                  <td className="py-2 pr-3 text-ink-2">{a?.raw_cases ?? "—"}</td>
                  <td className="py-2 text-ink-2">{a?.decided_by ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 max-w-[80ch] text-[12px] text-ink-3">
        A system that cannot see a precedent cannot cite it. Only <strong className="font-medium text-ink-2">RAG + findings</strong> equalises information
        access; what remains is deterministic rules versus an LLM deciding from retrieved text.
      </p>

      <SectionHead title="Results" aside={`generated ${new Date(data.generated_at).toLocaleString("en-GB")}`} />
      <HeadlineTable data={data} />
      <p className="mt-2 max-w-[80ch] text-[12px] text-ink-3">
        Where decision correctness is equal, memory adds precedents and a changed checklist, not a measured gain in decisions.
      </p>

      {missing.length > 0 && (
        <>
          <SectionHead title="Missing outputs" aside="stay in every denominator and count as failures" />
          <ul className="space-y-1 text-[13px] text-ink-2">
            {missing.flatMap(([s, ids]) =>
              ids.map((c) => (
                <li key={`${s}-${c}`}>
                  <span className="text-ink">{SHORT[s] ?? s}</span> · <Mono>{c}</Mono> · cause:{" "}
                  <strong className="font-medium text-ink">{data.errors?.[s]?.[c]?.kind ?? "not recorded"}</strong>
                </li>
              )),
            )}
          </ul>
          <p className="mt-2 text-[12px] text-ink-3">A provider limit or timeout says nothing about a system&apos;s reasoning. A re-run is a new run.</p>
        </>
      )}

      <div className="grid grid-cols-1 gap-x-10 lg:grid-cols-2 [&>*]:min-w-0">
        <section>
          <SectionHead title="By scenario" aside="claims fully correct" />
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-rule-2 text-left text-[11.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  <th className="py-1.5 pr-3 font-semibold">Scenario</th>
                  {systems.map((s) => (
                    <th key={s} className="py-1.5 pl-3 text-right font-semibold">
                      {(SHORT[s] ?? s).replace("ClaimBridge without memory", "No memory").replace("Plain RAG, large embeddings", "RAG large")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups
                  .filter((g) => cb.by_group[g])
                  .map((g) => (
                    <tr key={g} className="border-b border-rule">
                      <td className="py-1.5 pr-3 text-ink-2">{g === "normal" ? "Routine claims" : `${g} · ${TRAPS[g]?.name}`}</td>
                      {systems.map((s) => {
                        const [ok, n] = data.systems[s].by_group[g] ?? [0, 0];
                        const kind = ok === n ? "positive" : ok === 0 ? "negative" : "caution";
                        return (
                          <td key={s} className={`py-1.5 pl-3 text-right tabular ${s === "claimbridge" ? "font-semibold" : ""}`}>
                            <span className="inline-flex items-center gap-1.5">
                              <SignalMark kind={kind} size={11} />
                              {ok}/{n}
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-ink-3">
            The no-memory ablation cannot name precedents by design. Use decision correctness to compare decisions without penalizing that missing capability.
          </p>
        </section>

        <section>
          <SectionHead title="Why wrong precedents were used" aside="per the ground truth" />
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-rule-2 text-left text-[11.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  <th className="py-1.5 pr-3 font-semibold">System</th>
                  {["VERSION_DRIFT", "CONTRADICTED", "NOT_APPLICABLE"].map((c) => (
                    <th key={c} className="py-1.5 pl-3 text-right font-semibold">
                      {c === "VERSION_DRIFT" ? "Superseded" : c === "CONTRADICTED" ? "Contradicted" : "Not applicable"}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {systems.map((s) => (
                  <tr key={s} className="border-b border-rule">
                    <td className="py-1.5 pr-3 text-ink-2">{SHORT[s] ?? s}</td>
                    {["VERSION_DRIFT", "CONTRADICTED", "NOT_APPLICABLE"].map((c) => (
                      <td key={c} className="py-1.5 pl-3 text-right tabular">
                        {data.systems[s].wrong_precedent_by_code[c] ?? 0}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {ch && (
            <>
              <SectionHead title="Coordination under failure" aside={`${ch.kills} hard kills, ${ch.claims} claims`} />
              <dl className="grid grid-cols-[1fr_auto] gap-y-1.5 text-[13.5px]">
                <dt className="text-ink-2">Kills that interrupted a step in progress</dt>
                <dd className="text-right text-[16px] tabular">
                  {ch.steps_interrupted} of {ch.kills}
                </dd>
                <dt className="text-ink-2">…resumed by another worker</dt>
                <dd className="text-right text-[16px] tabular">{ch.recovery_seconds?.length ?? 0}</dd>
                <dt className="text-ink-2">Mean kill-to-completion, incl. {ch.lease_ttl_s}s lease</dt>
                <dd className="text-right text-[16px] tabular">{ch.mean_recovery_seconds}s</dd>
                <dt className="text-ink-2">Claims completed and correct</dt>
                <dd className="text-right text-[16px] tabular">
                  {ch.correct}/{ch.claims}
                </dd>
                <dt className="text-ink-2">Duplicate step outputs</dt>
                <dd className="text-right text-[16px] tabular">{ch.duplicate_step_outputs}</dd>
              </dl>
              <p className="mt-2 text-[12px] text-ink-3">
                A killed process never wakes up, so random kills cannot show a stale worker being refused: {ch.fenced_writes_rejected ?? 0} late writes
                were rejected during them, which proves nothing about fencing.
              </p>
              {st && (
                <div className="mt-3 rounded-[10px] border border-rule bg-wash px-3 py-2.5 text-[12.5px] text-ink-2">
                  <p className="font-medium text-ink">Deliberate paused-worker scenario</p>
                  <p className="mt-0.5">
                    A living worker is paused past its lease, a replacement finishes the step, then the first worker wakes and writes:{" "}
                    {st.stale_attempts.map((a) => `${a.what} ${a.accepted ? "ACCEPTED" : "rejected"}`).join(", ")};{" "}
                    {st.fenced_write_rejected_events} <Mono>FENCED_WRITE_REJECTED</Mono> audit event; stale checkpoint{" "}
                    {st.stale_checkpoint_survived ? "survived" : "did not survive"}.
                  </p>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {gen && (
        <>
          <SectionHead title="Generalization check" aside="pre-registered, separately authored, not independent" />
          <p className="max-w-[80ch] text-[13px] text-ink-2">{gen.authorship}</p>
          <ul className="mt-2 space-y-1 text-[13px] text-ink-2">
            {Object.entries(gen.by_kind).map(([k, v]) => (
              <li key={k}>
                <span className="text-ink">{k}</span>: {v.passed} of {v.evaluated ?? v.total} met{v.not_evaluated ? ` (${v.not_evaluated} not evaluated: provider unavailable)` : ""}
                {k === "generalization" ? " — the only rows that speak to generalization" : k === "known-defect-regression" ? " — regression tests, written after the defects were found" : " — design intent the author already knew"}
              </li>
            ))}
          </ul>
          {gen.results.filter((r) => !r.passed && !r.not_evaluated).length > 0 && (
            <ul className="mt-2 space-y-1 text-[12.5px] text-neg">
              {gen.results
                .filter((r) => !r.passed && !r.not_evaluated)
                .map((r) => (
                  <li key={r.id}>
                    <Mono>{r.id}</Mono> {r.purpose}: {r.mismatches.join("; ")}
                  </li>
                ))}
            </ul>
          )}
        </>
      )}

      <SectionHead title="Memory gain" aside="a recorded outcome becomes the next claim's precedent" />
      <ul className="space-y-2 text-[13.5px] text-ink-2">
        {systems.map((s) => {
          const mg = data.systems[s].memory_gain;
          if (!mg) return null;
          return (
            <li key={s} className="grid gap-x-4 border-b border-rule pb-2 sm:grid-cols-[220px_1fr]">
              <span className="font-medium text-ink">{SHORT[s] ?? s}</span>
              <span>
                {mg.before.accepted !== undefined
                  ? `Before: ${mg.before.disposition}, missing ${mg.before.missing?.join(", ") || "none"}. After: ${mg.after.disposition}, missing ${mg.after.missing?.join(", ") || "none"}. Support score ${pct(mg.after.confidence)} is not an approval probability.`
                  : `Before: ${mg.before.precedent_cases?.length ? mg.before.precedent_cases.join(", ") : "no precedent"}. After the case record is added: ${mg.after.precedent_cases?.join(", ") || "no precedent"}.`}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 max-w-[80ch] text-[12.5px] text-ink-3">
        The reviewer identifies the evidence present in a recorded synthetic outcome. ClaimBridge carries that observation into the next claim checklist.
        This demonstrates a changed checklist, not proof that the evidence caused an approval or that the change helps.
      </p>

      {claimIds.length > 0 && (
        <>
          <SectionHead title="Per-claim evidence" aside={operator ? "open a cell for the raw prediction and the expected answer" : "raw records are for operators"} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-[12.5px]">
              <thead>
                <tr className="border-b border-rule-2 text-left text-[11px] uppercase tracking-[0.06em] text-ink-3">
                  <th className="py-1.5 pr-3 font-medium">Claim</th>
                  <th className="py-1.5 pr-3 font-medium">Group</th>
                  {systems.map((s) => (
                    <th key={s} className="py-1.5 pl-3 text-center font-medium">
                      {(SHORT[s] ?? s).replace("ClaimBridge without memory", "No memory").replace("Plain RAG, large embeddings", "RAG large")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {claimIds.map((c) => (
                  <tr key={c} className="border-b border-rule">
                    <td className="py-1 pr-3">
                      <Mono className="text-ink">{c}</Mono>
                    </td>
                    <td className="py-1 pr-3 text-ink-3">{groupOf(c)}</td>
                    {systems.map((s) => {
                      const pc = data.systems[s].per_claim?.[c];
                      const failed = pc ? Object.entries(pc.checks).filter(([, ok]) => !ok).map(([k]) => k) : [];
                      const label = !pc ? "–" : pc.ok ? "✓" : "✗";
                      const title = !pc ? "no output" : pc.ok ? "fully correct" : `wrong: ${failed.join(", ")}`;
                      return (
                        <td key={s} className="py-1 pl-3 text-center">
                          {operator ? (
                            <a
                              href={`/api/eval/raw/${s}/${c}`}
                              target="_blank"
                              rel="noreferrer"
                              title={title}
                              className={`inline-block min-w-6 rounded-[5px] px-1.5 hover:bg-wash-2 ${pc?.ok ? "text-pos" : "text-neg"}`}
                            >
                              {label}
                            </a>
                          ) : (
                            <span title={title} className={pc?.ok ? "text-pos" : "text-neg"}>
                              {label}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <SectionHead title="Limits of this evaluation" />
      <ul className="max-w-[80ch] space-y-1 text-[13px] text-ink-2">
        <li>The data is synthetic; the expected answers are rules we wrote, in Python separate from the graph queries. That is not external validation.</li>
        <li>{data.scored_claims} claims is a small sample: one claim is about {Math.round(100 / (data.scored_claims ?? 34))} points.</li>
        <li>The baseline prompts were written once and not tuned per scenario.</li>
        <li>Baselines see only their own tenant&apos;s case records, so some expected precedents are out of their reach; the reachable-recall row accounts for that.</li>
        <li>Nothing here measures real-world appeal outcomes, or whether a changed checklist is useful.</li>
      </ul>
    </div>
  );
}
