// Evidence-graph replay: plays one claim's processing as the agents did it, step by step,
// from the graph the API returns. Imperative SVG (no React state per frame) so motion is smooth.
import type { ClaimDetail, GraphEdge, GraphNode } from "./api";
import { LEARNED_CAVEAT, conditionFailure, requirementOrigin, splitSources, supportView } from "./explain";

type Sig = "pos" | "neg" | "cau" | "neu";
const SIGNAL: Record<string, Sig> = {
  ACCEPTED: "pos", VERSION_DRIFT: "neg", CONTRADICTED: "neg",
  CONDITION_UNMET: "cau", LINEAGE_MISMATCH: "cau", REASON_MISMATCH: "neu", CANDIDATE: "neu",
};
const LABEL: Record<string, string> = {
  ACCEPTED: "Followed", VERSION_DRIFT: "Superseded", CONTRADICTED: "Contradicted",
  CONDITION_UNMET: "Distinguished", LINEAGE_MISMATCH: "Distinguished", REASON_MISMATCH: "Not relevant", CANDIDATE: "Under review",
};
export const DISPO_TEXT: Record<string, string> = {
  APPEAL_VIABLE: "Appeal is viable",
  APPEAL_NEEDS_EVIDENCE: "Appeal needs evidence first",
  NO_BASIS_ESCALATE: "No basis for appeal — escalate",
};
const NODE_W = 188, NODE_H = 50, GAP = 14, COLS = [0, 232, 476, 728];
const SVGNS = "http://www.w3.org/2000/svg";
const PLAN = "PLAN";

type Info = {
  kind: string; title: string; signal?: Sig; verdict?: string; lead?: string; why?: string; quote?: string;
  facts?: [string, string][]; items?: [string, string, string[]][]; cypher?: string;
};
export type Step = { agent: string; who?: string; title: string; ts?: number; show: string[]; edges: [string, string][]; verdict?: [string, string]; focus: string | null; say: string };
type Script = { steps: Step[]; nodes: (GraphNode | { id: string; kind: "plan"; label: string })[]; info: Record<string, Info>; edgeMeta: Record<string, Partial<GraphEdge>>; claimId: string; noBasis: boolean };

