import { Suspense } from "react";
import { CaseView } from "@/components/case-view";

export default function ClaimPage() {
  return (
    <Suspense>
      <CaseView />
    </Suspense>
  );
}
