"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowRight, Plus, Search, X } from "lucide-react";
import { post, type ClaimRow } from "@/lib/api";
import {
  DISPOSITION,
  STATUS_LABEL,
  STATUS_ORDER,
  STEPS,
  TRAPS,
  TREATMENT,
  ago,
  fmtDate,
  stepIndex,
} from "@/lib/vocab";
import { NewClaim } from "./new-claim";
import { SignalMark, Treatment } from "./signal";
import { Button, Empty, ErrorNote } from "./ui";

const GROUPS = [
  { id: "T1", label: "T1 · Version drift" },
  { id: "T2", label: "T2 · Wrong clause" },
  { id: "T3", label: "T3 · Missing evidence" },
  { id: "T4", label: "T4 · Contradicted memory" },
  { id: "T5", label: "T5 · Condition unmet" },
  { id: "T6", label: "T6 · No basis" },
  { id: "T7", label: "T7 · Tenant isolation" },
  { id: "M", label: "M · Memory gain" },
  { id: "normal", label: "Routine claims" },
  { id: "all", label: "Every claim" },
];

const LEDGER = ["NEW", "RECEIVED", "CLASSIFIED", "RETRIEVED", "VERIFIED", "AWAITING_REVIEW", "APPROVED", "CURATED", "NEEDS_HUMAN"];

const SELECT =
  "h-8 rounded-[8px] border border-rule bg-wash px-2 text-[13px] text-ink hover:border-rule-2 focus:border-rule-2 focus:outline-none";

function StepTrack({ row, wide = false }: { row: ClaimRow; wide?: boolean }) {
  const idx = stepIndex(row.status);
  const working = row.lease_owner;
  return (
    <div className={`flex flex-col gap-1 ${wide ? "" : "min-w-[140px]"}`}>
      <div className="flex gap-[3px]" aria-hidden>
        {STEPS.map((s) => {
          const at = STATUS_ORDER.indexOf(s.status);
          const done = idx > at;
          const current = at === idx;
          return (
            <span
              key={s.status}
              className={`h-[4px] flex-1 rounded-full ${
                row.status === "NEEDS_HUMAN"
                  ? "bg-neg"
                  : done || (current && row.status === "AWAITING_REVIEW")
                    ? "bg-ink-2"
                    : current && working
                      ? "live-dot bg-link"
                      : "bg-wash-2"
              }`}
            />
          );
        })}
      </div>
      <span key={row.status + (working ?? "")} className="turn text-[12px] text-ink-2">
        {working ? (
          <>
            <span className="text-link">{working}</span> working
          </>
        ) : (
          STATUS_LABEL[row.status] ?? row.status
        )}
      </span>
    </div>
  );
}

function CitatorStrip({ flags }: { flags: ClaimRow["flags"] }) {
  if (!flags.length) return <span className="text-[12px] text-ink-3">—</span>;
  const tally = { negative: 0, caution: 0, positive: 0, neutral: 0 };
  flags.forEach((f) => (tally[TREATMENT[f.code]?.signal ?? "neutral"] += 1));
  const parts = [
    tally.negative && `${tally.negative} refused`,
    tally.caution && `${tally.caution} distinguished`,
    tally.positive && `${tally.positive} followed`,
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-1">
        {flags.map((f) => {
          const t = TREATMENT[f.code] ?? TREATMENT.CANDIDATE;
          return (
            <span key={f.finding_id} title={`${f.finding_id}: ${t.label}. ${t.why}`}>
              <SignalMark kind={t.signal} size={13} />
            </span>
          );
        })}
      </div>
      <span className="text-[11.5px] text-ink-3">{parts.join(" · ")}</span>
    </div>
  );
}

