import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-error";
import type { HardshipAssessment } from "@/lib/hardship-types";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import { applyBudgetAdjustment, applyConfirmation, buildAngelaHardship, hasHardshipSeed } from "./hardship";
import {
  adjustBudgetItemMock,
  confirmProfileItemMock,
  getJobMock,
  getLatestHardshipMock,
  JOB_QUEUE_MS,
  JOB_RUN_MS,
  resetMockStore,
  runHardshipMock,
} from "./store";

beforeEach(() => resetMockStore());

const AT = "2026-11-20T10:00:00.000Z";
const assessment = (): HardshipAssessment => buildAngelaHardship("2026-11-20T09:00:00.000Z");
const line = (a: HardshipAssessment, id: string) => a.budget.lines.find((l) => l.id === id)!;
const measure = (a: HardshipAssessment, id: string) => a.measures.find((m) => m.id === id)!;
const check = (a: HardshipAssessment, id: string) => a.checks.find((c) => c.id === id)!;
const profile = (a: HardshipAssessment, key: string) => a.profile.find((p) => p.key === key)!;
const statusOf = (fn: () => unknown): number | undefined => {
  try {
    fn();
  } catch (e) {
    return (e as ApiError).status;
  }
  return undefined;
};
const adjust = (a: HardshipAssessment, amount: string, id = "other") =>
  applyBudgetAdjustment(a, id, { amount, reason: "One-off repair" }, "demo.reviewer", AT);

describe("Angela's mock hardship assessment: the letter and the profile", () => {
  it("reads the profile from the letter: reduction in income, July 2026, unknown duration, keep the home", () => {
    const a = assessment();
    expect(a.profile.map((p) => [p.key, p.value_label])).toEqual([
      ["primary_reason", "Reduction in income"],
      ["onset", "July 2026"],
      ["duration", "Unknown"],
      ["intent", "Keep the home"],
    ]);
    expect(a.settings_label).toBe("illustrative");
    expect(a.case_id).toBe(ANGELA_CASE_ID);
  });

  it("gives the letter 16 lines with IDs p1-L1 to p1-L16", () => {
    const a = assessment();
    expect(a.letter.lines).toHaveLength(16);
    expect(a.letter.lines[5]).toEqual({
      id: "p1-L6",
      text: "Because my employer cut my hours from 40 to 30 a week in July, my pay fell by a quarter.",
    });
  });

  it("every quote is an exact piece of the lines it cites, and is marked verified", () => {
    const a = assessment();
    for (const p of a.profile) {
      expect(p.quote).not.toBeNull();
      expect(p.quote_verified).toBe(true);
      const cited = p.quote!.line_ids.map((id) => a.letter.lines.find((l) => l.id === id)!.text).join(" ");
      expect(cited).toContain(p.quote!.text);
    }
  });

  it("starts with nothing reviewed", () => {
    expect(assessment().profile.every((p) => p.review === null)).toBe(true);
  });

  it("allows a list of values for the reason, the duration and the intent, and a typed month for the onset", () => {
    const a = assessment();
    expect(profile(a, "primary_reason").options).toHaveLength(9);
    expect(profile(a, "duration").options?.map((o) => o.value)).toEqual(["temporary", "long_term", "unknown"]);
    expect(profile(a, "intent").options?.map((o) => o.value)).toEqual(["keep", "sell", "unsure"]);
    expect(profile(a, "onset").options).toBeNull();
  });
});

describe("Angela's mock hardship assessment: the consistency checks", () => {
  it("has six checks: five agree and the spending check is flagged", () => {
    const a = assessment();
    expect(a.checks.map((c) => [c.id, c.status])).toEqual([
      ["hours_vs_pay", "consistent"],
      ["reason", "consistent"],
      ["intent", "consistent"],
      ["income", "consistent"],
      ["arrears", "consistent"],
      ["spending", "flagged"],
    ]);
  });

  it("compares the hours cut with the change in pay, with both values and sources", () => {
    const c = check(assessment(), "hours_vs_pay");
    expect(c.stated.value).toBe("Hours cut from 40 to 30 a week");
    expect(c.documented.value).toContain("2,800.00 to 2,100.00");
    expect(c.documented.value).toContain("25.00%");
    expect(c.stated.source).toMatchObject({ document_id: expect.any(String), line_ids: ["p1-L6"] });
  });

  it("gives every check both values and a source on each side", () => {
    for (const c of assessment().checks) {
      expect(c.stated.value && c.documented.value && c.detail).toBeTruthy();
      expect(c.stated.source.label && c.documented.source.label).toBeTruthy();
    }
  });

  it("flags the spending: 3,420.00 stated against 3,630.00 observed", () => {
    const c = check(assessment(), "spending");
    expect(c.stated.value).toBe("3,420.00 a month");
    expect(c.documented.value).toBe("3,630.00 a month");
    expect(c.detail).toBe("Observed 'other' spending 410.00 against 200.00 stated — ask the borrower");
  });
});

