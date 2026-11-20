import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-error";
import type { IncomeAnalysis } from "@/lib/income-types";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import {
  applyIncomeDecision,
  buildDanielIncome,
  candidateFrom,
  documentRequestsFrom,
  formatCents,
  fromCents,
  POSSIBLE_LABEL,
  toCents,
} from "./income";
import {
  getJobMock,
  getLatestIncomeMock,
  JOB_QUEUE_MS,
  JOB_RUN_MS,
  resetMockStore,
  runIncomeMock,
  setIncomeComponentMock,
} from "./store";

beforeEach(() => resetMockStore());

const analysis = (): IncomeAnalysis => buildDanielIncome("2026-11-20T09:00:00.000Z");
const part = (a: IncomeAnalysis, id: string) => a.components.find((c) => c.id === id)!;

describe("money in whole cents", () => {
  it("converts between text and cents without floats", () => {
    expect(toCents("5980.00")).toBe(598000);
    expect(toCents("444.41")).toBe(44441);
    expect(toCents("0.5")).toBe(50);
    expect(fromCents(598000)).toBe("5980.00");
    expect(fromCents(5)).toBe("0.05");
  });

  it("writes working the way the backend does, with thousands separators", () => {
    expect(formatCents(598000)).toBe("5,980.00");
    expect(formatCents(642441)).toBe("6,424.41");
    expect(formatCents(44441)).toBe("444.41");
    expect(formatCents(100000000)).toBe("1,000,000.00");
  });
});

describe("Daniel's mock income analysis", () => {
  it("shows the three components with the figures from the scenario", () => {
    const a = analysis();
    expect(a.components.map((c) => c.id)).toEqual(["base_pay", "overtime", "bonus"]);
    expect(part(a, "base_pay").monthly.value).toBe("5980.00");
    expect(part(a, "overtime").monthly.value).toBe("444.41");
    expect(part(a, "bonus").monthly.value).toBe("228.34");
    expect(part(a, "base_pay").year_to_date?.value).toBe("52440.00");
    expect(part(a, "base_pay").current_period?.value).toBe("2760.00");
  });

  it("counts only base pay, so the candidate monthly income is 5,980.00", () => {
    const a = analysis();
    expect(a.candidate_monthly.value).toBe("5980.00");
    expect(a.candidate_monthly.working[0]).toMatchObject({ formula: "5,980.00", result: "5,980.00" });
    expect(a.candidate_monthly.working[0].note).toBe("Left out: Overtime (1.5x) (444.41), Bonus (228.34)");
  });

  it("leaves overtime and bonus out with the reason", () => {
    const a = analysis();
    for (const id of ["overtime", "bonus"]) {
      expect(part(a, id).included).toBe(false);
      expect(part(a, id).rule_note).toContain("24 months");
      expect(part(a, id).override).toBeNull();
    }
    expect(part(a, "base_pay").included).toBe(true);
  });

  it("gives every figure its working and evidence", () => {
    const a = analysis();
    for (const c of a.components) {
      for (const f of [c.current_period, c.year_to_date, c.monthly]) {
        expect(f).not.toBeNull();
        expect(f!.working.length).toBeGreaterThan(0);
        expect(f!.evidence.length).toBeGreaterThan(0);
        expect(f!.evidence.every((e) => e.document_id && e.line_ids?.length)).toBe(true);
      }
    }
    expect(part(a, "base_pay").monthly.working[0].formula).toBe("34.50 × 80.00 hours × 26 periods ÷ 12");
    expect(part(a, "overtime").monthly.working[0].formula).toBe("3,897.10 × 26 ÷ (19 × 12)");
    expect(a.candidate_monthly.evidence.length).toBeGreaterThan(0);
  });

  it("keeps every figure as text, never a number", () => {
    const json = JSON.stringify(analysis());
    expect(json).not.toMatch(/"value":\s*\d/);
  });

  it("flags the short overtime history with both sides and a possible explanation", () => {
    const a = analysis();
    expect(a.flags).toHaveLength(1);
    const flag = a.flags[0];
    expect(flag.values).toHaveLength(2);
    expect(flag.values.every((v) => v.label && v.value && v.source.label)).toBe(true);
    expect(flag.explanations[0].label).toBe(POSSIBLE_LABEL);
    expect(flag.explanations[0].figures_verified).toBe(true);
  });

  it("collects the suggested documents once each, ready to copy", () => {
    const a = analysis();
    expect(a.document_requests).toEqual([
      "Final pay stub of 2025 showing year-to-date overtime and bonus",
      "Employer letter stating how long overtime and bonus have been paid",
    ]);
    const twice = [a.flags[0], a.flags[0]];
    expect(documentRequestsFrom(twice)).toHaveLength(2);
  });

  it("lists the four cross-checks, all passing, and the template trend sentences", () => {
    const a = analysis();
    expect(a.checks.map((c) => c.id)).toEqual(["wages", "employer", "deferrals", "trend"]);
    expect(a.checks.every((c) => c.status === "passed")).toBe(true);
    expect(a.trend[0]).toBe("Gross pay rose 5.49% in 2025 (W-2 Box 5: 70,431.80 to 74,298.60).");
    expect(a.method_label).toBe("illustrative");
  });

  it("never uses the decision words", () => {
    expect(JSON.stringify(analysis())).not.toMatch(/approv|deny|denied|offer|eligib|qualifies/i);
  });
});

