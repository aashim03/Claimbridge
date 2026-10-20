"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { ApiError, getWith, post, type Memory, type Finding, type Overview } from "@/lib/api";
import { FINDING_STATUS, ago, pct } from "@/lib/vocab";
import { Treatment } from "./signal";
import { Button, ErrorNote, Mono, SectionHead } from "./ui";

import { useAccess } from "./session-gate";
import { ClauseImpactPanel } from "./graph-trace";
import { BlastRadiusPanel } from "./blast-panel";

const ALL_VERSIONS = ["2024", "2025", "2026"];
const STATUS_ORDER = ["ACTIVE", "STALE", "CONTRADICTED"];

function Versions({ f, present }: { f: Finding; present: string[] }) {
  return (
    <div className="flex gap-1" aria-label={`Applies in ${f.valid_in.join(", ") || "no version"}`}>
      {ALL_VERSIONS.filter((v) => present.includes(v)).map((v) => {
        const ok = f.valid_in.includes(v);
        return (
          <span
            key={v}
            className={`px-1.5 font-mono text-[11px] leading-[18px] tabular ${
              ok ? "rounded-[4px] border border-rule-2 bg-wash-2 text-ink" : "rounded-[4px] border border-dashed border-rule-2 text-ink-3 line-through"
            }`}
          >
            {v}
          </span>
        );
      })}
    </div>
  );
}

