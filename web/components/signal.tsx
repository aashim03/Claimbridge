import type { Signal as SignalKind } from "@/lib/vocab";

// Citator signals, drawn: a stop sign for negative treatment, a caution triangle,
// a diamond for positive treatment, a ring for neutral. Shape carries meaning on
// its own, so the signal never depends on colour.

const FILL: Record<SignalKind, string> = {
  negative: "var(--neg)",
  caution: "var(--caution)",
  positive: "var(--pos)",
  neutral: "var(--neutral)",
};

export function SignalMark({
  kind,
  size = 14,
  className = "",
  title,
}: {
  kind: SignalKind;
  size?: number;
  className?: string;
  title?: string;
}) {
  const f = FILL[kind];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      className={`inline-block shrink-0 ${className}`}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {kind === "negative" && (
        <>
          <path d="M5.2 1h5.6L15 5.2v5.6L10.8 15H5.2L1 10.8V5.2z" fill={f} />
          <path d="M4.6 7h6.8v2H4.6z" fill="#fff" />
        </>
      )}
      {kind === "caution" && (
        <>
          <path d="M8 1.2 15.2 14H.8z" fill={f} />
          <path d="M7.1 5.4h1.8l-.3 4.6H7.4zM7.1 11.2h1.8V13H7.1z" fill="#fff" />
        </>
      )}
      {kind === "positive" && (
        <>
          <path d="M8 .9 15.1 8 8 15.1.9 8z" fill={f} />
          <path d="M7.1 4.6h1.8v2.5h2.5v1.8H8.9v2.5H7.1V8.9H4.6V7.1h2.5z" fill="#fff" />
        </>
      )}
      {kind === "neutral" && (
        <>
          <circle cx="8" cy="8" r="6.2" fill="none" stroke={f} strokeWidth="2.2" />
          <circle cx="8" cy="8" r="1.6" fill={f} />
        </>
      )}
    </svg>
  );
}

const TEXT: Record<SignalKind, string> = {
  negative: "text-neg",
  caution: "text-caution-ink",
  positive: "text-pos",
  neutral: "text-ink-3",
};

export function Treatment({
  kind,
  label,
  size = 14,
  className = "",
}: {
  kind: SignalKind;
  label: string;
  size?: number;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 font-medium ${TEXT[kind]} ${className}`}>
      <SignalMark kind={kind} size={size} />
      {label}
    </span>
  );
}

export function Wordmark({ className = "", invert = false }: { className?: string; invert?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} data-invert={invert || undefined}>
      <span
        aria-hidden
        className="grid size-[22px] place-items-center rounded-[6px]"
        style={{ background: "linear-gradient(135deg, var(--link), #c4b5fd)" }}
      >
        <svg width="14" height="14" viewBox="0 0 18 18">
          <path d="M2 13.5h14M4 13.5V9M14 13.5V9" stroke="var(--accent-ink)" strokeWidth="1.8" />
          <path d="M4 9c1.8-4 8.2-4 10 0" fill="none" stroke="var(--accent-ink)" strokeWidth="1.8" />
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink">ClaimBridge</span>
    </span>
  );
}
