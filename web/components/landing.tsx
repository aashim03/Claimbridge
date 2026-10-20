"use client";

import Link from "next/link";
import { ArrowRight, GitBranch } from "lucide-react";
import type { ClaimDetail, GraphEdge, GraphNode } from "@/lib/api";
import snapDetail from "@/lib/snapshot/ev-t1-01.json";
import snapGraph from "@/lib/snapshot/ev-t1-01-graph.json";
import { GraphReplay } from "./graph-replay";
import { HeadlineTable, useEval } from "./results";
import { Treatment, Wordmark } from "./signal";

const REPO = "https://github.com/Atheeq1821/claimbridge";

const DETAIL = snapDetail as unknown as ClaimDetail;
const GRAPH = snapGraph as unknown as { nodes: GraphNode[]; edges: GraphEdge[] };

const PAIRS = [
  {
    claim: "It refuses precedents the policy no longer supports.",
    proof:
      "Every lesson in memory is scoped to the policy versions it was verified under. When the clause changes, the Verifier marks the precedent superseded and names the clause that replaced it.",
    tag: <Treatment kind="negative" label="Superseded by §4.2 (2026)" size={12} />,
  },
  {
    claim: "It coordinates five agents through the graph alone.",
    proof:
      "No queue, no messages. Each agent leases a claim with one atomic write and commits with a fencing token. Kill one mid-step and another resumes from the checkpoint.",
    tag: <span className="font-mono text-[11.5px] text-ink-3">Lease · Checkpoint · CaseEvent</span>,
  },
  {
    claim: "It cites a graph node for every line it writes.",
    proof:
      "Published advice comes from graph facts and reviewed playbook templates. A valid citation ID alone cannot admit an invented instruction.",
    tag: <Treatment kind="positive" label="Followed · F-CODING" size={12} />,
  },
];

const PIPELINE = [
  ["Intake", "Pins the policy version in force on the service date and reads the denial."],
  ["Retrieval", "Pulls candidate precedents: by graph structure first, text similarity second."],
  ["Verifier", "Rules on every precedent in Cypher: version, clause, conditions, contradictions."],
  ["Planner", "Writes the plan. Every item must cite a node the Verifier returned."],
  ["Curator", "Turns a verified outcome into memory, or marks memory stale when policy changes."],
];

