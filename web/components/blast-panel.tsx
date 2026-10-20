"use client";

import { useState } from "react";
import useSWR from "swr";
import type { BlastLineage, BlastRadius } from "@/lib/api";
import { ErrorNote, Mono } from "./ui";

// Which clause lineages carry the most memory, ranked by PageRank over the dependency edges, and
// what one clause change would reach, with its hop distance from BFS. Both run inside FalkorDB.
export function BlastRadiusPanel() {
  const { data } = useSWR<{ lineages: BlastLineage[] }>("/api/blast/lineages", { refreshInterval: 8000 });
  const [picked, setPicked] = useState<string | null>(null);
  const ranked = data?.lineages ?? [];
  const lineage = ranked.find((l) => l.lineage_id === picked) ?? ranked[0];
  const clauseId = lineage ? [...lineage.clause_ids].sort().at(-1) : null; // newest version of the lineage
  const { data: reach, error } = useSWR<BlastRadius>(clauseId ? `/api/blast/clause/${clauseId}` : null, { refreshInterval: 8000 });

  const hopRows = reach
    ? [
        ...reach.clauses.filter((c) => c.hops > 0).map((c) => ({ id: c.clause_id, hops: c.hops, kind: "clause version" })),
        ...reach.findings.map((f) => ({ id: f.finding_id, hops: f.hops, kind: `precedent, ${f.status.toLowerCase()}` })),
        ...reach.outcomes.map((o) => ({ id: o.resolution_id, hops: o.hops, kind: "verified outcome behind a precedent" })),
        ...reach.claims.map((c) => ({ id: c.claim_id, hops: c.hops, kind: `claim, ${c.status.toLowerCase().replace(/_/g, " ")}` })),
      ].sort((a, b) => a.hops - b.hops || a.id.localeCompare(b.id))
    : [];

  return (
    <section className="mt-10 border-t border-rule-2 pt-5" aria-labelledby="blast-h">
      <h2 id="blast-h" className="text-[17px] font-semibold">
        Which clauses carry the most memory
      </h2>
      <p className="mt-1 max-w-[75ch] text-[13px] text-ink-2">
        FalkorDB&apos;s <Mono>algo.pageRank</Mono> scores each clause lineage by how much depends on it: claims lean on precedents, which lean on clauses. Pick one and{" "}
        <Mono>algo.BFS</Mono> shows what a change to it would reach, and how many hops away. A plain count gives the same set; the hop distance and the ranking are what the algorithms add.
      </p>

      {ranked.length === 0 && <p className="mt-3 text-[13px] text-ink-3">No memory depends on any clause yet.</p>}
      {ranked.length > 0 && (
        <ol className="mt-3 divide-y divide-rule rounded-[12px] border border-rule bg-wash" aria-label="Clause lineages ranked by dependent memory">
          {ranked.slice(0, 8).map((l) => {
            const on = l.lineage_id === lineage?.lineage_id;
            return (
              <li key={l.lineage_id}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => setPicked(l.lineage_id)}
                  className={`grid w-full grid-cols-[28px_1fr] items-baseline gap-x-2 px-4 py-2.5 text-left hover:bg-wash-2 ${on ? "bg-wash-2" : ""}`}
                >
                  <span className="font-mono text-[12.5px] text-ink-3 tabular">{String(l.rank).padStart(2, "0")}</span>
                  <span>
                    <span className="block text-[14px] text-ink">
                      §{l.section} {l.title} {on && <span className="ml-1 text-[11.5px] font-medium text-link">· selected</span>}
                    </span>
                    <span className="block text-[12px] text-ink-3 tabular">
                      score {l.score.toFixed(3)} · {l.findings.length} precedent{l.findings.length === 1 ? "" : "s"} · {l.claims_visible} claim{l.claims_visible === 1 ? "" : "s"}
                      {l.claims_total > l.claims_visible ? ` (${l.claims_total - l.claims_visible} withheld)` : ""} · <Mono>{l.lineage_id}</Mono>
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}

      <ErrorNote error={error} />
      {reach && (
        <div className="mt-4">
          <h3 className="text-[14px] font-semibold text-ink">
            If <Mono>{reach.clause_id}</Mono> changes
          </h3>
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4" aria-label="Reach">
            {(
              [
                ["Precedents", reach.counts.findings, "reached"],
                ["Claims", reach.counts.claims_visible, reach.counts.claims_withheld ? `${reach.counts.claims_withheld} withheld` : "reached"],
                ["Farthest", reach.counts.farthest_hop, `hop${reach.counts.farthest_hop === 1 ? "" : "s"} away`],
                ["Rank", reach.lineage_rank.rank ?? "–", reach.lineage_rank.rank ? `of ${reach.lineage_rank.of}` : "no memory rests here"],
              ] as [string, number | string, string][]
            ).map(([k, v, s]) => (
              <div key={k}>
                <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{k}</dt>
                <dd className="text-[22px] font-semibold tabular leading-tight">{v}</dd>
                <dd className="text-[12px] text-ink-3">{s}</dd>
              </div>
            ))}
          </dl>
          {hopRows.length > 0 && (
            <ol className="mt-3 divide-y divide-rule rounded-[12px] border border-rule bg-wash" aria-label="Everything reached, nearest first">
              {hopRows.map((r) => (
                <li key={r.id} className="grid grid-cols-[64px_1fr] items-baseline gap-x-2 px-4 py-1.5 text-[13px]">
                  <span className="text-ink-3 tabular">hop {r.hops}</span>
                  <span className="min-w-0 break-words">
                    <Mono>{r.id}</Mono> <span className="text-ink-3">· {r.kind}</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
          <p className="mt-2 text-[12px] text-ink-3">
            Computed on a throwaway copy of the dependency edges (<Mono>SUPERSEDES</Mono>, <Mono>ON_LINEAGE</Mono>, <Mono>CONSIDERED</Mono>, <Mono>DERIVED_FROM</Mono>) because{" "}
            <Mono>algo.BFS</Mono> follows edges in one direction; the live graph is only read. Synthetic data, so the ranking mostly follows the counts.
          </p>
        </div>
      )}
    </section>
  );
}