describe("Angela's mock hardship assessment: the budget and the measures", () => {
  it("shows stated and observed by category, and only 'Other' differs", () => {
    const a = assessment();
    expect(a.budget.lines.map((l) => [l.category, l.stated, l.observed])).toEqual([
      ["Housing (mortgage)", "1720.00", "1720.00"],
      ["Utilities", "310.00", "310.00"],
      ["Food and everyday", "780.00", "780.00"],
      ["Loan payments", "410.00", "410.00"],
      ["Other", "200.00", "410.00"],
    ]);
    expect(a.budget.stated_total).toBe("3420.00");
    expect(a.budget.observed_total).toBe("3630.00");
    expect(a.budget.observed_basis).toContain("July 2026 statement");
  });

  it("flags 'Other' with the template sentence and leaves the other lines alone", () => {
    const a = assessment();
    expect(line(a, "other")).toMatchObject({
      difference: "210.00",
      flagged: true,
      flag_message: "Observed 'other' spending 410.00 against 200.00 stated — ask the borrower",
    });
    for (const id of ["housing", "utilities", "food", "loans"]) {
      expect(line(a, id)).toMatchObject({ difference: "0.00", flagged: false, flag_message: null });
    }
  });

  it("monthly surplus: stated -70.00, observed -280.00 flagged, with working for both", () => {
    const m = measure(assessment(), "surplus");
    expect(m.value).toBe("-280.00");
    expect(m.compare).toEqual({ label: "Stated", value: "-70.00", unit: "money" });
    expect(m.flagged).toBe(true);
    expect(m.working.map((w) => [w.formula, w.result])).toEqual([
      ["3,350.00 − 3,420.00", "-70.00"],
      ["3,350.00 − 3,630.00", "-280.00"],
    ]);
  });

  it("housing ratio 40.95% up from 30.71%, arrears 5,160.00, liquid assets 640.25 = 12.41% of arrears", () => {
    const a = assessment();
    expect(measure(a, "housing_ratio")).toMatchObject({
      value: "40.95",
      unit: "percent",
      compare: { label: "Before the cut", value: "30.71", unit: "percent" },
    });
    expect(measure(a, "housing_ratio").working[1].formula).toBe("1,720.00 ÷ 5,600.00 × 100");
    expect(measure(a, "arrears").value).toBe("5160.00");
    expect(measure(a, "liquid_assets")).toMatchObject({ value: "640.25", note: "12.41% of arrears" });
    expect(measure(a, "income_change").value).toBe("-25.00");
  });

  it("gives every measure working and evidence, and keeps every figure as text", () => {
    const a = assessment();
    for (const m of a.measures) {
      expect(m.working.length).toBeGreaterThan(0);
      expect(m.evidence.length).toBeGreaterThan(0);
    }
    expect(JSON.stringify(a)).not.toMatch(/"(value|stated|observed|difference)":\s*-?\d/);
  });

  it("never uses the decision words", () => {
    expect(JSON.stringify(assessment())).not.toMatch(/approv|deny|denied|offer|eligib|qualifies/i);
  });

  it("only Angela has a hardship letter to read", () => {
    expect(hasHardshipSeed(ANGELA_CASE_ID)).toBe(true);
    expect(hasHardshipSeed(DANIEL_CASE_ID)).toBe(false);
  });
});

