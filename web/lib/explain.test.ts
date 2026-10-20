// Run with `npm test`. Pure logic only: the wording that tells a reviewer why a decision was made.
import assert from "node:assert/strict";
import { test } from "node:test";
import { conditionFailure, originLine, requirementOrigin, splitSources } from "./explain.ts";

const claim = (is_emergency: boolean, in_network: boolean) => ({ is_emergency, in_network });

test("condition failure names the condition that actually failed", () => {
  assert.match(conditionFailure({ req_emergency: true, req_in_network: null }, claim(false, true)), /only to emergencies.*not one/);
  assert.match(conditionFailure({ req_emergency: false, req_in_network: null }, claim(true, true)), /non-emergency.*was an emergency/);
  assert.match(conditionFailure({ req_emergency: null, req_in_network: true }, claim(false, false)), /in-network.*out of network/);
  assert.match(conditionFailure({ req_emergency: null, req_in_network: false }, claim(false, true)), /out-of-network.*in network/);
});

test("a network failure is not described as an emergency failure", () => {
  const text = conditionFailure({ req_emergency: true, req_in_network: true }, claim(true, false));
  assert.doesNotMatch(text, /emergenc/);
  assert.match(text, /network/);
});

test("emergency is checked first, as the Verifier does", () => {
  assert.match(conditionFailure({ req_emergency: true, req_in_network: true }, claim(false, false)), /emergenc/);
});

test("clause sources are policy; finding sources are learned", () => {
  assert.deepEqual(splitSources(["C-2026-MRI-PREAUTH", "F-L-AMBULANCE-1"]), { policy: ["C-2026-MRI-PREAUTH"], learned: ["F-L-AMBULANCE-1"] });
  assert.equal(requirementOrigin({ sources: ["F-L-AMBULANCE-1"] }), "learned");
  assert.equal(requirementOrigin({ sources: ["C-2026-X"] }), "policy");
  assert.equal(requirementOrigin({ sources: ["C-2026-X", "F-1"] }), "both");
});

test("a learned item is never worded as a policy requirement", () => {
  const line = originLine({ sources: ["F-L-AMBULANCE-1"], satisfied: false }, "4.2");
  assert.match(line, /suggested by precedent F-L-AMBULANCE-1/i);
  assert.match(line, /not a policy requirement/);
  assert.doesNotMatch(line, /required by the governing clause/i);
});

test("a policy item names its section", () => {
  assert.match(originLine({ sources: ["C-2026-X"], satisfied: true }, "4.2"), /required by the governing clause \(§4\.2\)/i);
});

import { SUPPORT_NOTE, supportView } from "./explain.ts";

const win = (support: number, contradicted: string[] = []) => ({ code: "ACCEPTED", support, contradicted_by: contradicted });

test("with nothing to count there is no support score, never a bare 0%", () => {
  assert.deepEqual(supportView({ confidence: 0 }, []), { value: "none yet", detail: "No recorded outcome supports a precedent for this claim." });
  assert.equal(supportView({ confidence: 0, support_state: "NO_PRECEDENT" }, []).value, "none yet");
  assert.equal(supportView({ confidence: 0, support_state: "NO_APPEAL_BASIS" }, []).value, "not applicable");
});

test("a score is shown with the observed counts beside it", () => {
  const v = supportView({ confidence: 0.667, support_state: "RECORDED_OUTCOMES" }, [win(1, ["R-1"])]);
  assert.equal(v.value, "67%");
  assert.equal(v.detail, "1 recorded win, 1 contradicted");
  assert.match(SUPPORT_NOTE, /not an approval probability/);
});
