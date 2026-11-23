import { beforeEach, describe, expect, it } from "vitest";
import { findNavItem } from "@/lib/nav";
import { AGENT_STEP_MS, COPILOT_QUEUE_MS } from "./copilot";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import {
  addConditionMock,
  decideConditionMock,
  getLatestLmMock,
  getLatestUnderwritingMock,
  overrideConditionMock,
  rerunCopilotAgentMock,
  resetMockStore,
  runCopilotMock,
  signOffMock,
} from "./store";

beforeEach(() => resetMockStore());

const T0 = 5_000_000;
const DONE = T0 + COPILOT_QUEUE_MS + 3 * AGENT_STEP_MS + 1;

describe("the agent screens in the mock store", () => {
  it("has nothing before the first run (404), for either screen", () => {
    expect(() => getLatestUnderwritingMock(DANIEL_CASE_ID)).toThrowError(expect.objectContaining({ status: 404 }));
    expect(() => getLatestLmMock(ANGELA_CASE_ID)).toThrowError(expect.objectContaining({ status: 404 }));
    expect(() => decideConditionMock(DANIEL_CASE_ID, "uwc-1", { decision: "accepted" })).toThrowError(expect.objectContaining({ status: 404 }));
    expect(() => signOffMock("lm", ANGELA_CASE_ID)).toThrowError(expect.objectContaining({ status: 404 }));
  });

  it("only the first run of a case has the failed Critic: a second run succeeds throughout", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, T0);
    expect(getLatestUnderwritingMock(DANIEL_CASE_ID, DONE).agent_runs.map((a) => a.status)).toEqual(["done", "done", "failed"]);
    runCopilotMock("underwriting", DANIEL_CASE_ID, T0);
    expect(getLatestUnderwritingMock(DANIEL_CASE_ID, DONE).agent_runs.map((a) => a.status)).toEqual(["done", "done", "done"]);
  });

  it("keeps the two screens' runs apart", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, T0);
    expect(() => getLatestLmMock(ANGELA_CASE_ID)).toThrowError(expect.objectContaining({ status: 404 }));
    runCopilotMock("lm", ANGELA_CASE_ID, T0);
    expect(getLatestLmMock(ANGELA_CASE_ID, DONE).run_status).toBe("succeeded");
  });

  it("a new run replaces the earlier one, and what a reviewer did to it", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, T0);
    decideConditionMock(DANIEL_CASE_ID, "uwc-1", { decision: "accepted" }, DONE);
    runCopilotMock("underwriting", DANIEL_CASE_ID, DONE + 10);
    const view = getLatestUnderwritingMock(DANIEL_CASE_ID, DONE + 10 + COPILOT_QUEUE_MS + 3 * AGENT_STEP_MS + 1);
    expect(view.conditions.every((c) => c.decision === "pending")).toBe(true);
    expect(view.sign_offs).toEqual([]);
  });

  it("is back to nothing after a reset", () => {
    runCopilotMock("lm", ANGELA_CASE_ID, T0);
    resetMockStore();
    expect(() => getLatestLmMock(ANGELA_CASE_ID)).toThrowError(expect.objectContaining({ status: 404 }));
    runCopilotMock("lm", ANGELA_CASE_ID, T0); // and the first run fails the Critic again
    expect(getLatestLmMock(ANGELA_CASE_ID, DONE).agent_runs[2].status).toBe("failed");
  });

  it("returns the report as it now stands after a decision, an added condition, an override and a sign-off", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, T0);
    const decided = decideConditionMock(DANIEL_CASE_ID, "uwc-2", { decision: "rejected", reason: "not required" }, DONE);
    expect(decided.conditions[1].decision).toBe("rejected");
    const added = addConditionMock(DANIEL_CASE_ID, { text: "Gift letter", priority: "significant" }, DONE);
    expect(added.conditions).toHaveLength(7);
    expect(signOffMock("underwriting", DANIEL_CASE_ID, "ok", DONE).pending_conditions).toBe(5);

    runCopilotMock("lm", ANGELA_CASE_ID, T0);
    const overridden = overrideConditionMock(ANGELA_CASE_ID, "loan_modification.intent", { status: "not_met", reason: "Unconfirmed" }, DONE);
    expect(overridden.waterfall.find((o) => o.option === "loan_modification")).toMatchObject({ status: "not_met", original_status: "met" });
  });

  it("re-runs one agent through the store", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, T0);
    rerunCopilotAgentMock("underwriting", DANIEL_CASE_ID, "critic", DONE);
    expect(getLatestUnderwritingMock(DANIEL_CASE_ID, DONE + 1).agent_runs[2]).toMatchObject({ status: "running", attempt: 2 });
  });
});

describe("the menu", () => {
  it("has the Underwriting copilot live for Loan Processing and the Recommendation live for Loss Mitigation", () => {
    expect(findNavItem("underwriting", "underwriting-copilot")?.status).toBe("live");
    expect(findNavItem("loss_mitigation", "recommendation")?.status).toBe("live");
    expect(findNavItem("loss_mitigation", "underwriting-copilot")).toBeUndefined();
    expect(findNavItem("underwriting", "recommendation")).toBeUndefined();
  });
});
