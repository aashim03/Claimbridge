// One vocabulary for the whole product: every code the graph writes has exactly one
// name, one citator signal and one sentence, used the same way on every screen.

export type Signal = "negative" | "caution" | "positive" | "neutral";

export const TREATMENT: Record<string, { signal: Signal; label: string; why: string }> = {
  ACCEPTED: { signal: "positive", label: "Followed", why: "Applies to this claim under the governing policy version." },
  VERSION_DRIFT: {
    signal: "negative",
    label: "Superseded",
    why: "Learned under a clause the governing policy version replaced.",
  },
  CONTRADICTED: {
    signal: "negative",
    label: "Contradicted",
    why: "Later verified cases with the same facts were upheld.",
  },
  CONDITION_UNMET: {
    signal: "caution",
    label: "Distinguished",
    why: "Only applies when its conditions are met; this claim does not meet them.",
  },
  LINEAGE_MISMATCH: {
    signal: "caution",
    label: "Distinguished",
    why: "Same denial reason, but it concerns a different policy clause.",
  },
  REASON_MISMATCH: {
    signal: "neutral",
    label: "Not relevant",
    why: "A look-alike notice found by text similarity; different denial reason.",
  },
  CANDIDATE: { signal: "neutral", label: "Under review", why: "Retrieved; the Verifier has not ruled yet." },
};

export const FINDING_STATUS: Record<string, { signal: Signal; label: string; why: string }> = {
  ACTIVE: { signal: "positive", label: "Applies", why: "Matches a clause in the current policy version." },
  STALE: {
    signal: "caution",
    label: "Limited",
    why: "Superseded in the current version; still applies to claims under the versions it was learned on.",
  },
  CONTRADICTED: {
    signal: "negative",
    label: "Contradicted",
    why: "Verified losses under the same conditions outweigh its wins.",
  },
};

export const DISPOSITION: Record<string, { label: string; short: string; tone: Signal }> = {
  APPEAL_VIABLE: { label: "Appeal is viable", short: "Viable", tone: "positive" },
  APPEAL_NEEDS_EVIDENCE: { label: "Appeal needs evidence first", short: "Needs evidence", tone: "caution" },
  NO_BASIS_ESCALATE: { label: "No basis for appeal — escalate", short: "No basis", tone: "negative" },
};

export const STEPS = [
  { status: "RECEIVED", agent: "Intake", label: "Filed" },
  { status: "CLASSIFIED", agent: "Retrieval", label: "Classified" },
  { status: "RETRIEVED", agent: "Verifier", label: "Precedents found" },
  { status: "VERIFIED", agent: "Planner", label: "Verified" },
  { status: "AWAITING_REVIEW", agent: "Caseworker", label: "Awaiting review" },
] as const;

export const STATUS_LABEL: Record<string, string> = {
  NEW: "Not filed",
  RECEIVED: "Filed",
  CLASSIFIED: "Classified",
  RETRIEVED: "Precedents found",
  VERIFIED: "Verified",
  AWAITING_REVIEW: "Awaiting review",
  APPROVED: "Approved",
  VERIFIED_OUTCOME: "Outcome recorded",
  CURATED: "Learned",
  NEEDS_HUMAN: "Needs a person",
};

export const STATUS_ORDER = [
  "NEW",
  "RECEIVED",
  "CLASSIFIED",
  "RETRIEVED",
  "VERIFIED",
  "AWAITING_REVIEW",
  "APPROVED",
  "VERIFIED_OUTCOME",
  "CURATED",
];

export function stepIndex(status: string): number {
  return STATUS_ORDER.indexOf(status);
}

export const TRAPS: Record<string, { name: string; line: string }> = {
  T1: { name: "Version drift", line: "A near-identical past win, under a clause that has since changed." },
  T2: { name: "Wrong clause", line: "Same denial reason, different policy clause." },
  T3: { name: "Missing evidence", line: "The precedent applies, but its evidence is not on file." },
  T4: { name: "Contradicted memory", line: "Later verified cases overturned the lesson." },
  T5: { name: "Condition unmet", line: "The precedent needed an emergency; this was elective." },
  T6: { name: "No basis", line: "The governing terms leave no appeal path." },
  T7: { name: "Tenant isolation", line: "Shared memory, private cases." },
  M: { name: "Memory gain", line: "A verified win becomes the next claim's precedent." },
};

export const ROLE_LABEL: Record<string, string> = {
  intake: "Intake",
  retrieval: "Retrieval",
  verifier: "Verifier",
  planner: "Planner",
  curator: "Curator",
  supervisor: "Supervisor",
};

export const ROLE_JOB: Record<string, string> = {
  intake: "Pins the policy version and reads the denial.",
  retrieval: "Finds candidate precedents in memory.",
  verifier: "Rules on each precedent, in Cypher.",
  planner: "Writes the cited plan.",
  curator: "Turns verified outcomes into memory.",
};

export function fmtDate(yyyymmdd?: number | null): string {
  if (!yyyymmdd) return "—";
  const y = Math.floor(yyyymmdd / 10000);
  const m = Math.floor((yyyymmdd / 100) % 100);
  const d = yyyymmdd % 100;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function ago(ms?: number | null, now = Date.now()): string {
  if (!ms) return "—";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function pct(v?: number | null): string {
  return v == null ? "n/a" : `${Math.round(v * 100)}%`;
}

export function humanEvent(type: string): string {
  const map: Record<string, string> = {
    SUBMITTED: "Filed",
    CLAIMED: "Picked up",
    RESUMED: "Resumed after a failure",
    LEASE_EXPIRED: "Lease expired",
    FENCED_WRITE_REJECTED: "Late write refused",
    INTAKE_DONE: "Denial classified",
    RETRIEVAL_DONE: "Precedents retrieved",
    VERIFIER_DONE: "Precedents ruled on",
    PLANNER_DONE: "Plan written",
    CURATOR_DONE: "Memory updated",
    APPROVED: "Approved",
    OUTCOME_RECORDED: "Outcome recorded",
    NEEDS_HUMAN: "Sent to a person",
    GAVE_UP: "Gave up after retries",
    HUMAN_CORRECTION: "A person classified the notice",
    EVIDENCE_DECLARED: "Document declared on file",
    EVIDENCE_WITHDRAWN: "Document withdrawn",
  };
  return map[type] ?? type;
}
