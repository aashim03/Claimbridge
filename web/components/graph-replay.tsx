"use client";

import { useEffect, useMemo, useRef } from "react";
import type { ClaimDetail, GraphEdge, GraphNode } from "@/lib/api";
import { mountReplay, stepCount, type ReplayHandle } from "@/lib/replay-engine";

// The evidence-graph replay. When the claim is still being processed, new steps arrive with
// each SWR revalidation; the replay restores what was already shown and plays only the new ones.
export function GraphReplay({
  detail,
  graph,
  autoplay = true,
  stepMs = 1500,
}: {
  detail: ClaimDetail;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
  autoplay?: boolean;
  stepMs?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const handle = useRef<ReplayHandle | null>(null);
  const shownSteps = useRef(0);
  const n = useMemo(() => stepCount(detail, graph), [detail, graph]);

  useEffect(() => {
    if (!ref.current) return;
    const prev = handle.current?.state();
    handle.current?.destroy();
    const growing = prev && prev.atEnd && n > shownSteps.current;
    handle.current = mountReplay(ref.current, { detail, graph }, growing
      ? { stepMs, animateFrom: shownSteps.current - 1 }
      : prev ? { stepMs, autoplay: false, startAt: Math.min(prev.idx, n - 1) } : { stepMs, autoplay });
    shownSteps.current = n;
    return undefined;
    // Rebuild only when the number of steps changes (new agent work), not on every revalidation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, detail.claim.claim_id]);

  useEffect(() => () => handle.current?.destroy(), []);
  return <div ref={ref} className="cbg" />;
}