describe("confirming and correcting a profile item", () => {
  it("a confirmation records who and when, and keeps the value", () => {
    const a = applyConfirmation(assessment(), { key: "primary_reason", action: "confirm" }, "demo.reviewer", AT);
    expect(profile(a, "primary_reason").value_label).toBe("Reduction in income");
    expect(profile(a, "primary_reason").review).toEqual({
      status: "confirmed",
      reason: null,
      by: "demo.reviewer",
      at: AT,
      original_label: "Reduction in income",
    });
  });

  it("a correction replaces the value, keeps the letter reading and records the reason", () => {
    const a = applyConfirmation(
      assessment(),
      { key: "duration", action: "correct", value: "long_term", reason: "  Employer said the cut is permanent  " },
      "demo.reviewer",
      AT,
    );
    expect(profile(a, "duration")).toMatchObject({ value: "long_term", value_label: "Long-term" });
    expect(profile(a, "duration").review).toEqual({
      status: "corrected",
      reason: "Employer said the cut is permanent",
      by: "demo.reviewer",
      at: AT,
      original_label: "Unknown",
    });
    expect(profile(a, "duration").quote?.text).toContain("I do not know whether my hours will return"); // quote untouched
  });

  it("the onset is a month written YYYY-MM, shown as a month name", () => {
    const a = applyConfirmation(
      assessment(),
      { key: "onset", action: "correct", value: "2026-06", reason: "Pay stub shows the cut from June" },
      "u",
      AT,
    );
    expect(profile(a, "onset")).toMatchObject({ value: "2026-06", value_label: "June 2026" });
    expect(profile(a, "onset").review?.original_label).toBe("July 2026");
  });

  it("refuses an onset that is not a month written YYYY-MM (422), as the backend does", () => {
    for (const value of ["June 2026", "2026-13", "2026-6", "26-06"]) {
      expect(() =>
        applyConfirmation(assessment(), { key: "onset", action: "correct", value, reason: "r" }, "u", AT),
      ).toThrow(expect.objectContaining({ status: 422 }));
    }
  });

  it("correcting twice, or confirming then correcting, still remembers what the letter said", () => {
    let a = applyConfirmation(assessment(), { key: "duration", action: "confirm" }, "u", AT);
    a = applyConfirmation(a, { key: "duration", action: "correct", value: "temporary", reason: "r1" }, "u", AT);
    a = applyConfirmation(a, { key: "duration", action: "correct", value: "long_term", reason: "r2" }, "u", AT);
    expect(profile(a, "duration").review?.original_label).toBe("Unknown");
    expect(profile(a, "duration").value_label).toBe("Long-term");
  });

  it("does not change the other items or the assessment it was given", () => {
    const before = assessment();
    const a = applyConfirmation(before, { key: "intent", action: "confirm" }, "u", AT);
    expect(profile(a, "onset").review).toBeNull();
    expect(profile(before, "intent").review).toBeNull();
  });

  it("refuses a correction with no value, no reason, a blank reason, a too long reason or a value off the list (422)", () => {
    const go = (value: string | undefined, reason: string | undefined) => () =>
      applyConfirmation(assessment(), { key: "duration", action: "correct", value, reason }, "u", AT);
    expect(statusOf(go(undefined, "r"))).toBe(422);
    expect(statusOf(go("long_term", undefined))).toBe(422);
    expect(statusOf(go("long_term", "   "))).toBe(422);
    expect(statusOf(go("long_term", "x".repeat(501)))).toBe(422);
    expect(statusOf(go("forever", "r"))).toBe(422);
    expect(statusOf(go("long_term", "x".repeat(500)))).toBeUndefined();
  });

  it("refuses an unknown item (404) and an unknown action (422)", () => {
    expect(statusOf(() => applyConfirmation(assessment(), { key: "nope" as never, action: "confirm" }, "u", AT))).toBe(404);
    expect(statusOf(() => applyConfirmation(assessment(), { key: "intent", action: "approve" as never }, "u", AT))).toBe(422);
  });
});

describe("adjusting a budget item", () => {
  it("marking the 'other' spend as one-off at 200.00 clears the flag and the deficit gap", () => {
    const a = adjust(assessment(), "200.00");
    expect(line(a, "other")).toMatchObject({ observed: "200.00", difference: "0.00", flagged: false, flag_message: null });
    expect(a.budget.observed_total).toBe("3420.00");
    expect(measure(a, "surplus")).toMatchObject({ value: "-70.00", flagged: false, flag_message: null });
    expect(measure(a, "surplus").working[1]).toMatchObject({ formula: "3,350.00 − 3,420.00", result: "-70.00" });
    expect(check(a, "spending")).toMatchObject({ status: "consistent", documented: { value: "3,420.00 a month" } });
  });

  it("records who, when and why, and keeps what the documents showed", () => {
    const a = adjust(assessment(), "200.00");
    expect(line(a, "other").adjustment).toEqual({
      original_observed: "410.00",
      reason: "One-off repair",
      by: "demo.reviewer",
      at: AT,
    });
  });

  it("adjusting again keeps the first observed amount, not the previous adjustment", () => {
    const a = adjust(adjust(assessment(), "300.00"), "250.00");
    expect(line(a, "other").adjustment?.original_observed).toBe("410.00");
    expect(line(a, "other").observed).toBe("250.00");
  });

  it("a smaller change still flagged: 300.00 gives a deficit of 170.00 against 70.00 stated", () => {
    const a = adjust(assessment(), "300.00");
    expect(line(a, "other")).toMatchObject({ difference: "100.00", flagged: true });
    expect(measure(a, "surplus")).toMatchObject({ value: "-170.00", flagged: true });
    expect(measure(a, "surplus").flag_message).toBe("Observed deficit 170.00 against 70.00 stated");
  });

  it("applies the tolerance: a difference of 25.00 or less is not flagged", () => {
    expect(line(adjust(assessment(), "225.00"), "other").flagged).toBe(false); // 25.00 exactly
    expect(line(adjust(assessment(), "226.00"), "other").flagged).toBe(true); // 26.00
  });

  it("writes the amount with two decimals", () => {
    expect(line(adjust(assessment(), "200.5"), "other").observed).toBe("200.50");
    expect(line(adjust(assessment(), "200"), "other").observed).toBe("200.00");
  });

  it("does not touch the measures that come from the pay stubs and the loan", () => {
    const before = assessment();
    const a = adjust(before, "200.00");
    for (const id of ["housing_ratio", "arrears", "liquid_assets", "income_change"]) {
      expect(measure(a, id)).toEqual(measure(before, id));
    }
    expect(a.profile).toEqual(before.profile);
  });

  it("does not change the other lines or the assessment it was given", () => {
    const before = assessment();
    const a = adjust(before, "200.00");
    expect(line(a, "utilities")).toEqual(line(before, "utilities"));
    expect(line(before, "other").observed).toBe("410.00");
    expect(before.budget.observed_total).toBe("3630.00");
  });

  it("refuses a missing, blank or too long reason (422)", () => {
    const go = (reason: string) => () =>
      applyBudgetAdjustment(assessment(), "other", { amount: "200.00", reason }, "u", AT);
    expect(statusOf(go(""))).toBe(422);
    expect(statusOf(go("   "))).toBe(422);
    expect(statusOf(go("x".repeat(501)))).toBe(422);
    expect(statusOf(go("x".repeat(500)))).toBeUndefined();
  });

  it("refuses an amount that is not a plain amount (422) and an unknown item (404)", () => {
    for (const bad of ["", "abc", "-5", "1,000", "200.123"]) expect(statusOf(() => adjust(assessment(), bad))).toBe(422);
    expect(statusOf(() => adjust(assessment(), "200.00", "nope"))).toBe(404);
  });
});