function Preview({ row, onClose, onFile, busy }: { row: ClaimRow; onClose: () => void; onFile: () => void; busy: boolean }) {
  const d = row.disposition ? DISPOSITION[row.disposition] : null;
  const trap = row.trap ? TRAPS[row.trap] : null;
  return (
    <aside
      aria-label={`Preview of ${row.claim_id}`}
      className="sticky top-[72px] hidden max-h-[calc(100dvh-96px)] w-[340px] shrink-0 overflow-y-auto rounded-[12px] border border-rule bg-wash xl:block"
    >
      <div className="flex items-start justify-between gap-3 border-b border-rule px-5 py-4">
        <div className="min-w-0">
          <p className="font-mono text-[13px] font-medium text-ink">{row.claim_id}</p>
          <p className="mt-0.5 truncate text-[12px] text-ink-3">{row.tenant}</p>
        </div>
        <button onClick={onClose} aria-label="Close preview" className="rounded-[6px] p-1 text-ink-3 hover:bg-wash-2 hover:text-ink">
          <X size={15} />
        </button>
      </div>
      <div className="space-y-5 px-5 py-4 text-[13px]">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
          <dt className="text-ink-3">Service</dt>
          <dd className="text-ink">{row.service_name}</dd>
          <dt className="text-ink-3">Denial</dt>
          <dd className="text-ink">{row.reason_name ?? "Not read yet"}</dd>
          <dt className="text-ink-3">Date</dt>
          <dd className="text-ink tabular">{fmtDate(row.service_date)}</dd>
          <dt className="text-ink-3">Updated</dt>
          <dd className="text-ink-2 tabular">{ago(row.updated_at)}</dd>
        </dl>
        {trap && (
          <div className="rounded-[8px] border border-rule bg-paper px-3 py-2.5">
            <p className="text-[12px] font-medium text-ink">
              {row.trap} · {trap.name}
            </p>
            <p className="mt-0.5 text-[12px] leading-snug text-ink-3">{trap.line}</p>
          </div>
        )}
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Progress</p>
          {row.status === "NEW" ? <span className="text-[12.5px] text-ink-3">Not filed yet</span> : <StepTrack row={row} wide />}
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Precedents</p>
          <CitatorStrip flags={row.flags} />
        </div>
        {d && (
          <div>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Disposition</p>
            <Treatment kind={d.tone} label={d.short} size={12} />
            {row.confidence != null && row.flags.some((f) => f.code === "ACCEPTED") && (
              <span className="ml-2 text-[12px] text-ink-3 tabular">{Math.round(row.confidence * 100)}% support score</span>
            )}
          </div>
        )}
      </div>
      <div className="flex gap-2 border-t border-rule px-5 py-4">
        {row.status === "NEW" ? (
          <Button variant="accent" busy={busy} onClick={onFile} className="flex-1">
            File claim
          </Button>
        ) : null}
        <Link
          href={`/console/claims/${row.claim_id}`}
          className={`inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[8px] text-[13px] font-medium ${
            row.status === "NEW" ? "border border-rule-2 text-ink hover:bg-wash-2" : "bg-ink text-paper hover:bg-white"
          }`}
        >
          Open case <ArrowRight size={14} aria-hidden />
        </Link>
      </div>
    </aside>
  );
}