const fmtDate = (i?: number | null) =>
  i && i < 99990000
    ? new Date(Date.UTC(Math.floor(i / 1e4), Math.floor(i / 100) % 100 - 1, i % 100)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    : "open-ended";
const year = (cid?: string | null) => (cid || "").match(/C-(\d{4})-/)?.[1] || "";
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

export function buildScript(d: ClaimDetail, gr: { nodes: GraphNode[]; edges: GraphEdge[] }): Script {
  const verdicts = Object.fromEntries(d.verdicts.map((v) => [v.finding_id, v]));
  const ev = (t: string) => d.timeline.find((e) => e.type === t);
  const clauseId = d.clause?.clause_id;
  const rec = d.recommendation;
  const req = Object.fromEntries(d.requirements.map((r) => [r.code, r]));
  const noBasis = rec?.disposition === "NO_BASIS_ESCALATE";
  const claimId = d.claim.claim_id;
  const info: Record<string, Info> = {};

  info[claimId] = {
    kind: "Claim", title: `${claimId} · ${d.service}`,
    lead: `The starting point. ${d.tenant}'s claim was denied${d.reason_name ? `: ${d.reason_name.toLowerCase()}` : ""}.`,
    facts: [["Service date", fmtDate(d.claim.service_date)], ["Filed", `${d.claim.filing_lag_days} days later`],
      ["Emergency", d.claim.is_emergency ? "yes" : "no"], ["In network", d.claim.in_network ? "yes" : "no"],
      ["Evidence on file", d.evidence.map((e) => e.name).join(", ") || "none"]],
    quote: d.notice,
  };
  if (d.version) info[d.version.version_id] = {
    kind: "Policy version", title: `LumenCare Silver ${d.version.label}`,
    lead: `Pinned by Intake: the service date (${fmtDate(d.claim.service_date)}) falls inside this version. Every later check — clauses, precedents, evidence — is scoped to it.`,
    facts: [["In force", `${fmtDate(d.version.effective_from)} → ${fmtDate(d.version.effective_to)}`]],
    cypher: "MATCH (c:Claim {claim_id: $cid}), (v:PolicyVersion)\nWHERE v.effective_from <= c.service_date\n  AND c.service_date < v.effective_to\nMERGE (c)-[:GOVERNED_BY]->(v)",
  };
  if (d.clause && clauseId) info[clauseId] = {
    kind: "Cited clause", title: `§${d.clause.section} ${d.clause.title}${d.version ? ` (${d.version.label})` : ""}`,
    lead: `The denial notice cites Section ${d.clause.section}; Intake resolved it to this clause in the governing version. Its terms set the policy's evidence requirements.`,
    quote: d.clause.text,
    facts: [["Policy requires", d.requirements.filter((r) => requirementOrigin(r) !== "learned").map((r) => r.name).join(", ") || "nothing"]],
    cypher: "MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(:PolicyVersion)\n      -[:CONTAINS]->(cl:Clause {section: $section})\nMERGE (notice)-[:CITES]->(cl)",
  };

  const findings = gr.nodes.filter((n) => n.kind === "finding");
  findings.forEach((n) => {
    const v = verdicts[n.id];
    if (!v) return;
    const why: Record<string, string> = {
      VERSION_DRIFT: `Superseded by §${v.learned_section} (${year(v.governing)}). It was learned under the ${year(v.learned_on)} clause, which the policy in force has changed.`,
      CONTRADICTED: `Contradicted: ${v.contradicted_by.length} later verified appeal${v.contradicted_by.length === 1 ? " was" : "s were"} upheld on the same facts.`,
      CONDITION_UNMET: `Distinguished: ${conditionFailure(v, d.claim)}.`,
      LINEAGE_MISMATCH: `Distinguished: it concerns §${v.learned_section}, a different clause from the one this denial cites.`,
      ACCEPTED: `Followed: it applies under the policy in force (checked for ${v.valid_in.join(", ") || "no version"}), and this claim meets its conditions.`,
      CANDIDATE: "Retrieved from memory; the Verifier has not ruled yet.",
    };
    info[n.id] = {
      kind: "Precedent (Finding)", title: n.id, signal: SIGNAL[v.code], verdict: LABEL[v.code], lead: v.statement, why: why[v.code],
      facts: [["Recorded wins", String(v.support)], ["Contradicted by", String(v.contradicted_by.length)], ["Support score", v.support > 0 ? `${Math.round((v.confidence || 0) * 100)}%` : "none yet"],
        ["Applies in", v.valid_in.join(", ") || "—"], ["Found by", v.source]],
      cypher: "MATCH (c)-[k:CONSIDERED]->(f:Finding)-[:ON_LINEAGE]->(fl:Clause)\nOPTIONAL MATCH (f)-[vi:VALID_IN]->(v)   // v = governing version\nRETURN CASE\n  WHEN fl.lineage_id <> cc.lineage_id THEN 'LINEAGE_MISMATCH'\n  WHEN vi IS NULL THEN 'VERSION_DRIFT'\n  WHEN f.status = 'CONTRADICTED' THEN 'CONTRADICTED'\n  WHEN f.req_emergency <> c.is_emergency THEN 'CONDITION_UNMET'\n  WHEN f.req_in_network <> c.in_network THEN 'CONDITION_UNMET'\n  ELSE 'ACCEPTED' END",
    };
  });
  gr.nodes.filter((n) => n.kind === "clause" && n.id !== clauseId).forEach((n) => {
    const sup = gr.edges.find((e) => e.label === "supersedes" && e.from === n.id);
    info[n.id] = {
      kind: sup ? "Clause in force" : "Clause a precedent was learned under", title: n.id,
      lead: sup ? `The ${year(n.id)} version of this clause. It supersedes ${sup.to}, so precedents learned there no longer apply.` : `A precedent was learned from verified wins under this clause (${year(n.id)}).`,
    };
  });
  gr.nodes.filter((n) => n.kind === "resolution").forEach((n) => {
    info[n.id] = { kind: "Verified outcome", title: n.id, lead: "A later appeal with the same facts that was upheld. It counts against the precedent it contradicts." };
  });
  gr.nodes.filter((n) => n.kind === "evidence").forEach((n) => {
    const r = req[n.id];
    const origin = r ? requirementOrigin(r) : "policy";
    const { policy, learned } = splitSources(r?.sources);
    const status = r?.satisfied ? "on file" : noBasis ? "not needed" : "missing";
    const tail = r?.satisfied ? "It is on file." : noBasis ? "It is moot: there is no basis for an appeal." : "It is missing, so it goes into the plan.";
    let lead: string;
    if (origin === "learned") lead = `Suggested by precedent ${learned.join(", ")}: ${LEARNED_CAVEAT}. ${r?.satisfied ? "It is already on file." : noBasis ? "It is moot: there is no basis for an appeal." : "It is missing, so the plan asks a caseworker whether to include it."}`;
    else if (origin === "both") lead = `Required by the governing clause${d.clause ? ` (§${d.clause.section})` : ""}, and also suggested by precedent ${learned.join(", ")}. ${tail}`;
    else lead = `Required by the governing clause${d.clause ? ` (§${d.clause.section})` : ""}. ${tail}`;
    info[n.id] = {
      kind: origin === "learned" ? "Suggested evidence (learned)" : "Policy requirement", title: n.label, lead,
      facts: [["Status", status], ["Basis", origin === "learned" ? "Observed association" : origin === "both" ? "Policy and observed association" : "Policy requirement"],
        ["Source", [...policy.map((x) => `clause ${x}`), ...learned.map((x) => `precedent ${x}`)].join(" · ") || "—"]],
      cypher: origin === "learned"
        ? "MATCH (c)-[:CONSIDERED {verdict: 'ACCEPTED'}]->(f:Finding)-[:NEEDS_EVIDENCE]->(e:EvidenceType)\nOPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(:Evidence)-[:OF_TYPE]->(e)\nRETURN e.code, f.finding_id, count(*) > 0 AS satisfied"
        : "MATCH (c)-[:HAS_NOTICE]->()-[:CITES]->(cl:Clause)-[:REQUIRES]->(e:EvidenceType)\nOPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(:Evidence)-[:OF_TYPE]->(e)\nRETURN e.code, cl.clause_id, count(*) > 0 AS satisfied" + (origin === "both" ? "\n// plus any accepted Finding -[:NEEDS_EVIDENCE]-> e" : ""),
    };
  });
  if (rec) info[PLAN] = {
    kind: "Recommendation", title: DISPO_TEXT[rec.disposition] || "Plan", lead: rec.summary,
    items: rec.items.map((i) => [i.kind, i.text, i.cites]),
    facts: [["Precedent support score", `${supportView(rec, d.verdicts).value}${supportView(rec, d.verdicts).detail ? ` (${supportView(rec, d.verdicts).detail})` : ""}`], ["Published plan", "Graph templates"],
      ["Citation guard", `dropped ${rec.guard_dropped || 0}, added ${rec.guard_added || 0}`]],
  };

  const steps: Step[] = [];
  steps.push({ agent: "Caseworker", title: "Claim filed", ts: ev("SUBMITTED")?.ts, show: [claimId], edges: [], focus: claimId, say: "The denied claim enters the graph with its notice and the evidence on file." });
  if (d.version) steps.push({ agent: "Intake", who: ev("INTAKE_DONE")?.agent, title: "Pins the governing policy version", ts: ev("INTAKE_DONE")?.ts, show: [d.version.version_id], edges: [[claimId, d.version.version_id]], focus: d.version.version_id, say: info[d.version.version_id].lead! });
  if (d.clause && clauseId) steps.push({ agent: "Intake", who: ev("INTAKE_DONE")?.agent, title: `Resolves the cited clause §${d.clause.section}`, ts: ev("INTAKE_DONE")?.ts, show: [clauseId], edges: [[claimId, clauseId], ...(d.version ? [[d.version.version_id, clauseId] as [string, string]] : [])], focus: clauseId, say: info[clauseId].lead! });
  const listed = findings.filter((f) => verdicts[f.id]);
  if (listed.length) steps.push({ agent: "Retrieval", who: ev("RETRIEVAL_DONE")?.agent, title: `Pulls ${listed.length} candidate precedent${listed.length === 1 ? "" : "s"} from memory`, ts: ev("RETRIEVAL_DONE")?.ts, show: listed.map((f) => f.id), edges: listed.map((f) => [claimId, f.id] as [string, string]), focus: null, say: "Candidates come by graph structure first (same denial reason), then text similarity. Nothing is accepted yet." });
  listed.forEach((f) => {
    const v = verdicts[f.id];
    if (v.code === "CANDIDATE") return;
    const extraNodes: string[] = [], extraEdges: [string, string][] = [];
    gr.edges.filter((e) => e.from === f.id).forEach((e) => { extraNodes.push(e.to); extraEdges.push([e.from, e.to]); });
    gr.edges.filter((e) => e.label === "supersedes" && extraNodes.includes(e.to)).forEach((e) => { extraNodes.push(e.from); extraEdges.push([e.from, e.to]); });
    steps.push({ agent: "Verifier", who: ev("VERIFIER_DONE")?.agent, title: `Rules on ${f.id}: ${LABEL[v.code]}`, ts: ev("VERIFIER_DONE")?.ts, show: extraNodes, edges: extraEdges, verdict: [f.id, v.code], focus: f.id, say: info[f.id].why || "" });
  });
  const evNodes = gr.nodes.filter((n) => n.kind === "evidence").map((n) => n.id);
  if (evNodes.length && rec) {
    const nLearned = d.requirements.filter((r) => requirementOrigin(r) !== "policy").length;
    const nPolicy = d.requirements.length - d.requirements.filter((r) => requirementOrigin(r) === "learned").length;
    steps.push({
      agent: "Planner", who: ev("PLANNER_DONE")?.agent,
      title: nLearned ? "Checks required and suggested evidence" : "Checks the evidence the clause requires",
      ts: ev("PLANNER_DONE")?.ts, show: evNodes,
      edges: gr.edges.filter((e) => evNodes.includes(e.to)).map((e) => [e.from, e.to] as [string, string]), focus: null,
      say: noBasis
        ? "The evidence is listed, but a gate already ruled out any appeal."
        : `${nPolicy} required by the clause${nLearned ? `; ${nLearned} also suggested by a followed precedent (${LEARNED_CAVEAT})` : ""}. Each is matched against the documents on file.`,
    });
  }
  if (rec) steps.push({ agent: "Planner", who: ev("PLANNER_DONE")?.agent, title: DISPO_TEXT[rec.disposition] || "Writes the plan", ts: ev("PLANNER_DONE")?.ts, show: [PLAN], edges: [[claimId, PLAN]], focus: PLAN, say: rec.summary });

  const nodes: Script["nodes"] = [...gr.nodes.filter((n) => n.kind !== "evidence" || rec), ...(rec ? [{ id: PLAN, kind: "plan" as const, label: DISPO_TEXT[rec.disposition] || "Plan" }] : [])];
  const edgeMeta: Script["edgeMeta"] = {};
  gr.edges.forEach((e) => (edgeMeta[`${e.from}>${e.to}`] = e));
  return { steps, nodes, info, edgeMeta, claimId, noBasis };
}

function layout(sc: Script) {
  const col = (n: Script["nodes"][number]) =>
    n.kind === "claim" ? 0
      : n.kind === "version" || n.kind === "evidence" || (n.kind === "clause" && (n as GraphNode).sub?.startsWith("C-")) ? 1
      : n.kind === "finding" || n.kind === "plan" ? 2 : 3;
  const cols: Script["nodes"][] = [[], [], [], []];
  sc.nodes.forEach((n) => cols[col(n)].push(n));
  const rank1 = (n: Script["nodes"][number]) => (n.kind === "version" ? 0 : n.kind === "clause" ? 1 : 2);
  cols[1].sort((a, b) => rank1(a) - rank1(b));
  cols[2].sort((a, b) => Number(a.kind === "plan") - Number(b.kind === "plan"));
  const H = Math.max(3, ...cols.map((c) => c.length)) * (NODE_H + GAP);
  const pos: Record<string, { x: number; y: number }> = {};
  cols.forEach((c, ci) => {
    const top = (H - c.length * (NODE_H + GAP)) / 2;
    c.forEach((n, i) => (pos[n.id] = { x: COLS[ci], y: top + i * (NODE_H + GAP) }));
  });
  return { pos, H };
}

function el<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}, parent?: Element) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, String(attrs[k]));
  parent?.appendChild(n);
  return n;
}

