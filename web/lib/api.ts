// Typed access to the ClaimBridge API (proxied same-origin under /api).

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Any 401 means the session ended (expiry, revocation, sign-out elsewhere): tell the session gate.
export const SESSION_ENDED = "claimbridge:session-ended";

// The identity this tab is showing; set by the session gate. A response for anyone else is refused.
let signedInAs: string | null = null;
export const setSignedInAs = (subject: string | null) => {
  signedInAs = subject;
};

async function parse(res: Response) {
  const who = res.headers.get("x-claimbridge-subject");
  if (signedInAs && who && who !== signedInAs && typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_ENDED));
    throw new ApiError(401, "You signed in as someone else in another tab. Checking who you are…");
  }
  if (res.ok) return res.json();
  if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_ENDED));
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = body.detail ?? detail;
  } catch {}
  throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function del<T = unknown>(url: string): Promise<T> {
  const res = await fetch(url, { method: "DELETE", headers: { "X-ClaimBridge-Request": "1" } });
  return parse(res);
}

export const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(parse);

export const getWith = (url: string, headers: HeadersInit = {}) => fetch(url, { cache: "no-store", headers }).then(parse);

export async function post<T = unknown>(url: string, body: unknown = {}, headers: HeadersInit = {}): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-ClaimBridge-Request": "1", ...headers },
    body: JSON.stringify(body),
  });
  return parse(res);
}

export type Flag = { finding_id: string; code: string };

export type ClaimRow = {
  claim_id: string;
  tenant_id: string;
  tenant: string;
  service: string;
  service_name: string;
  service_date: number;
  status: string;
  reason: string | null;
  reason_name: string | null;
  version: string | null;
  disposition: string | null;
  lease_owner: string | null;
  attempt: number | null;
  amount: number;
  confidence: number | null;
  trap: string | null;
  note: string | null;
  flags: Flag[];
  updated_at: number | null;
};

export type Verdict = {
  finding_id: string;
  code: string;
  source: string;
  statement: string;
  status: string;
  confidence: number;
  support: number;
  learned_on: string;
  learned_section: string;
  governing: string | null;
  contradicted_by: string[];
  valid_in: string[];
  req_emergency: boolean | null;
  req_in_network: boolean | null;
};

export type RecItem = { order: number; kind: string; text: string; origin: string; cites: string[] };

export type Recommendation = {
  disposition: string;
  summary: string;
  confidence: number;
  support_state?: "NO_PRECEDENT" | "NO_APPEAL_BASIS" | "RECORDED_OUTCOMES";
  uncertainty: string[];
  llm_platform: string | null;
  llm_model: string | null;
  guard_dropped: number;
  guard_added: number;
  approved_by?: string;
  items: RecItem[];
};

export type TimelineEvent = {
  seq: number;
  type: string;
  agent: string;
  step: string | null;
  ts: number;
  payload: Record<string, unknown>;
};

export type ClaimRecord = {
  claim_id: string;
  tenant_id: string;
  status: string;
  service_date: number;
  filed_date: number;
  filing_lag_days: number;
  amount: number;
  in_network: boolean;
  is_emergency: boolean;
  lease_owner?: string | null;
  attempt?: number;
  disposition?: string | null;
};

export type ClaimDetail = {
  claim: ClaimRecord;
  tenant: string;
  service: string;
  notice: string;
  notice_date: number;
  version: { version_id: string; label: string; effective_from: number; effective_to: number } | null;
  clause: { clause_id: string; section: string; title: string; text: string; lineage_id: string } | null;
  reason: string | null;
  reason_name: string | null;
  evidence: {
    code: string;
    name: string;
    submitted: number;
    doc_id?: string;
    declared_by?: string | null;
    verified?: boolean;
    reference?: string | null;
  }[];
  evidence_withdrawn: { name: string; by: string; at: number }[];
  human_review: { reason: string | null; step: string | null; agent: string | null; ts: number | null } | null;
  corrections: { id: string; reason: string; previous_reason: string | null; note: string; reviewer: string; ts: number }[];
  requirements: { code: string; name: string; satisfied: boolean; sources: string[] }[];
  verdicts: Verdict[];
  recommendation: Recommendation | null;
  timeline: TimelineEvent[];
  trap: string | null;
  note: string | null;
};

