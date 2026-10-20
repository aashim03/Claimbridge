"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { ChevronLeft, ChevronDown, ChevronRight } from "lucide-react";
import { post, type ClaimDetail, type GraphEdge, type GraphNode, type Verdict } from "@/lib/api";
import { DISPOSITION, STATUS_LABEL, TRAPS, TREATMENT, ago, fmtDate, humanEvent, pct } from "@/lib/vocab";
import { SUPPORT_NOTE, conditionFailure, originLine, requirementOrigin, supportView } from "@/lib/explain";
import { GraphReplay } from "./graph-replay";
import { PrecedentPath } from "./graph-trace";
import { InvestigatePanel } from "./investigate-panel";
import { EvidenceManager, ReclassifyForm } from "./human-actions";
import { SignalMark, Treatment } from "./signal";
import { Button, Cite, ErrorNote, Mono, SectionHead } from "./ui";

import { useAccess } from "./session-gate";

const KIND_LABEL: Record<string, string> = {
  EVIDENCE_NEEDED: "Evidence",
  ACTION: "Next step",
  WARNING: "Warning",
  REJECTED_PRECEDENT: "Do not rely",
};

const VERDICT_ORDER = ["ACCEPTED", "VERSION_DRIFT", "CONTRADICTED", "CONDITION_UNMET", "LINEAGE_MISMATCH", "CANDIDATE", "REASON_MISMATCH"];

const yearOf = (clauseId?: string | null) => clauseId?.match(/C-(\d{4})-/)?.[1] ?? "";

// The Planner states uncertainty with node IDs; show it in citation words, IDs second.
function uncertaintyLine(u: string, verdicts: Verdict[]): { text: string; ids?: string } {
  const drift = u.match(/^(F-[\w-]+) was learned under (C-\d{4}-[\w-]+); (C-\d{4}-[\w-]+) governs this claim\.$/);
  if (drift) {
    const v = verdicts.find((x) => x.finding_id === drift[1]);
    return {
      text: `${drift[1]}: superseded by §${v?.learned_section ?? ""} (${yearOf(drift[3])}); it was learned under the ${yearOf(drift[2])} clause.`,
      ids: `${drift[2]} → ${drift[3]}`,
    };
  }
  const contra = u.match(/^(F-[\w-]+) was contradicted by later verified cases \((.+)\)\.$/);
  if (contra) {
    const n = contra[2].split(",").length;
    return { text: `${contra[1]}: contradicted by ${n} later verified appeal${n === 1 ? "" : "s"} upheld on the same facts.`, ids: contra[2] };
  }
  return { text: u };
}

// The citation line, in words first: "Superseded by §4.2 (2026)". Node IDs follow in mono.
function groundsLine(v: Verdict, claim: ClaimDetail["claim"]): { text: string; ids: string[] } {
  switch (v.code) {
    case "VERSION_DRIFT":
      return {
        text: `Superseded by §${v.learned_section} (${yearOf(v.governing)}). Learned under the ${yearOf(v.learned_on)} clause, which the policy in force has since changed.`,
        ids: [v.learned_on, v.governing ?? ""].filter(Boolean),
      };
    case "CONTRADICTED":
      return {
        text: `Contradicted: ${v.contradicted_by.length} later verified appeal${v.contradicted_by.length === 1 ? " was" : "s were"} upheld on the same facts.`,
        ids: v.contradicted_by,
      };
    case "CONDITION_UNMET":
      return { text: `Distinguished: ${conditionFailure(v, claim)}.`, ids: [] };
    case "LINEAGE_MISMATCH":
      return {
        text: `Distinguished: it concerns §${v.learned_section}, a different clause from the one this denial cites.`,
        ids: [v.learned_on],
      };
    case "ACCEPTED":
      return { text: `Applicable precedent under the policy in force (valid in ${v.valid_in.join(", ")}).`, ids: [v.learned_on] };
    default:
      return { text: TREATMENT[v.code]?.why ?? "", ids: [] };
  }
}

