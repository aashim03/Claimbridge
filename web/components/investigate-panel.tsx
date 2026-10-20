"use client";

import { useState } from "react";
import useSWR from "swr";
import { Check, CircleAlert, Info } from "lucide-react";
import { post, type Investigation, type InvestigationStep } from "@/lib/api";
import { PrecedentPath } from "./graph-trace";
import { Button, ErrorNote, Mono, Panel } from "./ui";

// Each outcome gets an icon AND words, so no state depends on colour.
const OUTCOME: Record<string, { word: string; tone: "pos" | "caution" | "neutral" }> = {
  investigated: { word: "AI agent", tone: "pos" },
  investigated_with_template: { word: "AI agent · template brief", tone: "caution" },
  guarded: { word: "AI agent · brief replaced by the guard", tone: "caution" },
  llm_unavailable: { word: "Graph-only", tone: "neutral" },
  unknown_claim: { word: "No such claim", tone: "neutral" },
};

const PATH_TOOLS = new Set(["check_applicability", "explain_path"]);

function Step({ claimId, s }: { claimId: string; s: InvestigationStep }) {
  const finding = typeof s.args.finding_id === "string" ? s.args.finding_id : null;
  return (
    <li className="border-b border-rule px-4 py-3 last:border-b-0">
      <div className="grid grid-cols-[28px_1fr] gap-x-2">
        <span className="font-mono text-[12.5px] text-ink-3 tabular">{String(s.seq).padStart(2, "0")}</span>
        <div className="min-w-0">
          <p className="text-[14px] text-ink">
            {s.ok ? null : <span className="mr-1 font-medium text-neg">Did not answer.</span>}
            {s.plain}
          </p>
          <p className="mt-0.5 text-[12px] text-ink-3">
            tool <Mono>{s.tool}</Mono>
            {Object.values(s.args).length > 0 && (
              <>
                {" "}
                · <Mono className="break-all">{Object.values(s.args).join(", ")}</Mono>
              </>
            )}
          </p>
          {s.ok && PATH_TOOLS.has(s.tool) && finding && <PrecedentPath cid={claimId} fid={finding} />}
          <details className="mt-1.5 text-[12.5px]">
            <summary className="cursor-pointer text-link hover:underline">Raw tool result</summary>
            <pre className="mt-1.5 max-h-72 overflow-auto rounded-[8px] border border-rule bg-paper p-3 font-mono text-[11.5px] leading-relaxed text-ink-2">
              {JSON.stringify(s.result, null, 1)}
            </pre>
          </details>
        </div>
      </div>
    </li>
  );
}

export function InvestigatePanel({ claimId, onShowGraph }: { claimId: string; onShowGraph: () => void }) {
  const { data, mutate } = useSWR<{ investigations: Investigation[] }>(`/api/claims/${claimId}/investigations`);
  const [busy, setBusy] = useState<"auto" | "graph_only" | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [fresh, setFresh] = useState<Investigation | null>(null);
  const shown = fresh ?? data?.investigations[0] ?? null;

  async function run(mode: "auto" | "graph_only") {
    setBusy(mode);
    setErr(null);
    try {
      setFresh(await post<Investigation>(`/api/claims/${claimId}/investigate`, { mode }));
      mutate();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  const outcome = shown ? (OUTCOME[shown.outcome] ?? OUTCOME.llm_unavailable) : null;
  const Icon = outcome?.tone === "pos" ? Check : outcome?.tone === "caution" ? CircleAlert : Info;

  return (
    <div>
      <p className="max-w-[75ch] text-[13px] text-ink-2">
        The investigator picks read-only graph tools one step at a time, then writes a short brief. It can explain and compare; it cannot change a claim, a precedent or a decision. Every
        id and number in its brief must appear in a tool result, or the brief is replaced.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="accent" busy={busy === "auto"} disabled={busy !== null} onClick={() => run("auto")}>
          Investigate
        </Button>
        <Button busy={busy === "graph_only"} disabled={busy !== null} onClick={() => run("graph_only")}>
          Graph-only run
        </Button>
        <button type="button" className="text-[12.5px] text-link hover:underline" onClick={onShowGraph}>
          Open the graph replay
        </button>
      </div>
      <p className="mt-1.5 text-[12px] text-ink-3" aria-live="polite">
        {busy === "auto" ? "Investigating: the model is choosing tools…" : busy === "graph_only" ? "Running the fixed tool order…" : " "}
      </p>
      <ErrorNote error={err} />

      {!shown && !busy && <p className="mt-4 text-[13.5px] text-ink-3">No investigation yet. Run one to see which tools were called and what each returned.</p>}

      {shown && outcome && (
        <div className="mt-4 space-y-4">
          <Panel className="px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="inline-flex items-center gap-1.5 rounded-[6px] border border-rule-2 bg-wash-2 px-2 py-0.5 text-[12px] font-medium text-ink">
                <Icon size={13} aria-hidden /> {outcome.word}
              </span>
              <span className="text-[12.5px] text-ink-2">{shown.label}</span>
            </div>
            <h3 className="mt-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">Brief</h3>
            <p className="mt-1 text-[14px] leading-relaxed text-ink">{shown.brief}</p>
            {shown.hint && <p className="mt-2 text-[13px] text-ink-2">{shown.hint}</p>}
            {shown.violations.length > 0 && (
              <p className="mt-2 text-[12.5px] text-neg">The model&apos;s own brief was not shown: it {shown.violations.join("; it ")}.</p>
            )}
            {shown.notes.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-[12px] text-ink-3">
                {shown.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-[12px] text-ink-3 tabular">
              {shown.rounds.length > 0
                ? `${shown.model ?? "model"} · ${shown.rounds.length} round${shown.rounds.length === 1 ? "" : "s"} · ${shown.tokens.prompt ?? 0} prompt + ${shown.tokens.completion ?? 0} completion tokens${shown.rounds.every((r) => r.cached) ? " (replayed from a recording)" : ""}`
                : "No model was used: 0 tokens."}
            </p>
          </Panel>

          <section aria-label="Tool calls in order">
            <h3 className="mb-2 text-[13px] font-semibold text-ink">
              Steps <span className="font-normal text-ink-3">({shown.calls.length} tool calls, in order)</span>
            </h3>
            <Panel>
              <ol>
                {shown.calls.map((s) => (
                  <Step key={s.seq} claimId={claimId} s={s} />
                ))}
              </ol>
            </Panel>
          </section>
        </div>
      )}
    </div>
  );
}
