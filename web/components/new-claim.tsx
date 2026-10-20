"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { Sparkles, X } from "lucide-react";
import { post } from "@/lib/api";
import { Button, ErrorNote } from "./ui";

type Opt = { code: string; name: string };
type Catalog = { tenants: Opt[]; services: Opt[]; reasons: Opt[]; evidence: Opt[] };

const FIELD =
  "h-9 w-full rounded-[8px] border border-rule bg-paper px-2.5 text-[13px] text-ink hover:border-rule-2 focus:border-link focus:outline-none";

function Field({ label, hint, htmlFor, children }: { label: string; hint?: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-[12px] font-medium text-ink-2">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-[11.5px] text-ink-3">{hint}</p>}
    </div>
  );
}

function Toggle({ label, on, set }: { label: string; on: boolean; set: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => set(!on)}
      className="flex h-9 items-center justify-between gap-3 rounded-[8px] border border-rule bg-paper px-2.5 text-[13px] text-ink hover:border-rule-2"
    >
      {label}
      <span className={`relative h-[18px] w-[32px] rounded-full transition-colors ${on ? "bg-link" : "bg-rule-2"}`} aria-hidden>
        <span className={`absolute top-[2px] size-[14px] rounded-full bg-paper transition-[left] ${on ? "left-[16px]" : "left-[2px]"}`} />
      </span>
    </button>
  );
}

// Enter a denied claim by hand. It lands in the graph exactly like a seeded claim and,
// when filed, the agents pick it up; the case page replays their work live.
export function NewClaim({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { data: cat } = useSWR<Catalog>("/api/catalog");
  const [tenant, setTenant] = useState("TEN-03");
  const [service, setService] = useState("MRI");
  const [serviceDate, setServiceDate] = useState("2026-03-02");
  const [filedDate, setFiledDate] = useState("2026-03-20");
  const [emergency, setEmergency] = useState(false);
  const [network, setNetwork] = useState(true);
  const [enrolled, setEnrolled] = useState(12);
  const [evidence, setEvidence] = useState<string[]>(["ITEMIZED_BILL"]);
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("PREAUTH_MISSING");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const first = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function sample() {
    setBusy("sample");
    setErr(null);
    try {
      const r = await post<{ text: string }>("/api/claims/sample-notice", { service, reason, service_date: serviceDate });
      setNotice(r.text);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  async function submit(fileNow: boolean) {
    setBusy(fileNow ? "file" : "save");
    setErr(null);
    try {
      const r = await post<{ claim_id: string }>("/api/claims/new", {
        tenant_id: tenant,
        service,
        service_date: serviceDate,
        filed_date: filedDate,
        notice,
        evidence,
        in_network: network,
        is_emergency: emergency,
        enrolled_months: enrolled,
        file_now: fileNow,
      });
      router.push(`/console/claims/${r.claim_id}`);
    } catch (e) {
      setErr(e);
      setBusy(null);
    }
  }

  const lag = Math.round((Date.parse(filedDate) - Date.parse(serviceDate)) / 86400000);

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-labelledby="nc-title">
      <button className="absolute inset-0 bg-black/60" aria-label="Close" onClick={onClose} />
      <form
        onSubmit={(e) => (e.preventDefault(), submit(true))}
        className="absolute inset-y-0 right-0 flex w-full max-w-[520px] flex-col border-l border-rule bg-wash shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-4">
          <div>
            <h2 id="nc-title" className="text-[16px] font-semibold tracking-[-0.02em]">
              New denied claim
            </h2>
            <p className="mt-0.5 text-[12.5px] text-ink-3">The agents work it like any other claim. Fictional data only.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-[6px] p-1 text-ink-3 hover:bg-wash-2 hover:text-ink">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Policyholder" htmlFor="nc-tenant">
              <select id="nc-tenant" ref={first} value={tenant} onChange={(e) => setTenant(e.target.value)} className={FIELD}>
                {cat?.tenants.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Service" htmlFor="nc-service">
              <select id="nc-service" value={service} onChange={(e) => setService(e.target.value)} className={FIELD}>
                {cat?.services.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Service date" htmlFor="nc-sd" hint="Decides which policy version governs.">
              <input id="nc-sd" type="date" required value={serviceDate} min="2024-01-01" onChange={(e) => setServiceDate(e.target.value)} className={FIELD} />
            </Field>
            <Field label="Claim filed" htmlFor="nc-fd" hint={Number.isFinite(lag) ? (lag < 0 ? "Before the service date." : `${lag} days after the service.`) : undefined}>
              <input id="nc-fd" type="date" required value={filedDate} min={serviceDate} onChange={(e) => setFiledDate(e.target.value)} className={FIELD} />
            </Field>
            <Toggle label="Emergency" on={emergency} set={setEmergency} />
            <Toggle label="In network" on={network} set={setNetwork} />
            <Field label="Months enrolled" htmlFor="nc-en">
              <input
                id="nc-en"
                type="number"
                min={0}
                max={600}
                value={enrolled}
                onChange={(e) => setEnrolled(Number(e.target.value))}
                className={`${FIELD} tabular`}
              />
            </Field>
          </div>

          <fieldset>
            <legend className="mb-1.5 text-[12px] font-medium text-ink-2">Documents on file</legend>
            <div className="grid gap-1 sm:grid-cols-2">
              {cat?.evidence.map((e) => {
                const on = evidence.includes(e.code);
                return (
                  <label
                    key={e.code}
                    className={`flex cursor-pointer items-center gap-2 rounded-[7px] px-2 py-1.5 text-[12.5px] transition-colors ${
                      on ? "bg-wash-2 text-ink" : "text-ink-2 hover:bg-wash-2"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => setEvidence(on ? evidence.filter((x) => x !== e.code) : [...evidence, e.code])}
                      className="size-3.5 accent-[var(--link)]"
                    />
                    {e.name}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <Field label="Denial notice" htmlFor="nc-notice" hint="Paste or write the insurer's letter. Intake reads it to decide the denial reason and clause.">
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded-[8px] border border-dashed border-rule-2 p-2">
              <span className="text-[12px] text-ink-3">Or start from a sample for</span>
              <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Denial reason for the sample" className={`${FIELD} h-8 w-auto flex-1`}>
                {cat?.reasons.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name}
                  </option>
                ))}
              </select>
              <Button type="button" busy={busy === "sample"} onClick={sample} className="h-8">
                <Sparkles size={13} aria-hidden /> Insert
              </Button>
            </div>
            <textarea
              id="nc-notice"
              required
              minLength={40}
              maxLength={4000}
              rows={7}
              value={notice}
              onChange={(e) => setNotice(e.target.value)}
              placeholder="Notice of claim denial. Service: … Date of service: … This service required …"
              className={`${FIELD} h-auto resize-y py-2 leading-relaxed`}
            />
          </Field>
          <ErrorNote error={err} />
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-rule px-5 py-4">
          <p className="text-[11.5px] leading-snug text-ink-3">Do not enter real health information.</p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" busy={busy === "save"} disabled={!!busy || notice.trim().length < 40} onClick={() => submit(false)}>
              Save only
            </Button>
            <Button type="submit" variant="accent" busy={busy === "file"} disabled={!!busy || notice.trim().length < 40}>
              File and watch
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
