"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import useSWR, { SWRConfig, useSWRConfig } from "swr";
import { Bot, Brain, ChartColumnBig, Inbox, Menu, Search, X } from "lucide-react";
import { SESSION_ENDED, fetcher, type Overview } from "@/lib/api";
import { Wordmark } from "./signal";

import { SessionGate, useAccess } from "./session-gate";

type Live = { connected: boolean; lastTick: number | null };
const LiveContext = createContext<Live>({ connected: false, lastTick: null });
export const useLive = () => useContext(LiveContext);

function LiveBridge({ children }: { children: ReactNode }) {
  const { mutate } = useSWRConfig();
  const [live, setLive] = useState<Live>({ connected: false, lastTick: null });
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const open = () => {
      es = new EventSource("/api/stream");
      es.onopen = () => setLive((l) => ({ ...l, connected: true }));
      es.addEventListener("tick", () => {
        setLive({ connected: true, lastTick: Date.now() });
        if (pending.current) return;
        pending.current = setTimeout(() => {
          pending.current = null;
          mutate((key) => typeof key === "string" && key.startsWith("/api/") && key !== "/api/eval");
        }, 250);
      });
      // The server ends the stream when the credential is revoked or the session expires.
      es.addEventListener("auth", () => {
        es?.close();
        setLive({ connected: false, lastTick: null });
        window.dispatchEvent(new Event(SESSION_ENDED));
      });
      es.onerror = () => {
        setLive((l) => ({ ...l, connected: false }));
        es?.close();
        window.dispatchEvent(new Event(SESSION_ENDED));   // a refused reconnect usually means 401
        retry = setTimeout(open, 3000);
      };
    };
    open();
    return () => {
      es?.close();
      if (retry) clearTimeout(retry);
      // A refresh scheduled for the previous identity must not run against its torn-down cache.
      if (pending.current) {
        clearTimeout(pending.current);
        pending.current = null;
      }
    };
  }, [mutate]);

  return <LiveContext.Provider value={live}>{children}</LiveContext.Provider>;
}