export function Docket() {
  const router = useRouter();
  const { data, error, isLoading, mutate } = useSWR<ClaimRow[]>("/api/claims", { refreshInterval: 4000 });
  const [status, setStatus] = useState<string | null>(null);
  const [group, setGroup] = useState("all");
  const [fileGroup, setFileGroup] = useState("T1");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const rows = useMemo(() => {
    let r = data ?? [];
    if (status) r = r.filter((x) => x.status === status);
    if (group !== "all") r = r.filter((x) => (group === "normal" ? !x.trap : x.trap === group));
    if (q.trim()) {
      const s = q.trim().toLowerCase();
      r = r.filter((x) =>
        [x.claim_id, x.tenant, x.service_name, x.reason_name ?? ""].some((v) => v?.toLowerCase().includes(s)),
      );
    }
    return [...r].sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0) || a.claim_id.localeCompare(b.claim_id));
  }, [data, status, group, q]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (data ?? []).forEach((x) => (c[x.status] = (c[x.status] ?? 0) + 1));
    return c;
  }, [data]);

  const sel = selected ? (data ?? []).find((r) => r.claim_id === selected) ?? null : null;

  async function file(ids?: string[]) {
    setBusy(true);
    setActionError(null);
    try {
      await post("/api/claims/inject", { ids: ids ?? (data ?? []).filter(x => x.status === "NEW" && (fileGroup === "all" || (fileGroup === "normal" ? !x.trap : x.trap === fileGroup))).map(x => x.claim_id) });
      await mutate();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  }

  const unfiled = (data ?? []).filter((x) => x.status === "NEW" && !x.claim_id.startsWith("NC-") && (fileGroup === "all" || (fileGroup === "normal" ? !x.trap : x.trap === fileGroup))).length;

  // On wide screens a row opens the preview; below that it opens the case.
  function pick(id: string) {
    if (typeof window !== "undefined" && window.matchMedia("(min-width: 1280px)").matches) setSelected(selected === id ? null : id);
    else router.push(`/console/claims/${id}`);
  }

  return (
    <div className="mx-auto max-w-[1400px]">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <h1 className="text-[26px] font-semibold leading-[1.15] tracking-[-0.03em]">Docket</h1>
          <p className="mt-1.5 max-w-[66ch] text-[13.5px] text-ink-2">
            Denied claims, worked by five agents that share nothing but the graph. Each precedent carries its treatment:{" "}
            <Treatment kind="positive" label="followed" size={12} />,{" "}
            <Treatment kind="caution" label="distinguished" size={12} /> or{" "}
            <Treatment kind="negative" label="refused" size={12} />.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => setCreating(true)}>
            <Plus size={14} aria-hidden /> New claim
          </Button>
          <span className="mx-1 hidden h-5 w-px bg-rule sm:block" aria-hidden />
          <label className="sr-only" htmlFor="file-group">
            Scenario to file
          </label>
          <select id="file-group" value={fileGroup} onChange={(e) => setFileGroup(e.target.value)} className={SELECT}>
            {GROUPS.map((g) => (
              <option key={g.id} value={g.id}>
                {g.label}
              </option>
            ))}
          </select>
          {unfiled ? (
            <Button variant="accent" busy={busy} onClick={() => file()}>
              File {unfiled} claim{unfiled === 1 ? "" : "s"}
            </Button>
          ) : (
            <span className="inline-flex h-8 items-center px-1 text-[12.5px] text-ink-3" role="status">
              All claims in this scenario are filed
            </span>
          )}
        </div>
      </div>
      <ErrorNote error={actionError} />

      {/* Where every claim stands: a segmented control that also filters. */}
      <div className="mt-6 overflow-x-auto">
        <div className="inline-flex min-w-full gap-0.5 rounded-[10px] border border-rule bg-wash p-1 sm:min-w-0" role="group" aria-label="Filter by stage">
          {LEDGER.map((s) => {
            const n = counts[s] ?? 0;
            const active = status === s;
            return (
              <button
                key={s}
                onClick={() => setStatus(active ? null : s)}
                aria-pressed={active}
                className={`flex h-8 shrink-0 items-center gap-1.5 rounded-[7px] px-2.5 text-[12.5px] transition-colors ${
                  active ? "bg-wash-2 text-ink shadow-[inset_0_0_0_1px_var(--rule-2)]" : "text-ink-2 hover:text-ink"
                }`}
              >
                <span className={`font-semibold tabular ${n ? (s === "NEEDS_HUMAN" ? "text-neg" : "text-ink") : "text-ink-3"}`}>{n}</span>
                <span className={n || active ? "" : "text-ink-3"}>{STATUS_LABEL[s]}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Claim, policyholder, service, reason"
            aria-label="Search claims"
            className={`${SELECT} w-[280px] max-w-full pl-8 placeholder:text-ink-3`}
          />
        </div>
        <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Scenario" className={SELECT}>
          {GROUPS.map((g) => (
            <option key={g.id} value={g.id}>
              {g.id === "all" ? "All scenarios" : g.label}
            </option>
          ))}
        </select>
        {(status || group !== "all" || q) && (
          <Button variant="ghost" onClick={() => (setStatus(null), setGroup("all"), setQ(""))}>
            Clear filters
          </Button>
        )}
        <span className="ml-auto text-[12px] text-ink-3 tabular">
          {rows.length} of {data?.length ?? 0} claims
        </span>
      </div>

      <div className="mt-3 flex items-start gap-4">
        <div className="min-w-0 flex-1 overflow-x-auto rounded-[12px] border border-rule bg-wash">
          {error && <div className="px-4 py-2"><ErrorNote error={error} /></div>}
          <table className={`w-full border-collapse text-left ${sel ? "md:min-w-[680px]" : "md:min-w-[920px]"}`}>
            <thead>
              <tr className="border-b border-rule text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">
                <th className="py-2.5 pl-4 pr-4 font-medium">Claim</th>
                <th className={`hidden py-2.5 pr-4 font-medium md:table-cell ${sel ? "xl:hidden" : ""}`}>Scenario</th>
                <th className="hidden py-2.5 pr-4 font-medium md:table-cell">Service · denial</th>
                <th className="hidden py-2.5 pr-4 font-medium md:table-cell">Progress</th>
                <th className="hidden py-2.5 pr-4 font-medium md:table-cell">Precedents</th>
                <th className="hidden whitespace-nowrap py-2.5 pr-4 font-medium md:table-cell">Disposition</th>
                <th className={`hidden py-2.5 pr-4 text-right font-medium md:table-cell ${sel ? "xl:hidden" : ""}`}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {isLoading &&
                !data &&
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="border-b border-rule last:border-0">
                    <td colSpan={7} className="px-4 py-4">
                      <div className="h-4 w-2/3 animate-pulse rounded bg-wash-2" />
                    </td>
                  </tr>
                ))}
              {rows.map((r) => {
                const d = r.disposition ? DISPOSITION[r.disposition] : null;
                const on = selected === r.claim_id;
                return (
                  <tr
                    key={r.claim_id}
                    onClick={(e) => {
                      if ((e.target as HTMLElement).closest("a,button")) return;
                      pick(r.claim_id);
                    }}
                    className={`cursor-pointer border-b border-rule align-top transition-colors last:border-0 ${
                      on ? "bg-wash-2 shadow-[inset_2px_0_0_var(--link)]" : "hover:bg-[#141418]"
                    }`}
                  >
                    <td className="py-3 pl-4 pr-4">
                      <Link
                        href={`/console/claims/${r.claim_id}`}
                        className="font-mono text-[12.5px] font-medium text-ink hover:text-link hover:underline"
                      >
                        {r.claim_id}
                      </Link>
                      <div className="mt-0.5 text-[12px] text-ink-3">{r.tenant}</div>
                      <div className="mt-2 space-y-2 md:hidden">
                        <div className="text-[12.5px] text-ink">
                          {r.service_name} · {r.reason_name ?? "denial not read yet"}
                        </div>
                        {r.status === "NEW" ? <span className="text-[12px] text-ink-3">Not filed</span> : <StepTrack row={r} />}
                        <CitatorStrip flags={r.flags} />
                        {d && <Treatment kind={d.tone} label={d.short} size={12} className="text-[12.5px]" />}
                      </div>
                    </td>
                    <td className={`hidden py-3 pr-4 text-[12.5px] md:table-cell ${sel ? "xl:hidden" : ""}`}>
                      {r.trap ? (
                        <>
                          <span className="font-medium text-ink">
                            {r.trap} · {TRAPS[r.trap]?.name}
                          </span>
                          <div className="mt-0.5 max-w-[24ch] text-[11.5px] leading-snug text-ink-3">{TRAPS[r.trap]?.line}</div>
                        </>
                      ) : (
                        <span className="text-ink-3">{r.claim_id.startsWith("NC-") ? "Entered by hand" : "Routine"}</span>
                      )}
                    </td>
                    <td className="hidden py-3 pr-4 text-[13px] md:table-cell">
                      <div className="text-ink">{r.service_name}</div>
                      <div className="mt-0.5 text-[12px] text-ink-3">
                        {r.reason_name ?? "Denial not read yet"} · {fmtDate(r.service_date)}
                      </div>
                    </td>
                    <td className="hidden py-3 pr-4 md:table-cell">
                      {r.status === "NEW" ? (
                        <Button className="h-7" onClick={() => file([r.claim_id])} disabled={busy}>
                          File claim
                        </Button>
                      ) : (
                        <StepTrack row={r} />
                      )}
                    </td>
                    <td className="hidden py-3 pr-4 md:table-cell">
                      <CitatorStrip flags={r.flags} />
                    </td>
                    <td className="hidden whitespace-nowrap py-3 pr-4 text-[12.5px] md:table-cell">
                      {d ? (
                        <>
                          <Treatment kind={d.tone} label={d.short} size={12} />
                          {r.confidence != null && r.flags.some((f) => f.code === "ACCEPTED") && (
                            <div className="mt-0.5 text-[11.5px] text-ink-3 tabular" title="Precedent support score (smoothed recorded outcomes, not a probability)">
                              {Math.round(r.confidence * 100)}%
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="text-ink-3">—</span>
                      )}
                    </td>
                    <td className={`hidden whitespace-nowrap py-3 pr-4 text-right text-[12px] text-ink-3 tabular md:table-cell ${sel ? "xl:hidden" : ""}`}>
                      {ago(r.updated_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data && !rows.length && (
            <div className="p-4">
              <Empty title="No claims match these filters.">Clear the filters, or file a scenario to put claims on the docket.</Empty>
            </div>
          )}
        </div>
        {sel && <Preview row={sel} onClose={() => setSelected(null)} onFile={() => file([sel.claim_id])} busy={busy} />}
      </div>
      {creating && <NewClaim onClose={() => setCreating(false)} />}
    </div>
  );
}