function Stats() {
  const { data } = useEval();
  const cb = data?.systems.claimbridge?.metrics;
  const rag = data?.systems.baseline_rag?.metrics;
  const pctOf = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);
  const items = [
    { k: "Claims fully correct", a: pctOf(cb?.all_correct), b: pctOf(rag?.all_correct) },
    { k: "Relied on a precedent that does not apply", a: pctOf(cb?.M4_wrong_precedent_rate), b: pctOf(rag?.M4_wrong_precedent_rate) },
    { k: "Other policyholders' details exposed", a: cb?.M9_tenant_fields_leaked ?? "—", b: rag?.M9_tenant_fields_leaked ?? "—" },
  ];
  return (
    <dl className="grid gap-px overflow-hidden rounded-[12px] border border-rule bg-rule sm:grid-cols-3">
      {items.map((it) => (
        <div key={it.k} className="bg-wash px-5 py-5">
          <dt className="text-[12.5px] text-ink-3">{it.k}</dt>
          <dd className="mt-2 flex items-baseline gap-3">
            <span className="text-[36px] font-semibold leading-none tracking-[-0.04em] text-ink tabular">{String(it.a)}</span>
            <span className="text-[13px] text-ink-3 tabular">vs {String(it.b)} plain RAG</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Results() {
  const { data, error } = useEval();
  if (error) return <p className="text-[13px] text-ink-3">Results are in eval/results/latest.md in the repository.</p>;
  if (!data) return <div className="h-72 animate-pulse rounded-[12px] bg-wash" />;
  const ch = data.chaos;
  return (
    <>
      <Stats />
      <div className="mt-6 overflow-x-auto rounded-[12px] border border-rule bg-wash p-4 sm:p-5">
        <HeadlineTable data={data} compact />
      </div>
      {ch && (
        <p className="mt-4 max-w-[80ch] text-[14px] text-ink-2">
          Under {ch.kills} random hard kills, {ch.steps_interrupted} interrupted a step in progress; every one was resumed by another worker,
          with {ch.duplicate_step_outputs} duplicate outputs and {ch.correct} of {ch.claims} claims correct.
        </p>
      )}
    </>
  );
}

export function Landing() {
  return (
    <div className="min-h-dvh overflow-x-clip bg-paper">
      <header className="sticky top-0 z-30 border-b border-rule/60 bg-paper/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1200px] items-center justify-between gap-6 px-4 sm:px-8">
          <Link href="/" aria-label="ClaimBridge home">
            <Wordmark />
          </Link>
          <nav className="flex items-center gap-1 text-[13px] sm:gap-2">
            <a href="#how" className="hidden rounded-[7px] px-2.5 py-1.5 text-ink-2 hover:text-ink sm:inline">
              How it works
            </a>
            <a href="#results" className="hidden rounded-[7px] px-2.5 py-1.5 text-ink-2 hover:text-ink sm:inline">
              Results
            </a>
            <a href={REPO} className="hidden rounded-[7px] px-2.5 py-1.5 text-ink-2 hover:text-ink sm:inline">
              Source
            </a>
            <Link href="/console" className="ml-1 inline-flex h-8 items-center gap-1.5 rounded-[8px] bg-ink px-3 font-medium text-paper hover:bg-white">
              Open console <ArrowRight size={14} aria-hidden />
            </Link>
          </nav>
        </div>
      </header>

      <section className="relative">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-[520px]"
          style={{ background: "radial-gradient(60% 60% at 50% 0%, rgb(143 168 255 / 0.13), transparent 70%)" }}
        />
        <div className="relative mx-auto max-w-[1200px] px-4 pb-10 pt-16 text-center sm:px-8 sm:pt-24">
          <p className="rise inline-flex items-center gap-2 rounded-full border border-rule-2 bg-wash px-3 py-1 text-[12px] text-ink-2">
            <span className="size-1.5 rounded-full bg-link" aria-hidden />
            FalkorDB Graph Hacks · Track 02, agent memory and coordination · Track 01, agents that act on connected data
          </p>
          <h1
            className="rise mx-auto mt-6 max-w-[16ch] text-[clamp(40px,7vw,76px)] font-semibold leading-[1.02] tracking-[-0.045em] text-ink"
            style={{ animationDelay: "60ms" }}
          >
            Memory that knows when it&apos;s wrong.
          </h1>
          <p className="rise mx-auto mt-5 max-w-[58ch] text-[17px] leading-relaxed text-ink-2" style={{ animationDelay: "120ms" }}>
            An AI caseworker for denied health-insurance claims. Five agents reuse verified wins through a FalkorDB graph, and refuse the
            ones the current policy no longer supports.
          </p>
          <div className="rise mt-8 flex flex-wrap justify-center gap-3" style={{ animationDelay: "180ms" }}>
            <Link href="/console" className="inline-flex h-10 items-center gap-2 rounded-[9px] bg-ink px-4 text-[14px] font-medium text-paper hover:bg-white">
              Open the console <ArrowRight size={15} aria-hidden />
            </Link>
            <a
              href={REPO}
              className="inline-flex h-10 items-center gap-2 rounded-[9px] border border-rule-2 bg-wash px-4 text-[14px] font-medium text-ink hover:border-ink-3"
            >
              <GitBranch size={15} aria-hidden /> Source
            </a>
          </div>
        </div>

        {/* The product, working: a real run of claim EV-T1-01 replayed from the graph. */}
        <div className="relative mx-auto max-w-[1200px] px-4 pb-20 sm:px-8">
          <figure className="rounded-[16px] border border-rule-2 bg-wash p-2 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.8)]">
            <div className="flex items-center gap-3 border-b border-rule px-3 pb-2.5 pt-1.5">
              <span className="flex gap-1.5" aria-hidden>
                <span className="size-2.5 rounded-full bg-rule-2" />
                <span className="size-2.5 rounded-full bg-rule-2" />
                <span className="size-2.5 rounded-full bg-rule-2" />
              </span>
              <span className="truncate font-mono text-[11.5px] text-ink-3">console / claims / EV-T1-01 · graph replay</span>
            </div>
            <div className="p-3 text-left sm:p-4">
              <GraphReplay detail={DETAIL} graph={GRAPH} stepMs={1700} />
            </div>
          </figure>
          <figcaption className="mt-3 text-center text-[12.5px] text-ink-3">
            A recorded run on synthetic data: an MRI denial where a remembered win was learned under the 2025 policy. Click any node to see
            what it contributed.
          </figcaption>
        </div>
      </section>

      <section className="border-t border-rule">
        <div className="mx-auto grid max-w-[1200px] gap-px px-4 py-20 sm:px-8 md:grid-cols-3 md:gap-8">
          {PAIRS.map((p) => (
            <div key={p.claim} className="border-t border-rule py-6 first:border-t-0 md:border-t-0 md:py-0">
              <h3 className="text-[19px] font-semibold leading-snug tracking-[-0.02em] text-ink">{p.claim}</h3>
              <p className="mt-3 text-[14px] leading-relaxed text-ink-2">{p.proof}</p>
              <p className="mt-4">{p.tag}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="how" className="scroll-mt-14 border-t border-rule">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-8">
          <h2 className="max-w-[24ch] text-[clamp(28px,3.4vw,40px)] font-semibold leading-[1.1] tracking-[-0.035em]">
            Five agents. One graph. No messages between them.
          </h2>
          <p className="mt-4 max-w-[68ch] text-[15px] text-ink-2">
            Each agent is its own process. It leases a claim with one atomic write, does one step and commits, fenced so a worker that lost its
            lease cannot overwrite the next one. A caseworker approves every recommendation and records the real outcome, which is what memory
            learns from.
          </p>
          <ol className="mt-10 grid gap-px overflow-hidden rounded-[12px] border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-5">
            {PIPELINE.map(([name, job], i) => (
              <li key={name} className="bg-wash px-5 py-5">
                <p className="font-mono text-[11.5px] text-ink-3 tabular">0{i + 1}</p>
                <h3 className="mt-2 text-[16px] font-semibold tracking-[-0.02em]">{name}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{job}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="results" className="scroll-mt-14 border-t border-rule">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-8">
          <h2 className="max-w-[26ch] text-[clamp(28px,3.4vw,40px)] font-semibold leading-[1.1] tracking-[-0.035em]">
            Measured on synthetic claims. Open to inspection.
          </h2>
          <p className="mt-4 max-w-[70ch] text-[15px] text-ink-2">
            Compare complete systems on the same authored scenarios. ClaimBridge adds structured policy rules and curated memory;
            these results do not isolate the database contribution or predict real appeal outcomes.
          </p>
          <div className="mt-10">
            <Results />
          </div>
          <Link href="/console/evaluation" className="mt-6 inline-flex items-center gap-1.5 text-[14px] font-medium text-link hover:underline">
            Full evaluation, including the failures <ArrowRight size={15} aria-hidden />
          </Link>
        </div>
      </section>

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-start justify-between gap-6 px-4 py-10 text-[12.5px] leading-relaxed text-ink-3 sm:px-8">
          <div className="max-w-[62ch] space-y-2">
            <Wordmark />
            <p>
              All insurers, plans, people and claims are fictional. ClaimBridge recommends; a person approves. It does not approve claims or
              give legal advice.
            </p>
            <p>Built with FalkorDB, FastAPI and Next.js. AI assists intake; published plans use graph templates. AI development assistance is disclosed in the repository.</p>
          </div>
          <div className="flex gap-5">
            <Link href="/console" className="text-ink-2 hover:text-ink">
              Console
            </Link>
            <a href={REPO} className="text-ink-2 hover:text-ink">
              Source
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