const NAV = [
  { href: "/console", label: "Docket", icon: Inbox, exact: true, key: "1" },
  { href: "/console/memory", label: "Memory", icon: Brain, key: "2" },
  { href: "/console/agents", label: "Agents", icon: Bot, key: "3" },
  { href: "/console/evaluation", label: "Evaluation", icon: ChartColumnBig, key: "4" },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const { operator } = useAccess();
  const { data } = useSWR<Overview>("/api/overview", fetcher, { refreshInterval: 5000 });
  const live = useLive();
  const counts = data?.statuses ?? {};
  const review = counts["AWAITING_REVIEW"] ?? 0;
  const stale = (data?.findings?.["STALE"] ?? 0) + (data?.findings?.["CONTRADICTED"] ?? 0);

  return (
    <nav aria-label="Console" className="flex h-full flex-col border-r border-rule bg-paper">
      <div className="flex h-14 items-center px-4">
        <Link href="/" className="rounded-[6px]" onClick={onNavigate}>
          <Wordmark />
        </Link>
      </div>
      <p className="px-4 pb-2 pt-3 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Workspace</p>
      <ul className="flex flex-col gap-0.5 px-2">
        {NAV.filter(n => operator || n.label !== "Agents").map(({ href, label, icon: Icon, exact, key }) => {
          const active = exact ? path === href || path.startsWith("/console/claims") : path.startsWith(href);
          const badge = label === "Docket" ? review : label === "Memory" ? stale : label === "Agents" ? data?.workers_alive : null;
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={`group flex h-8 items-center gap-2.5 rounded-[7px] px-2.5 text-[13px] transition-colors ${
                  active ? "bg-wash-2 font-medium text-ink" : "text-ink-2 hover:bg-wash hover:text-ink"
                }`}
              >
                <Icon size={15} strokeWidth={1.75} aria-hidden className={active ? "text-ink" : "text-ink-3"} />
                <span>{label}</span>
                {badge ? (
                  <span
                    className="ml-auto rounded-[5px] bg-wash-2 px-1.5 font-mono text-[10.5px] leading-[18px] text-ink-2 tabular"
                    title={
                      label === "Docket"
                        ? "Claims awaiting review"
                        : label === "Memory"
                          ? "Precedents limited or contradicted"
                          : "Workers alive"
                    }
                  >
                    {badge}
                  </span>
                ) : (
                  <kbd className="ml-auto hidden font-mono text-[10.5px] text-ink-3 group-hover:inline">g {key}</kbd>
                )}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto space-y-3 border-t border-rule px-4 py-4 text-[11.5px] leading-relaxed text-ink-3">
        <div className="flex items-center gap-2">
          <span className={`size-1.5 rounded-full ${live.connected ? "live-dot bg-pos" : "bg-ink-3"}`} aria-hidden />
          <span className={live.connected ? "text-ink-2" : ""}>{live.connected ? "Live from the graph" : "Reconnecting…"}</span>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          <dt>Policy world</dt>
          <dd className="text-ink-2">{data?.world ? data.world.replace("V", "") : "—"}</dd>
          <dt>Supervisor</dt>
          <dd className="text-ink-2">{data ? (data.supervisor_alive ? "running" : "stopped") : "—"}</dd>
          <dt>LLM</dt>
          <dd className="truncate text-ink-2" title={data ? `${data.llm.platform}/${data.llm.model}` : ""}>
            {data ? `${data.llm.model.split("/").pop()} · ${data.llm.mode === "cached" ? "replay" : data.llm.mode}` : "—"}
          </dd>
        </dl>
      </div>
    </nav>
  );
}

// Top bar: jump to any claim by ID, plus g+1..4 navigation.
function CommandBar({ onMenu, menuOpen }: { onMenu: () => void; menuOpen: boolean }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let g = false;
    let t: ReturnType<typeof setTimeout> | null = null;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        input.current?.focus();
        return;
      }
      if (e.key === "g") {
        g = true;
        if (t) clearTimeout(t);
        t = setTimeout(() => (g = false), 900);
        return;
      }
      const hit = g && NAV.find((n) => n.key === e.key);
      if (hit) {
        g = false;
        router.push(hit.href);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (t) clearTimeout(t);
    };
  }, [router]);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-rule bg-paper/90 px-4 backdrop-blur sm:px-6">
      <button
        className="-ml-1 rounded-[7px] p-1.5 text-ink-2 hover:bg-wash hover:text-ink lg:hidden"
        aria-label={menuOpen ? "Close navigation" : "Open navigation"}
        onClick={onMenu}
      >
        {menuOpen ? <X size={18} /> : <Menu size={18} />}
      </button>
      <form
        role="search"
        className="relative w-full max-w-[420px]"
        onSubmit={(e) => {
          e.preventDefault();
          const id = q.trim().toUpperCase();
          if (id) {
            router.push(`/console/claims/${encodeURIComponent(id)}`);
            setQ("");
            input.current?.blur();
          }
        }}
      >
        <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
        <label htmlFor="cmd" className="sr-only">
          Open a claim by ID
        </label>
        <input
          id="cmd"
          ref={input}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Open a claim by ID, e.g. EV-T1-01"
          autoComplete="off"
          spellCheck={false}
          className="h-8 w-full rounded-[8px] border border-rule bg-wash pl-8 pr-10 font-mono text-[12.5px] text-ink placeholder:font-sans placeholder:text-ink-3 focus:border-rule-2 focus:outline-none"
        />
        <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded-[4px] border border-rule-2 px-1.5 font-mono text-[10.5px] text-ink-3">
          /
        </kbd>
      </form>
      <p className="ml-auto hidden text-[11.5px] text-ink-3 xl:block">Synthetic data · every recommendation needs a caseworker&apos;s approval</p>
    </header>
  );
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <SWRConfig value={{ fetcher, revalidateOnFocus: false, keepPreviousData: true }}>
      <SessionGate><LiveBridge>
        <div className="flex min-h-dvh">
          <aside className="sticky top-0 hidden h-dvh w-[220px] shrink-0 lg:block">
            <Suspense fallback={<div className="h-full border-r border-rule" />}>
              <Sidebar />
            </Suspense>
          </aside>
          {open && (
            <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
              <button className="absolute inset-0 bg-black/60" aria-label="Close navigation" onClick={() => setOpen(false)} />
              <div className="absolute inset-y-0 left-0 w-[250px]">
                <Suspense fallback={<div className="h-full bg-paper" />}>
                  <Sidebar onNavigate={() => setOpen(false)} />
                </Suspense>
              </div>
            </div>
          )}
          <div className="flex min-w-0 flex-1 flex-col">
            <Suspense fallback={<div className="h-14 border-b border-rule" />}>
              <CommandBar onMenu={() => setOpen(!open)} menuOpen={open} />
            </Suspense>
            <div className="border-b border-rule px-4 py-1.5 text-[11.5px] text-ink-3 sm:px-6 xl:hidden">
              Synthetic, fictional data. Every recommendation needs a caseworker&apos;s approval; ClaimBridge does not approve
              claims or give legal advice.
            </div>
            <main className="min-w-0 flex-1 px-4 pb-16 pt-6 sm:px-6 lg:px-8 lg:pt-8">{children}</main>
          </div>
        </div>
      </LiveBridge></SessionGate>
    </SWRConfig>
  );
}
