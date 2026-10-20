"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "accent" | "secondary" | "danger" | "ghost";

const VARIANT: Record<Variant, string> = {
  primary: "bg-ink text-paper hover:bg-white disabled:bg-ink-3",
  accent: "bg-link text-accent-ink hover:brightness-110 disabled:opacity-50",
  secondary: "bg-wash text-ink border border-rule-2 hover:border-ink-3 hover:bg-wash-2 disabled:text-ink-3",
  danger: "bg-wash text-neg border border-[#5a2c2e] hover:bg-neg-wash hover:border-neg disabled:text-ink-3",
  ghost: "text-ink-2 hover:text-ink hover:bg-wash-2",
};

export function Button({
  variant = "secondary",
  busy = false,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-[8px] px-3 text-[13px] font-medium transition-[background-color,border-color,filter] duration-150 disabled:cursor-not-allowed ${VARIANT[variant]} ${className}`}
    >
      {busy && <span className="size-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  );
}

// Section heads always carry more space above than below; pass `top` only for the first
// head of a column, which sits under the page header.
export function SectionHead({ title, aside, id, top = false }: { title: ReactNode; aside?: ReactNode; id?: string; top?: boolean }) {
  return (
    <div
      className={`mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-1 border-b border-rule pb-2.5 ${top ? "mt-0" : "mt-12"}`}
      id={id}
    >
      <h2 className="text-[17px] font-semibold leading-tight tracking-[-0.02em] text-ink">{title}</h2>
      {aside && <div className="text-[12.5px] text-ink-3">{aside}</div>}
    </div>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-[12px] border border-rule bg-wash ${className}`}>{children}</section>;
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] tracking-[-0.01em] ${className}`}>{children}</span>;
}

export function Cite({
  id,
  active,
  onHover,
  title,
  onClick,
}: {
  id: string;
  active?: boolean;
  onHover?: (id: string | null) => void;
  title?: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      onMouseEnter={() => onHover?.(id)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(id)}
      onBlur={() => onHover?.(null)}
      className={`rounded-[5px] border px-1.5 py-[1px] font-mono text-[11px] leading-[18px] transition-colors ${
        active ? "border-link bg-[#1a2140] text-link" : "border-rule-2 bg-wash-2 text-ink-2 hover:border-ink-3"
      }`}
    >
      {id}
    </button>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-dashed border-rule-2 px-6 py-10 text-center">
      <p className="text-[15px] font-medium text-ink">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-[52ch] text-[13px] text-ink-3">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" className="mt-2 text-[12.5px] text-neg">
      {msg}
    </p>
  );
}
