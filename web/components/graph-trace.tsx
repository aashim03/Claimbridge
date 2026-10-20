"use client";

import { useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ClauseImpact, ClausePick, ImpactEdge, ImpactNode, PrecedentTrace } from "@/lib/api";
import { ErrorNote, Mono } from "./ui";

const KEYFRAMES = `@keyframes cb-draw{from{stroke-dashoffset:var(--len)}to{stroke-dashoffset:0}}@keyframes cb-hop{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}@keyframes cb-pop{from{opacity:0}to{opacity:1}}@media (prefers-reduced-motion:reduce){*{animation-duration:1ms!important;animation-delay:0ms!important}}`;

// ------------------------------------------------------------------ why this precedent?

// The chain of edges between a claim and one precedent. Each hop is a relationship the Verifier
// checked in the graph; the first one that does not hold is the reason the precedent was refused.
export function PrecedentPath({ cid, fid }: { cid: string; fid: string }) {
  const [open, setOpen] = useState(false);
  const { data, error } = useSWR<PrecedentTrace>(open ? `/api/claims/${cid}/trace/${fid}` : null);
  return (
    <div className="mt-2">
      <button className="inline-flex items-center gap-1 text-[12px] text-link hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
        Show the path through the graph
      </button>
      {open && error && <ErrorNote error={error} />}
      {open && data && (
        <ol className="mt-2 border-l border-rule-2 pl-3" aria-label="Path through the graph">
          <style>{KEYFRAMES}</style>
          {data.hops.map((h, i) => (
            <li
              key={h.key}
              className={`relative pb-2 pl-3 text-[12.5px] leading-snug ${h.break ? "rounded-[6px] bg-neg-wash py-1.5 pr-2" : ""}`}
              style={{ animation: `cb-hop 360ms ${i * 90}ms both var(--ease-out-expo)` }}
            >
              <span
                className={`absolute -left-[17px] top-1 grid h-3 w-3 place-items-center rounded-full border text-[8px] ${
                  h.ok ? "border-pos bg-pos-wash text-pos" : "border-neg bg-neg text-paper"
                }`}
                aria-hidden
              >
                {h.ok ? "✓" : "✕"}
              </span>
              <span className="flex flex-wrap items-baseline gap-x-1.5">
                <Mono className="text-ink">{h.from}</Mono>
                <span className={h.ok ? "text-ink-3" : "font-semibold text-neg"}>— {h.rel} →</span>
                <Mono className={h.ok ? "text-ink" : "text-neg"}>{h.to}</Mono>
              </span>
              <span className={`block ${h.break ? "text-neg" : "text-ink-3"}`}>{h.break ? `Breaks here. ${h.note}` : h.note}</span>
            </li>
          ))}
          <li className="pl-3 text-[11.5px] text-ink-3">
            {data.broken ? "The first broken edge is the reason." : "Every edge holds, so the precedent applies."} Verdict stored by the Verifier: <Mono>{data.code}</Mono>
            {data.code === data.derived_code ? " (matches this path)" : ""}
          </li>
        </ol>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ blast radius of a clause

const W = 900;
const COL_X = [8, 235, 495, 735];
const NODE_W = [190, 205, 205, 155];
const ROW_H = 58;
const NODE_H = 40;

type Placed = ImpactNode & { x: number; y: number; w: number; col: number };

const colOf = (n: ImpactNode) => (n.kind === "clause" ? 0 : n.kind === "finding" ? 1 : n.kind === "claim" ? 3 : 2);

function layout(nodes: ImpactNode[], edges: ImpactEdge[]): Placed[] {
  const byCol: ImpactNode[][] = [[], [], [], []];
  for (const n of nodes) byCol[colOf(n)].push(n);
  byCol[0].sort((a, b) => (a.version ?? "").localeCompare(b.version ?? ""));
  // Order claims and evidence by the precedents they attach to, so edges cross as little as possible.
  const rank = new Map(byCol[1].map((n, i) => [n.id, i]));
  const bary = (n: ImpactNode) => {
    const r = edges.flatMap((e) => (e.from === n.id ? [rank.get(e.to)] : e.to === n.id ? [rank.get(e.from)] : [])).filter((x): x is number => x !== undefined);
    return r.length ? r.reduce((a, b) => a + b, 0) / r.length : 0;
  };
  byCol[2].sort((a, b) => bary(a) - bary(b));
  byCol[3].sort((a, b) => bary(a) - bary(b));
  const height = Math.max(Math.max(...byCol.map((c) => c.length), 1) * ROW_H, 120);
  return byCol.flatMap((col, ci) => {
    const gap = height / Math.max(col.length, 1);
    return col.map((n, i) => ({ ...n, col: ci, x: COL_X[ci], w: NODE_W[ci], y: gap * i + (gap - NODE_H) / 2 }));
  });
}

// Everything connected to the picked node, in both directions: its blast radius.
function reach(start: string, edges: ImpactEdge[]): Set<string> {
  const seen = new Set([start]);
  const queue = [start];
  while (queue.length) {
    const cur = queue.pop()!;
    for (const e of edges) {
      const other = e.from === cur ? e.to : e.to === cur ? e.from : null;
      if (other && !seen.has(other)) {
        seen.add(other);
        queue.push(other);
      }
    }
  }
  return seen;
}

function Graph({ impact, focus, onFocus }: { impact: ClauseImpact; focus: string; onFocus: (id: string) => void }) {
  const placed = layout(impact.nodes, impact.edges);
  const at = new Map(placed.map((n) => [n.id, n]));
  const lit = reach(focus, impact.edges);
  const height = Math.max(...placed.map((n) => n.y + NODE_H), 80) + 30;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="group" aria-label={`Everything connected to ${focus}`}>
      <style>{KEYFRAMES}</style>
      {["Policy clauses", "Memory learned on them", "Evidence it asks for", "Claims that weighed it"].map((t, i) => (
        <text key={t} x={COL_X[i]} y={11} fontSize="10" fontWeight="600" letterSpacing="0.6" fill="var(--ink-3)">
          {t.toUpperCase()}
        </text>
      ))}
      <g transform="translate(0 22)">
      {impact.edges.map((e, i) => {
        const a = at.get(e.from);
        const b = at.get(e.to);
        if (!a || !b) return null;
        const [l, r] = a.x <= b.x ? [a, b] : [b, a];
        const x1 = l.x + l.w, y1 = l.y + NODE_H / 2, x2 = r.x, y2 = r.y + NODE_H / 2;
        const d =
          a.col === b.col
            ? `M ${a.x + a.w - 20} ${Math.min(a.y, b.y) + NODE_H} C ${a.x + a.w + 30} ${(a.y + b.y) / 2 + NODE_H / 2}, ${a.x + a.w + 30} ${(a.y + b.y) / 2 + NODE_H / 2}, ${a.x + a.w - 20} ${Math.max(a.y, b.y)}`
            : `M ${x1} ${y1} C ${x1 + 40} ${y1}, ${x2 - 40} ${y2}, ${x2} ${y2}`;
        const on = lit.has(e.from) && lit.has(e.to);
        const bad = e.state === "changed" || (e.code !== undefined && e.code !== "ACCEPTED");
        const len = Math.round(Math.hypot(x2 - x1, y2 - y1) * 1.4 + 60);
        return (
          <path
            key={i}
            d={d}
            fill="none"
            strokeWidth={on ? (e.code ? 1.1 : 1.6) : 1}
            stroke={!on ? "var(--rule-2)" : bad ? "var(--caution)" : "var(--link)"}
            opacity={on ? (e.code ? 0.6 : 1) : 0.25}
            strokeDasharray={on ? (e.state === "same" ? "5 4" : len) : undefined}
            style={on && e.state !== "same" ? ({ "--len": len, animation: `cb-draw 700ms ${(Math.min(a.col, b.col) + 1) * 220}ms both var(--ease-out-expo)` } as React.CSSProperties) : undefined}
          >
            <title>{`${e.from} ${e.label} ${e.to}`}</title>
          </path>
        );
      })}
      {placed.map((n) => {
        const on = lit.has(n.id);
        const limited = n.status === "STALE" || n.status === "CONTRADICTED";
        return (
          <g
            key={n.id}
            transform={`translate(${n.x} ${n.y})`}
            opacity={on ? 1 : 0.4}
            onClick={() => onFocus(n.id)}
            style={{ cursor: "pointer", animation: on ? `cb-pop 400ms ${(n.col + 1) * 220}ms both` : undefined }}
            tabIndex={0}
            role="button"
            aria-label={`${n.kind} ${n.label}`}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onFocus(n.id)}
          >
            <rect
              width={n.w}
              height={NODE_H}
              rx="6"
              fill={n.id === focus ? "var(--wash-2)" : "var(--wash)"}
              stroke={n.id === focus ? "var(--link)" : limited ? "var(--caution)" : "var(--rule-2)"}
              strokeWidth={n.id === focus ? 1.6 : 1}
            />
            <text x="9" y="17" fontSize="11.5" fontWeight="600" fill="var(--ink)" fontFamily="var(--font-mono)">
              {n.kind === "clause" ? n.id : n.label.length > 27 ? n.label.slice(0, 26) + "…" : n.label}
            </text>
            <text x="9" y="31" fontSize="10.5" fill={limited ? "var(--caution)" : "var(--ink-3)"}>
              {n.kind === "clause" ? (n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label) : (n.sub ?? n.kind)}
            </text>
          </g>
        );
      })}
      </g>
    </svg>
  );
}

export function ClauseImpactPanel() {
  const { data: picks } = useSWR<{ clauses: ClausePick[] }>("/api/impact/clauses");
  const [picked, setPicked] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [showQ, setShowQ] = useState(false);
  const clauses = picks?.clauses.filter((c) => c.findings > 0) ?? [];
  // Open on the lineage with the most claims and memory resting on it, at its newest version.
  const richest = [...clauses].sort((a, b) => b.claims + b.findings - (a.claims + a.findings) || b.version_id.localeCompare(a.version_id))[0];
  const id = picked ?? richest?.clause_id ?? null;
  const { data, error } = useSWR<ClauseImpact>(id ? `/api/impact/clause/${id}` : null, { refreshInterval: 6000 });
  const f = focus && data?.nodes.some((n) => n.id === focus) ? focus : id;

  return (
    <section className="mt-10 border-t border-rule-2 pt-5" aria-labelledby="impact-h">
      <h2 id="impact-h" className="text-[17px] font-semibold">
        What rests on a clause
      </h2>
      <p className="mt-1 max-w-[75ch] text-[13px] text-ink-2">
        Pick a clause. One traversal walks its <Mono>SUPERSEDES</Mono> lineage, then every precedent learned on it, the evidence those precedents ask for and the claims that
        weighed them. Click any node to light up only what is connected to it. This is what a clause change puts at risk.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
        <label htmlFor="impact-clause" className="text-ink-2">
          Clause
        </label>
        <select
          id="impact-clause"
          value={id ?? ""}
          onChange={(e) => (setPicked(e.target.value), setFocus(e.target.value))}
          className="h-8 max-w-full rounded-[8px] border border-rule bg-wash px-2 font-mono text-[12px] hover:border-rule-2"
        >
          {clauses.map((c) => (
            <option key={c.clause_id} value={c.clause_id}>
              {c.clause_id} · §{c.section} {c.title} · {c.findings} precedent{c.findings === 1 ? "" : "s"} · {c.claims} claim{c.claims === 1 ? "" : "s"}
            </option>
          ))}
        </select>
      </div>
      <ErrorNote error={error} />
      {data && f && (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4" aria-label="Reach">
            {(
              [
                ["Clause versions", data.counts.clauses, data.counts.changed ? `${data.counts.changed} changed text` : "no change"],
                ["Precedents", data.counts.findings, data.counts.stale ? `${data.counts.stale} limited` : "all active"],
                ["Evidence types", data.counts.evidence, "asked for by them"],
                ["Claims", data.counts.claims, data.counts.claims_withheld ? `${data.counts.claims_visible} yours, ${data.counts.claims_withheld} withheld` : "weighed them"],
              ] as [string, number, string][]
            ).map(([k, v, s]) => (
              <div key={k}>
                <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{k}</dt>
                <dd className="text-[22px] font-semibold tabular leading-tight">{v}</dd>
                <dd className="text-[12px] text-ink-3">{s}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-3 overflow-x-auto rounded-[12px] border border-rule bg-wash p-3">
            <div className="min-w-[720px]">
              <Graph impact={data} focus={f} onFocus={setFocus} />
            </div>
          </div>
          <p className="mt-2 text-[12px] text-ink-3">
            <span className="text-link">Blue</span> edges connect to the selected node. <span className="text-caution-ink">Amber</span> marks a clause whose text changed, a limited precedent, or a
            precedent that was refused for a claim. Dashed: the text did not change, so memory carries forward.
          </p>
          <button className="mt-3 inline-flex items-center gap-1 text-[12.5px] text-ink-3 hover:text-ink" onClick={() => setShowQ(!showQ)} aria-expanded={showQ}>
            {showQ ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
            The Cypher behind this view
          </button>
          {showQ && <pre className="mt-2 overflow-x-auto rounded-[8px] border border-rule bg-paper p-3 font-mono text-[11.5px] leading-relaxed text-ink-2">{data.cypher}</pre>}
        </>
      )}
    </section>
  );
}
