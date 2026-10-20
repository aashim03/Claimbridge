"use client";

import { useState } from "react";
import useSWR from "swr";
import { del, post, type ClaimDetail } from "@/lib/api";
import { fmtDate } from "@/lib/vocab";
import { Button, ErrorNote } from "./ui";

type Catalog = { reasons: { code: string; name: string }[]; evidence: { code: string; name: string }[] };

const FIELD =
  "h-9 w-full rounded-[8px] border border-rule bg-paper px-2.5 text-[13px] text-ink hover:border-rule-2 focus:border-link focus:outline-none";

// A claim the agents could not read waits here for a person. The notice is kept exactly as received; the person's
// choice and reason become part of the audit record, and the claim resumes at Retrieval with nothing stale kept.
export function ReclassifyForm({ d, onDone, operator }: { d: ClaimDetail; onDone: () => void; operator: boolean }) {
  const { data: cat } = useSWR<Catalog>(operator ? "/api/catalog" : null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const why = d.human_review?.reason;

  return (
    <div className="space-y-3 text-[13px]">
      <p className="text-neg">The agents stopped on this claim and need a person.</p>
      {why && (
        <p className="rounded-[8px] border border-rule bg-paper px-3 py-2 text-ink-2">
          <span className="text-ink-3">Why: </span>
          {why}
        </p>
      )}
      {!operator ? (
        <p className="text-ink-3">An operator reviews notices the agents could not read, and resumes the claim.</p>
      ) : (
        <form
          className="space-y-2.5"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setErr(null);
            try {
              await post(`/api/claims/${d.claim.claim_id}/correct`, { denial_reason: reason, note });
              setReason("");
              setNote("");
              onDone();
            } catch (x) {
              setErr(x);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink-2">What does the notice actually deny?</span>
            <select required value={reason} onChange={(e) => setReason(e.target.value)} className={FIELD}>
              <option value="">Choose a denial reason…</option>
              {cat?.reasons.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink-2">Why (kept in the audit record)</span>
            <textarea
              required
              minLength={10}
              maxLength={500}
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Section 99.9 is a typo for 4.2; the letter says the scan needed approval."
              className={`${FIELD} h-auto resize-y py-2`}
            />
          </label>
          <Button type="submit" variant="accent" busy={busy} disabled={!reason || note.trim().length < 10} className="w-full">
            Classify and resume
          </Button>
          <p className="text-[11.5px] leading-snug text-ink-3">
            The notice stays exactly as received. The clause is chosen by the graph, not by you. The claim resumes at Retrieval and nothing the
            agents computed earlier is kept.
          </p>
        </form>
      )}
      <ErrorNote error={err} />
    </div>
  );
}

const EDITABLE = ["NEW", "NEEDS_HUMAN", "AWAITING_REVIEW"];

// Declaring a document says it exists. ClaimBridge does not open, read or verify documents.
export function EvidenceManager({ d, operator, onDone }: { d: ClaimDetail; operator: boolean; onDone: () => void }) {
  const { data: cat } = useSWR<Catalog>("/api/catalog");
  const [type, setType] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const editable = EDITABLE.includes(d.claim.status) && !d.claim.lease_owner;
  const onFile = new Set(d.evidence.map((e) => e.code));
  const missing = new Set(d.requirements.filter((r) => !r.satisfied).map((r) => r.code));
  const options = (cat?.evidence ?? []).filter((e) => !onFile.has(e.code));
  options.sort((a, b) => Number(missing.has(b.code)) - Number(missing.has(a.code)) || a.name.localeCompare(b.name));

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setErr(null);
    try {
      await fn();
      onDone();
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <ul>
        {d.evidence.length ? (
          d.evidence.map((e) => (
            <li key={e.code} className="flex items-start justify-between gap-3 border-b border-rule py-2 text-[13px]">
              <div className="min-w-0">
                <span>{e.name}</span>
                <p className="text-[11.5px] leading-snug text-ink-3">
                  {e.declared_by ? `Declared on file by ${e.declared_by}; not verified` : `Submitted with the claim ${fmtDate(e.submitted)}`}
                  {e.reference ? ` · ${e.reference}` : ""}
                </p>
              </div>
              {operator && editable && e.doc_id && (
                <button
                  className="shrink-0 rounded-[5px] px-1.5 py-0.5 text-[12px] text-neg hover:bg-neg-wash disabled:opacity-50"
                  disabled={!!busy}
                  onClick={() => run(`w-${e.doc_id}`, () => del(`/api/claims/${d.claim.claim_id}/evidence/${e.doc_id}`))}
                >
                  {busy === `w-${e.doc_id}` ? "Withdrawing…" : "Withdraw"}
                </button>
              )}
            </li>
          ))
        ) : (
          <li className="py-2 text-[13px] text-ink-3">No documents on file.</li>
        )}
      </ul>
      {d.evidence_withdrawn.length > 0 && (
        <p className="mt-2 text-[11.5px] text-ink-3">
          Withdrawn: {d.evidence_withdrawn.map((w) => `${w.name} (by ${w.by})`).join(", ")}. The record is kept; it no longer counts.
        </p>
      )}

      {editable ? (
        <form
          className="mt-3 space-y-2 rounded-[10px] border border-dashed border-rule-2 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void run("declare", () => post(`/api/claims/${d.claim.claim_id}/evidence`, { type, reference: reference || null }).then(() => (setType(""), setReference(""))));
          }}
        >
          <p className="text-[12px] font-medium text-ink-2">Declare a document is on file</p>
          <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <select required value={type} onChange={(e) => setType(e.target.value)} aria-label="Document type" className={FIELD}>
              <option value="">Choose a document…</option>
              {options.map((o) => (
                <option key={o.code} value={o.code}>
                  {o.name}
                  {missing.has(o.code) ? " (missing)" : ""}
                </option>
              ))}
            </select>
            <input
              value={reference}
              maxLength={200}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Reference, e.g. letter of 3 March"
              aria-label="Reference"
              className={FIELD}
            />
            <Button type="submit" variant="accent" busy={busy === "declare"} disabled={!type}>
              Declare
            </Button>
          </div>
          <p className="text-[11.5px] leading-snug text-ink-3">
            This says the document exists; ClaimBridge does not open or verify it.
            {d.claim.status === "AWAITING_REVIEW" ? " The plan is withdrawn and the Planner re-checks the checklist." : ""}
          </p>
        </form>
      ) : (
        <p className="mt-3 text-[11.5px] text-ink-3">Evidence is frozen once a claim is approved, and while an agent is working on it.</p>
      )}
      <ErrorNote error={err} />
    </div>
  );
}
