"use client";

import { useEffect, useState, type ReactNode } from "react";
import useSWR, { SWRConfig } from "swr";
import { SESSION_ENDED, fetcher, post, setSignedInAs } from "@/lib/api";

type Session = { mode: "demo" | "protected"; authenticated: boolean; subject?: string; role?: string; tenant_id?: string };

export function useAccess() {
  const { data } = useSWR<Session>("/api/session", fetcher);
  return { session: data, operator: data?.role === "admin" || data?.role === "demo" };
}

export function SessionGate({ children }: { children: ReactNode }) {
  // If the API is briefly unreachable, keep the page and keep asking who we are: when it returns, a revoked or
  // expired session lands on the sign-in form instead of hanging on an error forever.
  const { data, error, mutate } = useSWR<Session>("/api/session", fetcher, { shouldRetryOnError: true, errorRetryInterval: 3000 });
  const [token, setToken] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setSignedInAs(data?.authenticated ? (data.subject ?? null) : null), [data]);
  // A 401 anywhere (expired or revoked session) re-checks who we are; the gate then shows sign-in.
  useEffect(() => {
    const recheck = () => void mutate();
    window.addEventListener(SESSION_ENDED, recheck);
    return () => window.removeEventListener(SESSION_ENDED, recheck);
  }, [mutate]);
  if (error && !data) return <p role="alert" className="p-8">Access service unavailable. Retrying…</p>;
  if (!data) return <p className="p-8 text-ink-3">Checking access…</p>;
  if (!data.authenticated) return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-6">
      <p className="text-sm text-link">ClaimBridge · protected workspace</p>
      <h1 className="text-3xl font-semibold">Sign in to your cases</h1>
      <p className="text-sm text-ink-2">Use the access token issued by your workspace operator. Your policyholder access is assigned by the server.</p>
      <form className="space-y-4" onSubmit={async (e) => {
        e.preventDefault(); setBusy(true); setProblem("");
        try { await post("/api/session", { token }); setToken(""); await mutate(); }
        catch (err) { setProblem(err instanceof Error ? err.message : "Sign-in failed."); }
        finally { setBusy(false); }
      }}>
        <label className="block text-sm" htmlFor="access-token">Access token</label>
        <input id="access-token" type="password" autoComplete="current-password" required value={token}
          onChange={(e) => setToken(e.target.value)} className="w-full rounded-lg border border-rule bg-wash px-3 py-2" />
        {problem && <p role="alert" className="text-sm text-neg">{problem}</p>}
        <button disabled={busy} className="rounded-lg bg-ink px-4 py-2 text-paper">{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
  return (
    <SWRConfig key={data.subject} value={{ provider: () => new Map(), fallback: { "/api/session": data } }}>
      <div className="border-b border-rule bg-wash px-4 py-2 text-xs text-ink-2">
        {data.mode === "demo" ? "Public synthetic sandbox · all fictional policyholders are visible · never enter personal information"
          : `Protected workspace · ${data.subject}${data.tenant_id ? ` · ${data.tenant_id}` : " · operator"}`}
        {data.mode === "protected" && <button className="ml-4 underline" onClick={async () => {
          await fetch("/api/session", { method: "DELETE", headers: { "X-ClaimBridge-Request": "1" } });
          await mutate();
        }}>Sign out</button>}
      </div>
      {children}
    </SWRConfig>
  );
}
