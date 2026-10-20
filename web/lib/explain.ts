// One place for how the product explains a decision, so the checklist, the graph replay and the
// packet cannot drift apart. Facts come from the API; nothing here decides anything.
import type { ClaimDetail, Verdict } from "./api";

type Flags = { is_emergency: boolean; in_network: boolean };

// A requirement's sources are clause IDs (policy) or finding IDs (learned from resolved cases).
export const isLearnedSource = (id: string) => id.startsWith("F-");

export function splitSources(sources: string[] = []) {
  return { policy: sources.filter((s) => !isLearnedSource(s)), learned: sources.filter(isLearnedSource) };
}

export type Requirement = ClaimDetail["requirements"][number];

export function requirementOrigin(r: Pick<Requirement, "sources">): "policy" | "learned" | "both" {
  const { policy, learned } = splitSources(r.sources);
  return policy.length && learned.length ? "both" : learned.length ? "learned" : "policy";
}

// The condition that actually failed, in the same order the Verifier checks them.
export function conditionFailure(v: Pick<Verdict, "req_emergency" | "req_in_network">, c: Flags): string {
  if (v.req_emergency != null && v.req_emergency !== c.is_emergency)
    return v.req_emergency ? "it applied only to emergencies, and this claim was not one" : "it applied only to non-emergency care, and this claim was an emergency";
  if (v.req_in_network != null && v.req_in_network !== c.in_network)
    return v.req_in_network ? "it applied only to in-network care, and this claim was out of network" : "it applied only to out-of-network care, and this claim was in network";
  return "a condition it depends on is not met";
}

export const upperFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const SUPPORT_NOTE = "Support score is a smoothed count of recorded outcomes, not an approval probability.";

// What to show for a plan's "support score". Never a bare 0%: with nothing to count there is no score.
export function supportView(
  rec: { confidence: number; support_state?: string },
  verdicts: Pick<Verdict, "code" | "support" | "contradicted_by">[],
): { value: string; detail: string } {
  const accepted = verdicts.filter((v) => v.code === "ACCEPTED");
  const state = rec.support_state ?? (accepted.length ? "RECORDED_OUTCOMES" : "NO_PRECEDENT");
  if (state === "NO_PRECEDENT") return { value: "none yet", detail: "No recorded outcome supports a precedent for this claim." };
  if (state === "NO_APPEAL_BASIS") return { value: "not applicable", detail: "A policy gate leaves no basis for appeal, so there is no outcome to support." };
  const top = [...accepted].sort((a, b) => b.support - a.support)[0];
  const counts = top ? `${top.support} recorded win${top.support === 1 ? "" : "s"}, ${top.contradicted_by.length} contradicted` : "";
  return { value: `${Math.round(rec.confidence * 100)}%`, detail: counts };
}

export const LEARNED_CAVEAT = "an observed association from resolved cases, not a policy requirement";

// Plain-language origin of one checklist line.
export function originLine(r: Pick<Requirement, "sources" | "satisfied">, clauseSection?: string): string {
  const { policy, learned } = splitSources(r.sources);
  const parts: string[] = [];
  if (policy.length) parts.push(`required by the governing clause${clauseSection ? ` (§${clauseSection})` : ""}`);
  if (learned.length) parts.push(`suggested by precedent ${learned.join(", ")}: ${LEARNED_CAVEAT}`);
  return upperFirst(parts.join("; and also ")) + ".";
}