describe("the candidate total", () => {
  it("adds overtime in cents when it is counted: 5,980.00 + 444.41 = 6,424.41", () => {
    const a = analysis();
    part(a, "overtime").included = true;
    const total = candidateFrom(a.components);
    expect(total.value).toBe("6424.41");
    expect(total.working[0].formula).toBe("5,980.00 + 444.41");
    expect(total.working[0].result).toBe("6,424.41");
    expect(total.working[0].note).toBe("Left out: Bonus (228.34)");
  });

  it("counting everything adds up with no float drift", () => {
    const a = analysis();
    for (const c of a.components) c.included = true;
    expect(candidateFrom(a.components).value).toBe("6652.75");
    expect(candidateFrom(a.components).working[0].note).toBe("Nothing is left out");
  });

  it("counting nothing gives 0.00", () => {
    const a = analysis();
    for (const c of a.components) c.included = false;
    expect(candidateFrom(a.components).value).toBe("0.00");
  });
});

describe("including or excluding a component", () => {
  const at = "2026-11-20T10:00:00.000Z";
  const statusOf = (fn: () => unknown): number | undefined => {
    try {
      fn();
    } catch (e) {
      return (e as ApiError).status;
    }
    return undefined;
  };

  it("counting overtime moves the candidate to 6,424.41 and updates its working", () => {
    const a = applyIncomeDecision(analysis(), "overtime", { included: true, reason: "Employer letter received" }, "demo.reviewer", at);
    expect(a.candidate_monthly.value).toBe("6424.41");
    expect(a.candidate_monthly.working[0]).toMatchObject({ formula: "5,980.00 + 444.41", result: "6,424.41" });
    expect(part(a, "overtime").included).toBe(true);
  });

  it("counting everything gives 6,652.75, and leaving base pay out gives 0.00", () => {
    let a = applyIncomeDecision(analysis(), "overtime", { included: true, reason: "r" }, "u", at);
    a = applyIncomeDecision(a, "bonus", { included: true, reason: "r" }, "u", at);
    expect(a.candidate_monthly.value).toBe("6652.75");
    a = applyIncomeDecision(analysis(), "base_pay", { included: false, reason: "r" }, "u", at);
    expect(a.candidate_monthly.value).toBe("0.00");
  });

  it("records who, when and why, and keeps what the method said", () => {
    const a = applyIncomeDecision(analysis(), "overtime", { included: true, reason: "  Employer letter received  " }, "demo.reviewer", at);
    const c = part(a, "overtime");
    expect(c.override).toEqual({ included: true, reason: "Employer letter received", by: "demo.reviewer", at });
    expect(c.rule_included).toBe(false); // the original answer is never overwritten
    expect(c.rule_note).toContain("24 months");
    expect(c.monthly.value).toBe("444.41"); // the figure itself does not change
  });

  it("leaves every other component alone and does not change the analysis it was given", () => {
    const before = analysis();
    const a = applyIncomeDecision(before, "overtime", { included: true, reason: "r" }, "u", at);
    expect(part(a, "bonus").override).toBeNull();
    expect(part(a, "base_pay").override).toBeNull();
    expect(part(before, "overtime").included).toBe(false);
    expect(before.candidate_monthly.value).toBe("5980.00");
  });

  it("refuses a missing, blank or too long reason (422) and an unknown component (404)", () => {
    const go = (id: string, reason: string) => () =>
      applyIncomeDecision(analysis(), id, { included: true, reason }, "u", at);
    expect(statusOf(go("overtime", ""))).toBe(422);
    expect(statusOf(go("overtime", "   "))).toBe(422);
    expect(statusOf(go("overtime", "x".repeat(501)))).toBe(422);
    expect(statusOf(go("overtime", "x".repeat(500)))).toBeUndefined();
    expect(statusOf(go("nope", "reason"))).toBe(404);
  });

  it("the store keeps the decision as the latest result and refuses it before a run", () => {
    expect(statusOf(() => setIncomeComponentMock(DANIEL_CASE_ID, "overtime", { included: true, reason: "r" }))).toBe(404);
    const job = runIncomeMock(DANIEL_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    const returned = setIncomeComponentMock(DANIEL_CASE_ID, "overtime", { included: true, reason: "r" }, 5_000);
    expect(returned.candidate_monthly.value).toBe("6424.41");
    expect(getLatestIncomeMock(DANIEL_CASE_ID).candidate_monthly.value).toBe("6424.41");
    expect(getLatestIncomeMock(DANIEL_CASE_ID).components[1].override?.at).toBe("1970-01-01T00:00:05.000Z");
  });

  it("the store refuses a missing reason and leaves the result as it was", () => {
    const job = runIncomeMock(DANIEL_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    expect(statusOf(() => setIncomeComponentMock(DANIEL_CASE_ID, "overtime", { included: true, reason: "" }))).toBe(422);
    expect(getLatestIncomeMock(DANIEL_CASE_ID).candidate_monthly.value).toBe("5980.00");
  });
});

describe("running the income analysis on the mock", () => {
  const statusOf = (fn: () => unknown): number | undefined => {
    try {
      fn();
    } catch (e) {
      return (e as ApiError).status;
    }
    return undefined;
  };

  it("has nothing to show before the first run", () => {
    expect(statusOf(() => getLatestIncomeMock(DANIEL_CASE_ID))).toBe(404);
  });

  it("queues, runs through its stages, and stores the result when the job finishes", () => {
    const t0 = 1_000_000;
    const job = runIncomeMock(DANIEL_CASE_ID, t0);
    expect(job).toMatchObject({ kind: "income_analysis", status: "queued" });

    const running = getJobMock(job.id, t0 + JOB_QUEUE_MS + JOB_RUN_MS / 2);
    expect(running.status).toBe("running");
    expect(["gather", "calculate", "explain", "checks"]).toContain(running.stage);
    expect(statusOf(() => getLatestIncomeMock(DANIEL_CASE_ID))).toBe(404); // not stored until it ends

    const done = getJobMock(job.id, t0 + JOB_QUEUE_MS + JOB_RUN_MS);
    expect(done.status).toBe("succeeded");
    const latest = getLatestIncomeMock(DANIEL_CASE_ID);
    expect(latest.candidate_monthly.value).toBe("5980.00");
    expect(latest.case_id).toBe(DANIEL_CASE_ID);
  });

  it("hands back a copy, so a screen cannot change the stored result", () => {
    const job = runIncomeMock(DANIEL_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    getLatestIncomeMock(DANIEL_CASE_ID).components[0].included = false;
    expect(getLatestIncomeMock(DANIEL_CASE_ID).components[0].included).toBe(true);
  });

  it("refuses a case with no income documents", () => {
    expect(statusOf(() => runIncomeMock(ANGELA_CASE_ID))).toBe(422);
    expect(statusOf(() => runIncomeMock("not-a-case"))).toBe(422);
  });
});