function PrecedentRow({ v, claim, hot, onHover }: { v: Verdict; claim: ClaimDetail["claim"]; hot: boolean; onHover: (id: string | null) => void }) {
  const t = TREATMENT[v.code] ?? TREATMENT.CANDIDATE;
  const grounds = groundsLine(v, claim);
  return (
    <li
      id={`p-${v.finding_id}`}
      className={`grid scroll-mt-24 grid-cols-[132px_1fr] gap-x-4 border-b border-rule px-4 py-3.5 transition-colors last:border-0 sm:grid-cols-[150px_1fr_auto] ${
        hot ? "bg-[#161a2b] shadow-[inset_2px_0_0_var(--link)]" : ""
      }`}
      onMouseEnter={() => onHover(v.finding_id)}
      onMouseLeave={() => onHover(null)}
    >
      <div className="pt-0.5">
        <Treatment kind={t.signal} label={t.label} />
        <Mono className="mt-1 block text-ink-3">{v.finding_id}</Mono>
      </div>
      <div className="min-w-0">
        <p className="text-[14px] leading-snug text-ink">{v.statement}</p>
        <p className={`mt-1 text-[13px] ${t.signal === "negative" ? "text-neg" : t.signal === "caution" ? "text-caution-ink" : "text-ink-2"}`}>
          {grounds.text}
        </p>
        {grounds.ids.length > 0 && <Mono className="mt-0.5 block text-ink-3">{grounds.ids.join(" → ")}</Mono>}
        {v.code !== "REASON_MISMATCH" && <PrecedentPath cid={claim.claim_id} fid={v.finding_id} />}
      </div>
      <div className="col-start-2 mt-1 text-[12px] text-ink-3 sm:col-start-3 sm:mt-0 sm:text-right">
        <div className="tabular">
          {v.support} recorded win{v.support === 1 ? "" : "s"} · {v.contradicted_by.length} contradicted
        </div>
        <div className="tabular">{v.support > 0 ? `support score ${pct(v.confidence)}` : "no supporting outcomes yet"}</div>
        <div>via {v.source}</div>
      </div>
    </li>
  );
}