describe("running the hardship analysis on the mock", () => {
  it("has nothing to show before the first run (404), and refuses a case with no letter (422)", () => {
    expect(statusOf(() => getLatestHardshipMock(ANGELA_CASE_ID))).toBe(404);
    expect(statusOf(() => runHardshipMock(DANIEL_CASE_ID))).toBe(422);
  });

  it("queues, runs through its stages, and stores the result when the job finishes", () => {
    const t0 = 1_000_000;
    const job = runHardshipMock(ANGELA_CASE_ID, t0);
    expect(job).toMatchObject({ kind: "hardship_assessment", status: "queued" });
    const running = getJobMock(job.id, t0 + JOB_QUEUE_MS + JOB_RUN_MS / 2);
    expect(["read", "compare", "budget", "checks"]).toContain(running.stage);
    expect(statusOf(() => getLatestHardshipMock(ANGELA_CASE_ID))).toBe(404); // not stored until it ends

    expect(getJobMock(job.id, t0 + JOB_QUEUE_MS + JOB_RUN_MS).status).toBe("succeeded");
    expect(getLatestHardshipMock(ANGELA_CASE_ID).measures[0].value).toBe("-280.00");
  });

  it("hands back copies, so a screen cannot change the stored result", () => {
    const job = runHardshipMock(ANGELA_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    getLatestHardshipMock(ANGELA_CASE_ID).budget.lines[0].observed = "0.00";
    expect(getLatestHardshipMock(ANGELA_CASE_ID).budget.lines[0].observed).toBe("1720.00");
  });

  it("keeps confirmations and adjustments as the latest result, and refuses both before a run (404)", () => {
    expect(statusOf(() => confirmProfileItemMock(ANGELA_CASE_ID, { key: "intent", action: "confirm" }))).toBe(404);
    expect(statusOf(() => adjustBudgetItemMock(ANGELA_CASE_ID, "other", { amount: "200.00", reason: "r" }))).toBe(404);

    const job = runHardshipMock(ANGELA_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    confirmProfileItemMock(ANGELA_CASE_ID, { key: "intent", action: "confirm" }, 5_000);
    const returned = adjustBudgetItemMock(ANGELA_CASE_ID, "other", { amount: "200.00", reason: "One-off" }, 6_000);
    expect(returned.budget.observed_total).toBe("3420.00");

    const latest = getLatestHardshipMock(ANGELA_CASE_ID);
    expect(profile(latest, "intent").review?.at).toBe("1970-01-01T00:00:05.000Z");
    expect(measure(latest, "surplus").value).toBe("-70.00");
  });

  it("leaves the result as it was when a change is refused", () => {
    const job = runHardshipMock(ANGELA_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    expect(statusOf(() => adjustBudgetItemMock(ANGELA_CASE_ID, "other", { amount: "200.00", reason: "" }))).toBe(422);
    expect(getLatestHardshipMock(ANGELA_CASE_ID).budget.observed_total).toBe("3630.00");
  });
});
