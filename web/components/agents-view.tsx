"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { post } from "@/lib/api";
import { ROLE_JOB, ROLE_LABEL, ago, humanEvent } from "@/lib/vocab";
import { Button, Empty, ErrorNote, Mono, SectionHead } from "./ui";

type Worker = { agent_id: string; role: string; state: string; current_claim: string | null; last_seen: number; alive: boolean };
type Agents = {
  workers: Worker[];
  leases: { claim_id: string; status: string; owner: string; expires_in_ms: number; attempt: number }[];
  events: { claim_id: string; type: string; agent: string; ts: number; payload: Record<string, unknown> }[];
  commands: { id: string; type: string; target: string; status: string; note: string | null; created_at: number }[];
  now: number;
};

const ROLES = ["intake", "retrieval", "verifier", "planner", "curator"];

function StateLabel({ w }: { w: Worker }) {
  const state = !w.alive && w.state !== "killed" ? (w.state === "stopped" ? "stopped" : "unresponsive") : w.state;
  const tone =
    state === "working" ? "text-link" : state === "idle" ? "text-pos" : state === "killed" ? "text-neg" : "text-ink-3";
  return (
    <span className={`inline-flex items-center gap-1.5 text-[12px] font-medium ${tone}`}>
      <span
        className={`size-1.5 rounded-full ${state === "working" ? "live-dot bg-link" : state === "idle" ? "bg-pos" : state === "killed" ? "bg-neg" : "bg-neutral"}`}
        aria-hidden
      />
      {state}
    </span>
  );
}