function ActionPanel({ d, cid, onDone }: { d: ClaimDetail; cid: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const status = d.claim.status as string;
  const { operator } = useAccess();
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const owner = d.claim.lease_owner as string | undefined;
  const last = d.timeline[d.timeline.length - 1];

  async function act(name: string, url: string, body: object) {
    setBusy(name);
    setErr(null);
    try {
      await post(url, body);
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  let body: React.ReactNode;
  if (status === "NEW") {
    body = (
      <>
        <p className="text-[13px] text-ink-2">This claim has not been filed. Filing hands it to the Intake agent.</p>
        <Button variant="accent" className="mt-3 w-full" busy={busy === "file"} onClick={() => act("file", "/api/claims/inject", { ids: [cid] })}>
          File claim
        </Button>
      </>
    );
  } else if (status === "AWAITING_REVIEW") {
    body = (
      <>
        <p className="text-[13px] text-ink-2">Approve this recommendation for human follow-up. ClaimBridge does not send an appeal to the insurer.</p>
        <Button variant="primary" className="mt-3 w-full" busy={busy === "approve"} onClick={() => act("approve", `/api/claims/${cid}/approve`, {})}>
          Approve recommendation
        </Button>
      </>
    );
  } else if (status === "APPROVED" && !operator) {
    body = <p className="text-sm text-ink-2">Approved for follow-up. An operator must verify and record the insurer outcome.</p>;
  } else if (status === "APPROVED") {
    body = (
      <>
        <p className="text-[13px] text-ink-2">
          When the insurer answers the appeal, record what happened. The Curator turns it into memory for the next claim.
        </p>
        <fieldset className="mt-3 space-y-1 text-xs text-ink-2">
          <legend className="mb-2">Which documents did the decision rely on, as far as you saw?</legend>
          {d.evidence.map(e => <label key={e.code} className="flex items-center gap-2">
            <input type="checkbox" checked={confirmed.includes(e.code)} onChange={() => setConfirmed(prev => prev.includes(e.code) ? prev.filter(x => x !== e.code) : [...prev, e.code])} />
            {e.name}
          </label>)}
          <p className="pt-1 text-ink-3">
            Tick only what you actually observed. If you tick nothing, memory records the documents that were on file as an association, not proof
            that any of them caused the outcome.
          </p>
        </fieldset>
        <div className="mt-3 grid grid-cols-3 gap-1.5">
          {[
            ["OVERTURNED", "Overturned"],
            ["PARTIAL", "Partial"],
            ["UPHELD", "Upheld"],
          ].map(([o, l]) => (
            <Button
              key={o}
              variant={o === "UPHELD" ? "danger" : o === "OVERTURNED" ? "primary" : "secondary"}
              busy={busy === o}
              onClick={() => act(o, `/api/claims/${cid}/outcome`, { outcome: o, confirmed_evidence: confirmed.length ? confirmed : null })}
            >
              {l}
            </Button>
          ))}
        </div>
      </>
    );
  } else if (status === "CURATED") {
    const p = (last?.payload ?? {}) as { action?: string; outcome?: string; findings?: { finding_id: string; confidence?: number; status?: string }[] };
    body = (
      <p className="text-[13px] text-ink-2">
        Outcome <strong className="text-ink">{p.outcome?.toLowerCase()}</strong>. Memory{" "}
        {p.action === "learned" ? "learned a new precedent" : p.action === "strengthened" ? "strengthened a precedent" : p.action === "contradicted" ? "recorded a contradiction against" : "was unchanged"}
        {p.findings?.length ? (
          <>
            {": "}
            {p.findings.map((f) => (
              <Link key={f.finding_id} href="/console/memory" className="font-mono text-[12px] text-link underline">
                {f.finding_id}
              </Link>
            ))}
          </>
        ) : null}
        .
      </p>
    );
  } else if (status === "NEEDS_HUMAN") {
    body = <ReclassifyForm d={d} onDone={onDone} operator={operator} />;
  } else {
    body = (
      <p className="text-[13px] text-ink-2">
        {owner ? (
          <>
            <span className="font-medium text-link">{owner}</span> is working on it now.
          </>
        ) : (
          <>Waiting for the next free agent.</>
        )}{" "}
        The graph replay plays each step as the agent commits it.
      </p>
    );
  }

  return (
    <section className="rounded-[12px] border border-rule bg-wash p-4">
      <h2 className="flex items-center justify-between gap-2 text-[14px] font-semibold">
        <span className="flex items-center gap-2">
          {owner && <span className="live-dot size-1.5 rounded-full bg-link" aria-hidden />}
          {STATUS_LABEL[status] ?? status}
        </span>
        {d.recommendation?.approved_by && <span className="text-[11.5px] font-normal text-ink-3">approved by {d.recommendation.approved_by}</span>}
      </h2>
      <div className="mt-2">{body}</div>
      <ErrorNote error={err} />
    </section>
  );
}

function AgentRecord({ d }: { d: ClaimDetail }) {
  if (!d.timeline.length) return <p className="px-4 py-4 text-[13px] text-ink-3">No agent has touched this claim yet.</p>;
  return (
    <ol className="px-4 py-3">
      {d.timeline.map((e) => {
        const alarm = e.type === "RESUMED" || e.type === "LEASE_EXPIRED" || e.type === "FENCED_WRITE_REJECTED";
        const extra =
          e.type === "RESUMED"
            ? `after ${(e.payload.previous_owner as string) ?? "a failed worker"}`
            : e.type === "INTAKE_DONE"
              ? `${e.payload.reason ?? ""} · ${e.payload.method === "llm" ? "read by LLM" : e.payload.method === "cited_section" ? "from cited section" : "by similarity"}`
              : e.type === "PLANNER_DONE"
                ? `${(e.payload.items as number) ?? ""} items`
                : e.type === "OUTCOME_RECORDED"
                  ? String(e.payload.outcome ?? "").toLowerCase()
                  : "";
        return (
          <li key={e.seq} className="grid grid-cols-[14px_1fr] gap-x-2.5 pb-3">
            <span
              className={`mt-[7px] size-[7px] rounded-full ${alarm ? "bg-caution" : e.type.endsWith("_DONE") ? "bg-ink-2" : "bg-rule-2"}`}
              aria-hidden
            />
            <div className="min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <span className={`text-[13px] ${alarm ? "font-semibold text-caution-ink" : "text-ink"}`}>{humanEvent(e.type)}</span>
                <span className="shrink-0 text-[11.5px] text-ink-3 tabular">{ago(e.ts)}</span>
              </div>
              <div className="truncate text-[12px] text-ink-3">
                <Mono>{e.agent}</Mono>
                {extra ? ` · ${extra}` : ""}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

type Tab = "graph" | "plan" | "precedents" | "evidence" | "investigate" | "record";

export function CaseView() {
  const { id } = useParams<{ id: string }>();
  const { data: d, error, mutate } = useSWR<ClaimDetail>(`/api/claims/${id}`, { refreshInterval: 5000 });
  const { data: g, mutate: mutateGraph } = useSWR<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/api/claims/${id}/graph`, {
    refreshInterval: 5000,
  });
  const [hot, setHot] = useState<string | null>(null);
  const [showIrrelevant, setShowIrrelevant] = useState(false);
  const [tab, setTab] = useState<Tab>("graph");
  const [jump, setJump] = useState<string | null>(null);
  const { operator } = useAccess();

  // A citation clicked in the plan opens the precedent it names.
  useEffect(() => {
    if (tab !== "precedents" || !jump) return;
    document.getElementById(`p-${jump}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(() => (setHot(null), setJump(null)), 1800);
    return () => clearTimeout(t);
  }, [tab, jump]);

  if (error)
    return (
      <div className="mx-auto max-w-[1400px]">
        <ErrorNote error={error} />
      </div>
    );
  if (!d)
    return (
      <div className="mx-auto max-w-[1400px] space-y-3">
        <div className="h-5 w-40 animate-pulse rounded bg-wash" />
        <div className="h-9 w-2/3 animate-pulse rounded bg-wash" />
        <div className="h-72 animate-pulse rounded-[12px] bg-wash" />
      </div>
    );

  const c = d.claim;
  const rec = d.recommendation;
  const disp = rec ? DISPOSITION[rec.disposition] : null;
  const verdicts = [...d.verdicts].sort((a, b) => VERDICT_ORDER.indexOf(a.code) - VERDICT_ORDER.indexOf(b.code));
  const relevant = verdicts.filter((v) => v.code !== "REASON_MISMATCH");
  const irrelevant = verdicts.filter((v) => v.code === "REASON_MISMATCH");
  const missing = d.requirements.filter((r) => !r.satisfied);
  const noBasis = rec?.disposition === "NO_BASIS_ESCALATE";
  const refresh = () => {
    mutate();
    mutateGraph();
  };
  const byFinding = new Map(d.verdicts.map((v) => [v.finding_id, v]));

  const TABS: { id: Tab; label: string; n?: number }[] = [
    { id: "graph", label: "Graph replay" },
    { id: "plan", label: "Plan", n: rec?.items.length },
    { id: "precedents", label: "Precedents", n: relevant.length || undefined },
    { id: "evidence", label: "Evidence", n: noBasis ? undefined : missing.length || undefined },
    { id: "investigate", label: "Investigate" },
    { id: "record", label: "Agent record", n: d.timeline.length || undefined },
  ];

  return (
    <div className="mx-auto max-w-[1400px]">
      <Link href="/console" className="inline-flex items-center gap-1 text-[12.5px] text-ink-3 hover:text-ink">
        <ChevronLeft size={14} aria-hidden /> Docket
      </Link>

      {rec && <a href={`/api/claims/${encodeURIComponent(id)}/packet`} download
        className="ml-5 inline-flex text-[12.5px] font-medium text-link hover:underline">Download review packet</a>}

      <header className="mt-3 grid gap-x-8 gap-y-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <Mono className="rounded-[5px] border border-rule-2 bg-wash px-1.5 py-0.5 text-ink">{c.claim_id}</Mono>
            {d.trap && TRAPS[d.trap] && (
              <span className="rounded-[5px] border border-rule bg-wash px-1.5 py-0.5 text-ink-2">
                {d.trap} · {TRAPS[d.trap].name}
              </span>
            )}
          </div>
          <h1 className="mt-3 max-w-[32ch] text-[28px] font-semibold leading-[1.12] tracking-[-0.03em]">
            {d.service}
            <span className="mt-1 block text-[18px] font-normal leading-tight tracking-[-0.015em] text-ink-2">
              {d.reason_name ? `Denied: ${d.reason_name.toLowerCase()}` : "Denial being read"}
            </span>
          </h1>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[12.5px] text-ink-2">
            <div className="flex gap-1.5">
              <dt className="text-ink-3">Policyholder</dt>
              <dd>{d.tenant}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-3">Service date</dt>
              <dd className="tabular">{fmtDate(c.service_date)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-3">Filed</dt>
              <dd className="tabular">{c.filing_lag_days} days later</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-3">Governing policy</dt>
              <dd>{d.version ? `LumenCare Silver ${d.version.label}` : "being determined"}</dd>
            </div>
            {d.clause && (
              <div className="flex gap-1.5">
                <dt className="text-ink-3">Denial cites</dt>
                <dd>
                  §{d.clause.section} {d.clause.title}
                </dd>
              </div>
            )}
            <div className="flex gap-1.5">
              <dt className="text-ink-3">Emergency</dt>
              <dd>{c.is_emergency ? "yes" : "no"}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-3">In network</dt>
              <dd>{c.in_network ? "yes" : "no"}</dd>
            </div>
          </dl>
          {d.trap && TRAPS[d.trap] && <p className="mt-2 max-w-[90ch] text-[12.5px] text-ink-3">{d.note ?? TRAPS[d.trap].line}</p>}
        </div>
        <ActionPanel d={d} cid={id} onDone={refresh} />
      </header>

      {/* Holding: the answer first. */}
      <section className="mt-6 rounded-[12px] border border-rule bg-wash px-5 py-4">
        {rec && disp ? (
          <div className="grid gap-x-8 gap-y-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="min-w-0">
              <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Holding</p>
              <p className="mt-1.5 flex items-center gap-2.5 text-[20px] font-semibold leading-tight tracking-[-0.02em]">
                <SignalMark kind={disp.tone} size={18} className="stamp" />
                {disp.label}
              </p>
              <p className="mt-2 max-w-[80ch] text-[14px] leading-relaxed text-ink-2">{rec.summary}</p>
              {rec.uncertainty?.length > 0 && (
                <ul className="mt-3 space-y-1" aria-label="Caveats">
                  {rec.uncertainty.map((u) => {
                    const line = uncertaintyLine(u, d.verdicts);
                    return (
                      <li key={u} className="flex gap-2 text-[12.5px] text-ink-2">
                        <span className="mt-[9px] h-px w-3 shrink-0 bg-ink-3" aria-hidden />
                        <span>
                          {line.text}
                          {line.ids && <Mono className="ml-1.5 text-ink-3">{line.ids}</Mono>}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <dl className="grid grid-cols-[auto_auto] content-start gap-x-4 gap-y-1 text-[12.5px] md:text-right">
              <dt className="text-ink-3">Support score</dt>
              <dd className="font-medium text-ink tabular" title={supportView(rec, d.verdicts).detail}>
                {supportView(rec, d.verdicts).value}
              </dd>
              {supportView(rec, d.verdicts).detail && (
                <>
                  <dt className="text-ink-3">Observed</dt>
                  <dd className="text-ink-2">{supportView(rec, d.verdicts).detail}</dd>
                </>
              )}
              <dt className="text-ink-3">Citation guard</dt>
              <dd className="text-ink-2 tabular">
                {rec.guard_dropped || rec.guard_added ? `−${rec.guard_dropped} / +${rec.guard_added}` : "all cited"}
              </dd>
              {(
                <>
                  <dt className="text-ink-3">Published plan</dt>
                  <dd className="text-ink-2">Graph templates</dd>
                </>
              )}
            </dl>
            <p className="text-[11.5px] leading-snug text-ink-3 md:col-span-2">{SUPPORT_NOTE}</p>
          </div>
        ) : (
          <p className="text-[13.5px] text-ink-3">
            <span className="font-medium text-ink-2">No holding yet.</span> The Planner writes one after the Verifier has ruled on every
            precedent. Watch it happen in the replay below.
          </p>
        )}
      </section>

      <div className="mt-6 overflow-x-auto border-b border-rule" role="tablist" aria-label="Case sections">
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              onClick={() => setTab(t.id)}
              className={`relative -mb-px flex h-10 shrink-0 items-center gap-1.5 border-b-2 px-3 text-[13px] transition-colors ${
                tab === t.id ? "border-ink font-medium text-ink" : "border-transparent text-ink-3 hover:text-ink-2"
              }`}
            >
              {t.label}
              {t.n ? <span className="rounded-[5px] bg-wash-2 px-1.5 font-mono text-[10.5px] leading-[17px] text-ink-2">{t.n}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-5">
        {tab === "graph" &&
          (g && g.nodes.length > 0 ? (
            <GraphReplay key={id} detail={d} graph={g} />
          ) : (
            <p className="text-[13.5px] text-ink-3">The graph fills in as the agents work.</p>
          ))}

        {tab === "investigate" && <InvestigatePanel claimId={id} onShowGraph={() => setTab("graph")} />}

        {tab === "plan" &&
          (rec && rec.items.length > 0 ? (
            <div className="rounded-[12px] border border-rule bg-wash">
              <p className="border-b border-rule px-4 py-2.5 text-[12px] text-ink-3">
                Each item names the graph nodes it rests on. Click a precedent ID to open it.
              </p>
              <ol>
                {rec.items.map((it) => (
                  <li key={it.order} className="grid grid-cols-[30px_1fr] gap-x-2 border-b border-rule px-4 py-3 last:border-b-0">
                    <span className="font-mono text-[12.5px] text-ink-3 tabular">{String(it.order).padStart(2, "0")}</span>
                    <div>
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span
                          className={`text-[11px] font-semibold uppercase tracking-[0.06em] ${
                            it.kind === "REJECTED_PRECEDENT" || it.kind === "WARNING" ? "text-neg" : "text-ink-3"
                          }`}
                        >
                          {KIND_LABEL[it.kind] ?? it.kind}
                        </span>
                        <span className="text-[14px] text-ink">{it.text}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {it.cites.map((x) => {
                          const v = byFinding.get(x);
                          return (
                            <Cite
                              key={x}
                              id={x}
                              active={hot === x}
                              onHover={setHot}
                              title={v ? `${TREATMENT[v.code]?.label ?? v.code}: ${v.statement}` : undefined}
                              onClick={v ? () => (setJump(x), setHot(x), setTab("precedents")) : undefined}
                            />
                          );
                        })}
                        {it.origin === "template" && <span className="text-[11px] text-ink-3">added by the citation guard</span>}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <p className="text-[13.5px] text-ink-3">The plan appears once the Planner has written it.</p>
          ))}

        {tab === "precedents" && (
          <>
            {relevant.length ? (
              <>
                <p className="mb-3 text-[12.5px] text-ink-3">
                  {relevant.filter((v) => v.code === "ACCEPTED").length} followed ·{" "}
                  {relevant.filter((v) => v.code !== "ACCEPTED").length} refused or distinguished
                </p>
                <ul className="rounded-[12px] border border-rule bg-wash">
                  {relevant.map((v) => (
                    <PrecedentRow key={v.finding_id} v={v} claim={c} hot={hot === v.finding_id} onHover={setHot} />
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-[13.5px] text-ink-3">
                {["NEW", "RECEIVED", "CLASSIFIED"].includes(c.status)
                  ? "Precedents appear once Retrieval has searched memory."
                  : "No precedent in memory applies to this claim."}
              </p>
            )}
            {irrelevant.length > 0 && (
              <button
                className="mt-3 inline-flex items-center gap-1 text-[12.5px] text-ink-3 hover:text-ink"
                onClick={() => setShowIrrelevant(!showIrrelevant)}
                aria-expanded={showIrrelevant}
              >
                {showIrrelevant ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                {irrelevant.length} look-alike{irrelevant.length === 1 ? "" : "s"} found by text similarity, not relevant
              </button>
            )}
            {showIrrelevant && (
              <ul className="mt-2 rounded-[12px] border border-rule bg-wash">
                {irrelevant.map((v) => (
                  <PrecedentRow key={v.finding_id} v={v} claim={c} hot={hot === v.finding_id} onHover={setHot} />
                ))}
              </ul>
            )}
          </>
        )}

        {tab === "evidence" && (
          <div className="grid gap-x-8 gap-y-6 lg:grid-cols-[minmax(0,1fr)_380px]">
            <div className="min-w-0">
              <SectionHead
                top
                title="Evidence"
                aside={noBasis ? "not needed: there is no basis for an appeal" : missing.length ? `${missing.length} missing` : d.requirements.length ? "all on file" : undefined}
              />
              <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <div>
                  <h3 className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Evidence checklist</h3>
                  <ul className="mt-1.5">
                    {d.requirements.length ? (
                      d.requirements.map((r) => {
                        const origin = requirementOrigin(r);
                        return (
                          <li key={r.code} className="border-b border-rule py-2 text-[13px]">
                            <div className="flex items-center justify-between gap-3">
                              <span>{r.name}</span>
                              {r.satisfied ? (
                                <Treatment kind="positive" label="On file" size={12} />
                              ) : noBasis ? (
                                <Treatment kind="neutral" label="Not needed" size={12} />
                              ) : (
                                <Treatment kind="negative" label="Missing" size={12} />
                              )}
                            </div>
                            <p className="mt-1 text-[11.5px] leading-snug text-ink-3">
                              <span className={origin === "learned" ? "text-link" : "text-ink-2"}>
                                {origin === "learned" ? "Suggested" : origin === "both" ? "Required and suggested" : "Required"}
                              </span>
                              {" · "}
                              {originLine(r, d.clause?.section)}
                            </p>
                          </li>
                        );
                      })
                    ) : (
                      <li className="py-2 text-[13px] text-ink-3">Nothing required, or not yet determined.</li>
                    )}
                  </ul>
                </div>
                <div>
                  <h3 className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Documents on file</h3>
                  <div className="mt-1.5">
                    <EvidenceManager d={d} operator={operator} onDone={refresh} />
                  </div>
                </div>
              </div>
              <SectionHead title="Denial notice" aside={`issued ${fmtDate(d.notice_date)}`} />
              <blockquote className="max-w-[78ch] border-l-2 border-rule-2 pl-4 text-[14px] leading-relaxed text-ink-2">{d.notice}</blockquote>
            </div>
            {d.clause && (
              <section className="self-start rounded-[12px] border border-rule bg-wash p-4">
                <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Clause the denial cites</p>
                <h2 className="mt-1.5 text-[15px] font-semibold">
                  §{d.clause.section} {d.clause.title}
                </h2>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{d.clause.text}</p>
                <p className="mt-2 text-[11.5px] text-ink-3">
                  <Mono>{d.clause.clause_id}</Mono> · in force from {fmtDate(d.version?.effective_from)}
                </p>
              </section>
            )}
          </div>
        )}

        {tab === "record" && (
          <div className="max-w-[720px] rounded-[12px] border border-rule bg-wash">
            <AgentRecord d={d} />
          </div>
        )}
      </div>
    </div>
  );
}