export type GraphNode = {
  id: string;
  kind: "claim" | "version" | "clause" | "evidence" | "finding" | "resolution";
  label: string;
  sub?: string;
  code?: string;
  status?: string;
  satisfied?: boolean;
  origin?: "policy" | "learned" | "both";
};
export type GraphEdge = { from: string; to: string; label: string; code?: string; state?: string; origin?: "policy" | "learned" };

export type Finding = {
  finding_id: string;
  statement: string;
  status: string;
  support: number;
  wins: number;
  confidence: number;
  origin: string;
  updated_at: number;
  reason: string;
  reason_name: string;
  lineage: string;
  learned_on: string;
  section: string;
  clause_title: string;
  valid_in: string[];
  needs: string[];
  contradictions: number;
  stale_because: string[];
  playbook: string | null;
};

export type Memory = {
  findings: Finding[];
  playbooks: { playbook_id: string; name: string; uses: number; wins: number; reason: string; steps: string[] }[];
  versions: { id: string; label: string; effective_from: number }[];
  next_version: string | null;
};

export type TraceHop = { key: string; from: string; rel: string; to: string; ok: boolean; note: string; break: boolean };
export type PrecedentTrace = { claim_id: string; finding_id: string; code: string; derived_code: string; broken: string | null; hops: TraceHop[]; source: string };

export type ImpactClause = { clause_id: string; version_id: string; section: string; title: string; lineage_id: string; supersedes: string | null; changed: boolean };
export type ImpactNode = { id: string; kind: "clause" | "finding" | "evidence" | "playbook" | "claim"; label: string; sub?: string; status?: string; version?: string };
export type ImpactEdge = { from: string; to: string; label: string; state?: string; code?: string };
export type ClauseImpact = {
  clause_id: string;
  lineage_id: string;
  clauses: ImpactClause[];
  findings: { finding_id: string; status: string; statement: string; learned_on: string; evidence_names: string[]; playbook: string | null; stale_because: string[] }[];
  claims: string[];
  nodes: ImpactNode[];
  edges: ImpactEdge[];
  counts: { clauses: number; changed: number; findings: number; stale: number; evidence: number; claims: number; claims_visible: number; claims_withheld: number };
  cypher: string;
};
export type ClausePick = { clause_id: string; version_id: string; section: string; title: string; lineage_id: string; findings: number; claims: number };

export type Overview = {
  world: string | null;
  statuses: Record<string, number>;
  findings: Record<string, number>;
  workers_alive: number;
  supervisor_alive: boolean;
  llm: { platform: string; model: string; mode: string };
  world_job: { running: boolean; action: string | null; error: string | null };
};

// ---- investigator and graph algorithms

export type InvestigationStep = {
  seq: number;
  round?: number;
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  plain: string;
  result: unknown;
};

export type Investigation = {
  investigation_id: string | null;
  outcome: "investigated" | "investigated_with_template" | "guarded" | "llm_unavailable" | "unknown_claim";
  label: string;
  model: string | null;
  platform: string | null;
  brief: string;
  hint: string | null;
  violations: string[];
  notes: string[];
  rounds: { round: number; cached?: boolean; prompt_tokens?: number | null; completion_tokens?: number | null }[];
  tokens: { prompt: number | null; completion: number | null };
  calls: InvestigationStep[];
};

export type BlastLineage = {
  rank: number;
  lineage_id: string;
  title: string;
  section: string;
  score: number;
  clause_ids: string[];
  findings: string[];
  claims_total: number;
  claims_visible: number;
};

export type BlastRadius = {
  clause_id: string;
  lineage_id: string;
  max_hops: number;
  algorithms: string[];
  counts: { clauses: number; findings: number; outcomes: number; claims_visible: number; claims_withheld: number; farthest_hop: number };
  clauses: { clause_id: string; hops: number; version_id: string }[];
  findings: { finding_id: string; hops: number; status: string }[];
  outcomes: { resolution_id: string; hops: number }[];
  claims: { claim_id: string; hops: number; status: string }[];
  lineage_rank: { rank: number | null; of: number; score: number | null };
};