function WorldPanel({ memory, onChange }: { memory: Memory; onChange: () => void }) {
  const { data: ov, mutate } = useSWR<Overview>("/api/overview", { refreshInterval: 1500 });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [result, setResult] = useState<{ stale?: { finding_id: string; new_clause: string }[]; carried_forward?: string[] } | null>(null);
  const job = ov?.world_job;
  const running = job?.running;

  async function act(action: string, version?: string) {
    setBusy(action);
    setErr(null);
    setResult(null);
    try {
      const r = await post<{ result?: typeof result }>("/api/world", { action, version });
      if (action === "publish") setResult(r.result ?? null);
      await mutate();
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : e);
    } finally {
      setBusy(null);
    }
  }

  const present = memory.versions.map((v) => v.label);
  return (
    <section className="rounded-[12px] border border-rule bg-wash p-4">
      <h2 className="text-[14px] font-semibold">Policy world</h2>
      <ol className="mt-3 flex items-center gap-2">
        {ALL_VERSIONS.map((v, i) => (
          <li key={v} className="flex items-center gap-2">
            <span
              className={`rounded-[6px] px-2 py-0.5 font-mono text-[12px] tabular ${
                present.includes(v) ? "bg-ink text-paper" : "border border-dashed border-rule-2 text-ink-3"
              }`}
            >
              {v}
            </span>
            {i < ALL_VERSIONS.length - 1 && <span className="h-px w-5 bg-rule-2" aria-hidden />}
          </li>
        ))}
      </ol>
      <p className="mt-3 text-[12.5px] leading-relaxed text-ink-2">
        {memory.next_version
          ? `The ${memory.next_version.replace("V", "")} policy has not been published. Publishing it re-checks every precedent against the new clauses: those learned on a clause that changed become limited.`
          : "Every policy version is in force. Rewind to the 2025 world to watch the 2026 policy arrive and mark memory stale."}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {memory.next_version ? (
          <Button variant="primary" busy={busy === "publish"} disabled={!!running} onClick={() => act("publish", memory.next_version!)}>
            Publish the {memory.next_version.replace("V", "")} policy
          </Button>
        ) : (
          <Button busy={busy === "reset_2025" || (running && job?.action === "reset_2025")} disabled={!!running} onClick={() => act("reset_2025")}>
            Rewind to the 2025 world
          </Button>
        )}
        <Button variant="ghost" busy={running && job?.action === "reset"} disabled={!!running} onClick={() => act("reset")}>
          Reset demo
        </Button>
      </div>
      {running && <p className="mt-2 text-[12px] text-ink-3">Rebuilding the graph… about 20 seconds.</p>}
      {job?.error && <ErrorNote error={job.error} />}
      <ErrorNote error={err} />
      {result?.stale && (
        <div className="mt-3 border-t border-rule pt-3 text-[12.5px]">
          <p className="font-semibold text-ink">
            {result.stale.length} precedent{result.stale.length === 1 ? "" : "s"} limited, {result.carried_forward?.length ?? 0} carried forward
          </p>
          <ul className="mt-1 space-y-0.5">
            {result.stale.map((s) => (
              <li key={s.finding_id} className="flex items-center gap-1.5">
                <Treatment kind="caution" label="" size={12} />
                <Mono>{s.finding_id}</Mono>
                <span className="text-ink-3">superseded by</span>
                <Mono>{s.new_clause}</Mono>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

const TENANTS = [
  ["TEN-01", "Asha Varma"],
  ["TEN-03", "Carmen Ruiz"],
  ["TEN-05", "Elif Kaya"],
  ["TEN-07", "Grace Lin"],
  ["TEN-11", "Keiko Sato"],
];

function Privacy({ findings }: { findings: Finding[] }) {
  const [fid, setFid] = useState(findings.find((f) => f.finding_id === "F-CODING")?.finding_id ?? findings[0]?.finding_id);
  const { session } = useAccess();
  // A signed-in policyholder is fixed by the server; only an operator (or the public sandbox) can look at
  // the shared memory "as" another policyholder, and only an operator is told who the others are.
  const fixedTenant = session?.mode === "protected" ? (session.tenant_id ?? null) : null;
  const [picked, setTenant] = useState("TEN-03");
  const tenant = fixedTenant ?? picked;
  const { data } = useSWR<{ rows: { resolution_id: string; outcome: string; own: boolean; claim_id: string | null; service_date: number | null }[]; redacted: number }>(
    fid ? [`/api/memory/findings/${fid}/precedents`, tenant] : null,
    ([url, t]: [string, string]) => getWith(url, { "X-Tenant-Id": t }),
  );
  return (
    <section>
      <SectionHead title="Shared memory, private cases" aside="the precedent is shared; the cases behind it are not" />
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className="text-ink-2">Viewing</span>
        <select value={fid} onChange={(e) => setFid(e.target.value)} aria-label="Precedent" className="h-8 rounded-[8px] border border-rule bg-wash px-2 font-mono text-[12px] hover:border-rule-2">
          {findings.map((f) => (
            <option key={f.finding_id} value={f.finding_id}>
              {f.finding_id}
            </option>
          ))}
        </select>
        <span className="text-ink-2">as policyholder</span>
        {fixedTenant ? (
          <Mono className="text-ink">{fixedTenant} (you)</Mono>
        ) : (
          <select value={tenant} onChange={(e) => setTenant(e.target.value)} aria-label="Policyholder" className="h-8 rounded-[8px] border border-rule bg-wash px-2 hover:border-rule-2">
            {TENANTS.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        )}
      </div>
      <table className="mt-3 w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-rule-2 text-left text-[11.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">
            <th className="py-1.5 pr-4 font-semibold">Verified outcome</th>
            <th className="py-1.5 pr-4 font-semibold">Case</th>
            <th className="py-1.5 font-semibold">Visible to this policyholder</th>
          </tr>
        </thead>
        <tbody>
          {data?.rows.map((r) => (
            <tr key={r.resolution_id} className="border-b border-rule">
              <td className="py-2 pr-4">
                <Mono>{r.resolution_id}</Mono> · {r.outcome.toLowerCase()}
              </td>
              <td className="py-2 pr-4">{r.own ? <Mono className="text-ink">{r.claim_id}</Mono> : <span className="text-ink-3">withheld</span>}</td>
              <td className="py-2">
                {r.own ? <Treatment kind="positive" label="Their own case: full detail" size={12} /> : <Treatment kind="neutral" label="Another policyholder's case: outcome only" size={12} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && <p className="mt-2 text-[12px] text-ink-3">{data.redacted} of {data.rows.length} underlying cases withheld from this policyholder. The memory is shared; the cases behind it are not.</p>}
    </section>
  );
}

export function MemoryView() {
  const { operator } = useAccess();
  const { data, error, mutate } = useSWR<Memory>("/api/memory", { refreshInterval: 6000 });
  const grouped = useMemo(() => {
    const g: Record<string, Finding[]> = { ACTIVE: [], STALE: [], CONTRADICTED: [] };
    data?.findings.forEach((f) => (g[f.status] ??= []).push(f));
    return g;
  }, [data]);

  if (error) return <ErrorNote error={error} />;
  const present = data?.versions.map((v) => v.label) ?? [];
  const learned = data?.findings.filter((f) => f.origin === "learned") ?? [];

  return (
    <div className="mx-auto max-w-[1280px]">
      <h1 className="text-[26px] font-semibold leading-[1.15] tracking-[-0.03em]">Memory</h1>
      <p className="mt-1.5 max-w-[70ch] text-[13.5px] text-ink-2">
        Precedents distilled from verified outcomes. Each applies only in the policy versions whose clause it was learned on; later
        verified losses count against it.
      </p>

      <div className="mt-6 grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {!data && <div className="h-64 animate-pulse rounded-[12px] bg-wash" />}
          {data &&
            STATUS_ORDER.filter((s) => grouped[s]?.length).map((s, gi) => {
              const st = FINDING_STATUS[s];
              return (
                <section key={s}>
                  <SectionHead
                    top={gi === 0}
                    title={
                      <span className="inline-flex items-center gap-2">
                        <Treatment kind={st.signal} label={st.label} size={15} className="text-[17px] font-semibold" />
                        <span className="font-sans text-[13px] font-normal text-ink-3 tabular">{grouped[s].length}</span>
                      </span>
                    }
                    aside={st.why}
                  />
                  <ul>
                    {grouped[s].map((f) => (
                      <li key={f.finding_id} className="grid gap-x-6 gap-y-2 border-b border-rule py-3 sm:grid-cols-[1fr_auto]">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-baseline gap-x-2">
                            <Mono className="font-medium text-ink">{f.finding_id}</Mono>
                            {f.origin === "learned" && (
                              <span className="rounded-[4px] bg-link px-1.5 text-[10.5px] font-semibold uppercase leading-[17px] tracking-[0.06em] text-accent-ink">learned live</span>
                            )}
                            <span className="text-[12px] text-ink-3">
                              {f.reason_name} · §{f.section} {f.clause_title}
                            </span>
                          </div>
                          <p className="mt-1 max-w-[75ch] text-[14px] leading-snug text-ink">{f.statement}</p>
                          {f.stale_because.length > 0 && (
                            <p className="mt-1 text-[12.5px] text-caution-ink">
                              Superseded by <Mono>{f.stale_because.join(", ")}</Mono>; still applies to claims under {f.valid_in.join(" and ")}.
                            </p>
                          )}
                          {f.contradictions > 0 && (
                            <p className={`mt-1 text-[12.5px] ${f.status === "CONTRADICTED" ? "text-neg" : "text-caution-ink"}`}>
                              {f.contradictions} verified loss{f.contradictions === 1 ? "" : "es"} under the same conditions.
                            </p>
                          )}
                          {f.playbook && <p className="mt-1 text-[12px] text-ink-3">Recommends: {f.playbook}</p>}
                        </div>
                        <div className="flex flex-col gap-1.5 text-[12px] text-ink-3 sm:items-end">
                          <Versions f={f} present={present} />
                          <span className="tabular">
                            {f.wins} recorded win{f.wins === 1 ? "" : "s"} · {f.contradictions} contradicted · {f.wins > 0 ? `support score ${pct(f.confidence)}` : "no supporting outcomes yet"}
                          </span>
                          {f.updated_at ? <span>updated {ago(f.updated_at)}</span> : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}

          {data && <Privacy findings={data.findings} />}

          {data && <ClauseImpactPanel />}

          {data && <BlastRadiusPanel />}

          {data && (
            <section>
              <SectionHead title="Playbooks" aside="procedural memory: what worked, counted from verified outcomes" />
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-rule-2 text-left text-[11.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                    <th className="py-1.5 pr-4 font-semibold">Playbook</th>
                    <th className="py-1.5 pr-4 font-semibold">Steps</th>
                    <th className="py-1.5 text-right font-semibold">Won / used</th>
                  </tr>
                </thead>
                <tbody>
                  {data.playbooks.map((p) => (
                    <tr key={p.playbook_id} className="border-b border-rule align-top">
                      <td className="py-2 pr-4 font-medium text-ink">{p.name}</td>
                      <td className="py-2 pr-4 text-ink-2">
                        <ol className="list-decimal pl-4">
                          {p.steps.map((s) => (
                            <li key={s}>{s}</li>
                          ))}
                        </ol>
                      </td>
                      <td className="py-2 text-right tabular">
                        {p.wins} / {p.uses}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>

        <aside className="space-y-6 lg:sticky lg:top-6 lg:self-start">
          {data && operator && <WorldPanel memory={data} onChange={() => mutate()} />}
          {data && (
            <section className="rounded-[12px] border border-rule bg-wash p-4 text-[12.5px] text-ink-2">
              <h2 className="mb-2 text-[14px] font-semibold text-ink">Learned in this session</h2>
              {learned.length ? (
                <ul className="space-y-1">
                  {learned.map((f) => (
                    <li key={f.finding_id}>
                      <Mono className="text-ink">{f.finding_id}</Mono> · {f.wins} win{f.wins === 1 ? "" : "s"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-ink-3">
                  Nothing yet. Approve a claim and record its outcome as overturned: the Curator turns it into a precedent the next claim can
                  cite.
                </p>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