const GLYPH: Record<Sig, string> = {
  neg: '<path d="M5.2 1h5.6L15 5.2v5.6L10.8 15H5.2L1 10.8V5.2z" class="gf"/><path d="M4.6 7h6.8v2H4.6z" fill="#fff"/>',
  cau: '<path d="M8 1.2 15.2 14H.8z" class="gf"/><path d="M7.1 5.4h1.8l-.3 4.6H7.4zM7.1 11.2h1.8V13H7.1z" fill="#fff"/>',
  pos: '<path d="M8 .9 15.1 8 8 15.1.9 8z" class="gf"/><path d="M7.1 4.6h1.8v2.5h2.5v1.8H8.9v2.5H7.1V8.9H4.6V7.1h2.5z" fill="#fff"/>',
  neu: '<circle cx="8" cy="8" r="6" fill="none" class="gs" stroke-width="2.2"/><circle cx="8" cy="8" r="1.6" class="gf"/>',
};

export type ReplayHandle = { destroy(): void; state(): { idx: number; atEnd: boolean } };

export function mountReplay(
  root: HTMLElement,
  data: { detail: ClaimDetail; graph: { nodes: GraphNode[]; edges: GraphEdge[] } },
  opts: { stepMs?: number; autoplay?: boolean; startAt?: number; animateFrom?: number } = {},
): ReplayHandle {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sc = buildScript(data.detail, data.graph);
  const { pos, H } = layout(sc);
  const W = COLS[3] + NODE_W + 40;
  const timers: ReturnType<typeof setTimeout>[] = [];
  const later = (fn: () => void, ms: number) => timers.push(setTimeout(fn, ms));
  let destroyed = false;

  root.innerHTML = `
    <div class="cbg-bar">
      <button class="cbg-btn cbg-play" type="button">Pause</button>
      <button class="cbg-btn" data-a="prev" type="button" aria-label="Previous step">‹ Step</button>
      <button class="cbg-btn" data-a="next" type="button" aria-label="Next step">Step ›</button>
      <button class="cbg-btn" data-a="replay" type="button">Replay</button>
      <div class="cbg-status" aria-live="polite"></div>
    </div>
    <ol class="cbg-rail"></ol>
    <div class="cbg-body"><div class="cbg-stage"><p class="cbg-scrollhint">Scroll sideways to follow the graph →</p></div><aside class="cbg-insp"></aside></div>`;
  const play = root.querySelector<HTMLButtonElement>(".cbg-play")!;
  const status = root.querySelector<HTMLDivElement>(".cbg-status")!;
  const rail = root.querySelector<HTMLOListElement>(".cbg-rail")!;
  const stage = root.querySelector<HTMLDivElement>(".cbg-stage")!;
  const insp = root.querySelector<HTMLElement>(".cbg-insp")!;
  sc.steps.forEach((s, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<button type="button" title="${esc(s.title)}">${esc(s.agent)}</button>`;
    li.querySelector("button")!.onclick = () => go(i, true);
    rail.appendChild(li);
  });

  const svg = el("svg", { viewBox: `-6 -30 ${W} ${H + 40}`, class: "cbg-svg", role: "img", "aria-label": "Evidence graph replay" }, stage);
  ["Claim", "Policy & evidence", "Precedents · plan", "Grounds"].forEach((t, i) => (el("text", { x: COLS[i], y: -14, class: "cbg-colhead" }, svg).textContent = t.toUpperCase()));
  const gEdges = el("g", {}, svg), gTokens = el("g", {}, svg), gNodes = el("g", {}, svg);

  const trim = (s: string, k: number) => (s.length > k ? s.slice(0, k - 1) + "…" : s);
  const sub = (n: Script["nodes"][number]) => {
    if (n.kind === "claim") return data.detail.service;
    if (n.kind === "finding") return "under review";
    if (n.kind === "evidence") { const r = data.detail.requirements.find((x) => x.code === n.id); const st = r?.satisfied ? "on file" : sc.noBasis ? "not needed" : "missing"; return r && requirementOrigin(r) === "learned" ? `suggested · ${st}` : st; }
    if (n.kind === "resolution") return "verified outcome: upheld";
    if (n.kind === "plan") return `${data.detail.recommendation?.items.length || 0} cited items`;
    return trim((n as GraphNode).sub || "", 28);
  };
  const nodeEls: Record<string, { g: SVGGElement; t2: SVGTextElement; sig: SVGGElement; n: Script["nodes"][number] }> = {};
  sc.nodes.forEach((n) => {
    const p = pos[n.id];
    const g = el("g", { class: `cbg-node k-${n.kind} hidden`, transform: `translate(${p.x} ${p.y})`, tabindex: 0, role: "button", "aria-label": `${n.label}: show what it contributed` }, gNodes);
    el("rect", { width: NODE_W, height: NODE_H, class: "cbg-box" }, g);
    const sig = el("g", {}, g);
    el("text", { x: 12, y: 21, class: "cbg-t1" }, g).textContent = (n.kind === "plan" ? "Plan · " : "") + trim(n.label, 24);
    const t2 = el("text", { x: 12, y: 38, class: "cbg-t2" }, g);
    t2.textContent = sub(n);
    g.addEventListener("click", () => inspect(n.id, true));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inspect(n.id, true); } });
    nodeEls[n.id] = { g, t2, sig, n };
  });

  const edgeEls: Record<string, { path: SVGPathElement; cls: string }> = {};
  sc.steps.forEach((s) => s.edges.forEach(([a, b]) => {
    const key = `${a}>${b}`;
    if (edgeEls[key] || !pos[a] || !pos[b]) return;
    const A = pos[a], B = pos[b], same = A.x === B.x, back = B.x < A.x;
    const x1 = back ? A.x : A.x + NODE_W, y1 = A.y + NODE_H / 2, x2 = same || back ? B.x + NODE_W : B.x, y2 = B.y + NODE_H / 2;
    const d = same ? `M${x1} ${y1} C${x1 + 30} ${y1}, ${x2 + 30} ${y2}, ${x2} ${y2}`
      : back ? `M${x1} ${y1} C${x1 - 40} ${y1}, ${x2 + 40} ${y2}, ${x2} ${y2}`
      : `M${x1} ${y1} C${x1 + 40} ${y1}, ${x2 - 40} ${y2}, ${x2} ${y2}`;
    const meta = sc.edgeMeta[key] || {};
    const cls = meta.state === "missing" && !sc.noBasis ? "e-missing" : meta.origin === "learned" ? "e-learned" : meta.code ? `e-${SIGNAL[meta.code] || "neu"}` : "e-neu";
    edgeEls[key] = { path: el("path", { d, class: `cbg-edge ${cls} hidden` }, gEdges) as SVGPathElement, cls };
  }));

  let idx = -1;
  let playing = !reduce && opts.autoplay !== false;
  let pinned: string | null = null;
  let loopTimer: ReturnType<typeof setTimeout> | null = null;

  function reveal(s: Step, animate: boolean) {
    s.edges.forEach(([a, b]) => {
      const e = edgeEls[`${a}>${b}`];
      if (!e) return;
      e.path.classList.remove("hidden");
      if (!animate || reduce) return;
      const L = e.path.getTotalLength();
      e.path.style.strokeDasharray = `${L}`;
      e.path.style.strokeDashoffset = `${L}`;
      e.path.getBoundingClientRect();
      e.path.style.transition = "stroke-dashoffset 700ms cubic-bezier(.16,1,.3,1)";
      e.path.style.strokeDashoffset = "0";
      later(() => { e.path.style.strokeDasharray = ""; e.path.style.transition = ""; }, 760);
      const tok = el("circle", { r: 4.5, class: "cbg-token" }, gTokens);
      const t0 = performance.now();
      const tick = (t: number) => {
        if (destroyed) return;
        const k = Math.min(1, (t - t0) / 700);
        const p = e.path.getPointAtLength(L * (1 - Math.pow(1 - k, 3)));
        tok.setAttribute("cx", String(p.x));
        tok.setAttribute("cy", String(p.y));
        if (k < 1) requestAnimationFrame(tick); else tok.remove();
      };
      requestAnimationFrame(tick);
    });
    const delay = animate && !reduce ? 520 : 0;
    const showNodes = () => s.show.forEach((id) => nodeEls[id]?.g.classList.remove("hidden"));
    if (delay) later(showNodes, delay); else showNodes();
    if (s.verdict) { const [f, c] = s.verdict; if (delay) later(() => setVerdict(f, c, animate), delay + 120); else setVerdict(f, c, false); }
  }
  function setVerdict(fid: string, code: string, animate: boolean) {
    const ne = nodeEls[fid];
    if (!ne) return;
    const k = SIGNAL[code] || "neu";
    ne.g.setAttribute("class", `cbg-node k-finding v-${k}`);
    ne.sig.innerHTML = "";
    const outer = el("g", { transform: `translate(${NODE_W - 28} 10)` }, ne.sig);
    const inner = el("g", { class: `g-glyph s-${k}${animate && !reduce ? " cbg-stamp" : ""}` }, outer);
    inner.innerHTML = GLYPH[k];
    ne.t2.textContent = LABEL[code];
    const e = edgeEls[`${sc.claimId}>${fid}`];
    if (e) e.path.setAttribute("class", `cbg-edge e-${k}`);
  }
  function resetAll() {
    Object.values(nodeEls).forEach((ne) => { ne.g.setAttribute("class", `cbg-node k-${ne.n.kind} hidden`); ne.sig.innerHTML = ""; ne.t2.textContent = sub(ne.n); });
    Object.values(edgeEls).forEach((e) => e.path.setAttribute("class", `cbg-edge ${e.cls} hidden`));
    gTokens.innerHTML = "";
  }
  function setPlaying(p: boolean) { playing = p; play.textContent = p ? "Pause" : "Play"; play.setAttribute("aria-pressed", String(p)); }
  function go(i: number, user = false, animateLast = true) {
    if (user) setPlaying(false);
    i = Math.max(-1, Math.min(sc.steps.length - 1, i));
    if (i < idx) { resetAll(); for (let j = 0; j <= i; j++) reveal(sc.steps[j], false); }
    else for (let j = idx + 1; j <= i; j++) reveal(sc.steps[j], animateLast && j === i);
    idx = i;
    [...rail.children].forEach((li, j) => (li.className = j < idx ? "done" : j === idx ? "now" : ""));
    const s = sc.steps[idx];
    if (s) {
      const t = s.ts ? new Date(s.ts).toLocaleTimeString("en-GB") : "";
      status.innerHTML = `<b>${idx + 1}/${sc.steps.length}</b> ${esc(s.agent)}${s.who ? ` <code>${esc(s.who)}</code>` : ""} — ${esc(s.title)}${t ? ` <span class="cbg-time">${t}</span>` : ""}`;
      if (!pinned) inspect(s.focus, false, s);
    }
    Object.values(nodeEls).forEach((ne) => ne.g.classList.toggle("focus", ne.n.id === (pinned || s?.focus)));
  }
  function inspect(id: string | null, user: boolean, step?: Step) {
    if (user) { pinned = id; Object.values(nodeEls).forEach((ne) => ne.g.classList.toggle("focus", ne.n.id === id)); }
    const info = id ? sc.info[id] : undefined;
    if (!info) {
      insp.innerHTML = `<p class="cbg-k">${esc(step?.agent)}</p><h4>${esc(step?.title)}</h4><p class="cbg-lead">${esc(step?.say)}</p><p class="cbg-hint">Click any node to see what it contributed to this claim.</p>`;
      return;
    }
    const facts = (info.facts || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
    const items = (info.items || []).map(([k, t, c]) => `<li><span class="cbg-ik">${esc(k.replace(/_/g, " ").toLowerCase())}</span> ${esc(t)}<br><code>${c.map(esc).join(" · ")}</code></li>`).join("");
    insp.innerHTML = `
      <p class="cbg-k">${esc(info.kind)}${user ? ' · <button type="button" class="cbg-unpin">follow the replay</button>' : ""}</p>
      <h4>${info.signal ? `<span class="cbg-chip s-${info.signal}">${esc(info.verdict)}</span>` : ""}${esc(info.title)}</h4>
      ${info.lead ? `<p class="cbg-lead">${esc(info.lead)}</p>` : ""}
      ${info.why ? `<p class="cbg-why s-${info.signal}">${esc(info.why)}</p>` : ""}
      ${info.quote ? `<blockquote>${esc(info.quote)}</blockquote>` : ""}
      ${facts ? `<dl>${facts}</dl>` : ""}
      ${items ? `<ol class="cbg-items">${items}</ol>` : ""}
      ${info.cypher ? `<details><summary>The Cypher that decided this</summary><pre>${esc(info.cypher)}</pre></details>` : ""}`;
    const un = insp.querySelector<HTMLButtonElement>(".cbg-unpin");
    if (un) un.onclick = () => { pinned = null; go(idx); };
  }
  function loop() {
    if (loopTimer) clearTimeout(loopTimer);
    if (!playing || destroyed) return;
    if (idx >= sc.steps.length - 1) { setPlaying(false); return; }
    go(idx + 1);
    loopTimer = setTimeout(loop, opts.stepMs || 1500);
  }
  play.onclick = () => { setPlaying(!playing); if (playing) { if (idx >= sc.steps.length - 1) { resetAll(); idx = -1; } loop(); } };
  root.querySelector<HTMLButtonElement>('[data-a="prev"]')!.onclick = () => go(idx - 1, true);
  root.querySelector<HTMLButtonElement>('[data-a="next"]')!.onclick = () => go(idx + 1, true);
  root.querySelector<HTMLButtonElement>('[data-a="replay"]')!.onclick = () => { resetAll(); idx = -1; pinned = null; setPlaying(true); loop(); };

  if (opts.animateFrom != null && opts.animateFrom >= 0) {
    // Live update: restore the steps already seen, then play the new ones.
    go(Math.min(opts.animateFrom, sc.steps.length - 1), false, false);
    setPlaying(true);
    loopTimer = setTimeout(loop, 300);
  } else if (reduce || opts.autoplay === false) {
    setPlaying(false);
    go(opts.startAt ?? sc.steps.length - 1, false, false);
  } else {
    go(0);
    loopTimer = setTimeout(loop, 900);
  }

  return {
    destroy() { destroyed = true; timers.forEach(clearTimeout); if (loopTimer) clearTimeout(loopTimer); root.innerHTML = ""; },
    state: () => ({ idx, atEnd: idx >= sc.steps.length - 1 }),
  };
}

export function stepCount(d: ClaimDetail, g: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  return buildScript(d, g).steps.length;
}