export function AgentsView() {
  const { data, error, mutate } = useSWR<Agents>("/api/agents", { refreshInterval: 1500 });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);

  async function act(key: string, url: string, body: object = {}) {
    setBusy(key);
    setErr(null);
    try {
      await post(url, body);
      await mutate();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  const supervisor = data?.workers.find((w) => w.role === "supervisor");
  const byRole = (r: string) => (data?.workers ?? []).filter((w) => w.role === r).sort((a, b) => Number(b.alive) - Number(a.alive) || a.agent_id.localeCompare(b.agent_id));

  return (
    <div className="mx-auto max-w-[1280px]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold leading-[1.15] tracking-[-0.03em]">Agents</h1>
          <p className="mt-1.5 max-w-[72ch] text-[13.5px] text-ink-2">
            Each worker is its own process. They never message each other: a worker leases a claim in the graph, does one step, and
            commits. Kill one mid-step and its lease expires; another replica resumes from the checkpoint it left behind.
          </p>
        </div>
        <p className="text-[12.5px] text-ink-3">
          Supervisor{" "}
          {supervisor?.alive ? <span className="font-medium text-pos">running</span> : <span className="font-medium text-neg">not running</span>}
        </p>
      </div>
      <ErrorNote error={err ?? error} />
      {data && !supervisor?.alive && (
        <div className="mt-4">
          <Empty title="The agent pool is not running.">
            Start it with <Mono>uv run python -m claimbridge.cli up</Mono> in <Mono>backend/</Mono>; the workers will appear here.
          </Empty>
        </div>
      )}

      <div className="mt-6 grid gap-px overflow-hidden rounded-[12px] border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-5">
        {ROLES.map((r) => {
          const ws = byRole(r);
          return (
            <section key={r} className="bg-wash p-4">
              <h2 className="text-[15px] font-semibold tracking-[-0.02em]">{ROLE_LABEL[r]}</h2>
              <p className="mt-0.5 min-h-[34px] text-[12px] leading-snug text-ink-3">{ROLE_JOB[r]}</p>
              <ul className="mt-3 space-y-2.5">
                {ws.map((w) => (
                  <li key={w.agent_id} className={`border-t border-rule pt-2 ${w.alive ? "" : "opacity-60"}`}>
                    <div className="flex items-center justify-between gap-2">
                      <Mono className="text-ink">{w.agent_id}</Mono>
                      <StateLabel w={w} />
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[11.5px] text-ink-3">
                      <span>
                        {w.current_claim && w.state === "working" ? (
                          <Link href={`/console/claims/${w.current_claim}`} className="font-mono text-link hover:underline">
                            {w.current_claim}
                          </Link>
                        ) : (
                          `seen ${ago(w.last_seen, data?.now)}`
                        )}
                      </span>
                      {w.alive && (
                        <button
                          onClick={() => act(`kill-${w.agent_id}`, `/api/agents/${w.agent_id}/kill`)}
                          disabled={!!busy}
                          className="rounded-[5px] px-1.5 py-0.5 font-medium text-neg hover:bg-neg-wash disabled:opacity-50"
                        >
                          {busy === `kill-${w.agent_id}` ? "Killing…" : "Kill"}
                        </button>
                      )}
                    </div>
                  </li>
                ))}
                {!ws.length && <li className="text-[12px] text-ink-3">No workers.</li>}
              </ul>
              <Button className="mt-3 h-7 w-full" busy={busy === `start-${r}`} disabled={!supervisor?.alive} onClick={() => act(`start-${r}`, "/api/agents/start", { role: r })}>
                Start another
              </Button>
            </section>
          );
        })}
      </div>

      <div className="mt-2 grid gap-x-10 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section>
          <SectionHead title="Coordination ledger" aside="every lease, handoff and recovery, as recorded in the graph" />
          {data?.events.length ? (
            <table className="w-full border-collapse text-[13px]">
              <tbody>
                {data.events.map((e, i) => {
                  const alarm = ["RESUMED", "LEASE_EXPIRED", "FENCED_WRITE_REJECTED", "NEEDS_HUMAN", "GAVE_UP"].includes(e.type);
                  return (
                    <tr key={i} className={`border-b border-rule ${alarm ? "bg-caution-wash" : ""}`}>
                      <td className="w-[86px] py-1.5 pr-3 text-[11.5px] text-ink-3 tabular">{ago(e.ts, data.now)}</td>
                      <td className={`py-1.5 pr-3 ${alarm ? "font-semibold text-caution-ink" : "text-ink"}`}>
                        {humanEvent(e.type)}
                        {e.type === "RESUMED" && e.payload.previous_owner ? (
                          <span className="font-normal text-ink-2"> from {String(e.payload.previous_owner)}</span>
                        ) : null}
                      </td>
                      <td className="py-1.5 pr-3">
                        <Mono className="text-ink-2">{e.agent}</Mono>
                      </td>
                      <td className="py-1.5 text-right">
                        <Link href={`/console/claims/${e.claim_id}`} className="font-mono text-[12px] text-link hover:underline">
                          {e.claim_id}
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <Empty title="No activity yet.">File claims on the docket and the agents&apos; handoffs appear here.</Empty>
          )}
        </section>
        <aside>
          <SectionHead title="Leases held now" />
          {data?.leases.length ? (
            <ul>
              {data.leases.map((l) => {
                const s = Math.ceil(l.expires_in_ms / 1000);
                return (
                  <li key={l.claim_id} className="flex items-center justify-between border-b border-rule py-1.5 text-[12.5px]">
                    <Link href={`/console/claims/${l.claim_id}`} className="font-mono text-link hover:underline">
                      {l.claim_id}
                    </Link>
                    <Mono className="text-ink-2">{l.owner}</Mono>
                    <span className={`tabular ${s <= 0 ? "font-semibold text-neg" : "text-ink-3"}`}>
                      {s > 0 ? `${s}s left` : "expired"}
                      {l.attempt > 1 ? ` · attempt ${l.attempt}` : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[12.5px] text-ink-3">No claim is leased right now.</p>
          )}
          <SectionHead title="Commands" aside="written to the graph; the Supervisor executes them" />
          {data?.commands.length ? (
            <ul>
              {data.commands.map((c) => (
                <li key={c.id} className="flex items-center justify-between border-b border-rule py-1.5 text-[12.5px]">
                  <span>
                    <span className="font-medium">{c.type.toLowerCase()}</span> <Mono className="text-ink-2">{c.target}</Mono>
                  </span>
                  <span className={c.status === "FAILED" ? "text-neg" : c.status === "PENDING" ? "text-caution-ink" : "text-ink-3"}>
                    {c.status.toLowerCase()}
                    {c.note && c.type !== "START" ? ` · ${c.note}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12.5px] text-ink-3">No commands issued.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
