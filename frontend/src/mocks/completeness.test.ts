import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-error";
import { CHECKLIST_BY_PILLAR, type ChecklistResult } from "@/lib/completeness";
import { applyOverride, buildCompleteness, outstandingFrom, overallFrom } from "./completeness";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import {
  getLatestCompletenessMock,
  overrideCompletenessItemMock,
  resetMockStore,
  runCompletenessMock,
} from "./store";

beforeEach(() => resetMockStore());

const AT = "2026-11-20T10:00:00.000Z";
const daniel = (): ChecklistResult =>
  buildCompleteness(DANIEL_CASE_ID, CHECKLIST_BY_PILLAR.underwriting, "2026-11-20T09:00:00.000Z", "c1");
const angela = (): ChecklistResult =>
  buildCompleteness(ANGELA_CASE_ID, CHECKLIST_BY_PILLAR["loss-mitigation"], "2026-11-20T09:00:00.000Z", "c2");
const item = (r: ChecklistResult, id: string) => r.items.find((i) => i.item_id === id)!;
const statusOf = (fn: () => unknown): number | undefined => {
  try {
    fn();
  } catch (e) {
    return (e as ApiError).status;
  }
  return undefined;
};

describe("Daniel's mock completeness result", () => {
  it("is incomplete: pay stubs, W-2s, tax returns and the bank statements are each partly met", () => {
    const r = daniel();
    expect(r.overall_status).toBe("incomplete");
    expect(r.items.map((i) => [i.item_id, i.status])).toEqual([
      ["pay_stubs_30_days", "partial"],
      ["w2_two_years", "partial"],
      ["tax_returns_two_years", "partial"],
      ["bank_statements_2_months", "partial"],
      ["credit_report_120_days", "satisfied"],
    ]);
  });

  it("gives the reason for each item, with the numbers from the scenario", () => {
    const r = daniel();
    expect(item(r, "pay_stubs_30_days").reason).toBe("14 of 30 days of pay stubs found");
    expect(item(r, "w2_two_years").reason).toContain("2024 is missing");
    expect(item(r, "bank_statements_2_months").reason).toContain("Page 1 of 3 but only 2 pages");
  });

  it("lists what to ask for, one line per item that is not met, and nothing for the credit report", () => {
    expect(daniel().outstanding).toEqual([
      "Pay stubs for 16 more days (14 of 30 days found)",
      "W-2 for 2024",
      "Form 1040 for 2024",
      "Page 3 of the August 2026 bank statement (the footer says Page 1 of 3, 2 pages uploaded)",
    ]);
  });

  it("is labelled illustrative and names its checklist and version", () => {
    const r = daniel();
    expect(r).toMatchObject({ checklist_id: "pillar1-wage-earner", checklist_version: "1", checklist_label: "illustrative" });
  });
});

describe("Angela's mock completeness result", () => {
  it("is incomplete only because the August 2026 bank statement is missing", () => {
    const r = angela();
    expect(r.overall_status).toBe("incomplete");
    expect(r.items.filter((i) => i.status !== "satisfied").map((i) => i.item_id)).toEqual(["bank_statement_2026-08"]);
    expect(item(r, "bank_statement_2026-08").status).toBe("missing");
    expect(r.outstanding).toEqual(["August 2026 bank statement"]);
  });
});

describe("running a checklist on the mock", () => {
  it("refuses an unknown case (404), an unknown checklist (422) and a checklist for the wrong pillar (422)", () => {
    expect(statusOf(() => buildCompleteness("nope", CHECKLIST_BY_PILLAR.underwriting, AT, "c"))).toBe(404);
    expect(statusOf(() => buildCompleteness(DANIEL_CASE_ID, "made-up@1", AT, "c"))).toBe(422);
    expect(statusOf(() => buildCompleteness(DANIEL_CASE_ID, CHECKLIST_BY_PILLAR["loss-mitigation"], AT, "c"))).toBe(422);
  });

  it("answers 404 for the latest result until the checklist has been run", () => {
    expect(statusOf(() => getLatestCompletenessMock(DANIEL_CASE_ID))).toBe(404);
  });

  it("stores the result so it is there again later, and hands back copies", () => {
    runCompletenessMock(DANIEL_CASE_ID, CHECKLIST_BY_PILLAR.underwriting, 5_000);
    const latest = getLatestCompletenessMock(DANIEL_CASE_ID);
    expect(latest.run_at).toBe("1970-01-01T00:00:05.000Z");
    latest.items[0].status = "satisfied";
    expect(getLatestCompletenessMock(DANIEL_CASE_ID).items[0].status).toBe("partial");
  });

  it("keeps each case's result apart", () => {
    runCompletenessMock(DANIEL_CASE_ID, CHECKLIST_BY_PILLAR.underwriting);
    expect(statusOf(() => getLatestCompletenessMock(ANGELA_CASE_ID))).toBe(404);
  });
});

describe("overriding an item", () => {
  it("counts a missing item as satisfied: Angela's result becomes complete with nothing outstanding", () => {
    const r = applyOverride(angela(), "bank_statement_2026-08", "  Statement requested, due Monday  ", "demo.reviewer", AT);
    expect(item(r, "bank_statement_2026-08").status).toBe("overridden");
    expect(r.overall_status).toBe("complete");
    expect(r.outstanding).toEqual([]);
  });

  it("records who, when and why, and keeps what the checklist found", () => {
    const r = applyOverride(angela(), "bank_statement_2026-08", "Statement requested", "demo.reviewer", AT);
    expect(item(r, "bank_statement_2026-08")).toMatchObject({
      override_reason: "Statement requested",
      original_status: "missing",
      overridden_by: "demo.reviewer",
      overridden_at: AT,
      reason: "No bank statement found for August 2026. October 2026 was found.", // the checklist's own answer
    });
  });

  it("leaves Daniel incomplete while other items are still not met, and shortens the outstanding list", () => {
    const r = applyOverride(daniel(), "w2_two_years", "Employer letter received", "u", AT);
    expect(r.overall_status).toBe("incomplete");
    expect(r.outstanding).toHaveLength(3);
    expect(r.outstanding).not.toContain("W-2 for 2024");
    expect(item(r, "w2_two_years").original_status).toBe("partial");
  });

  it("does not change the other items or the result it was given", () => {
    const before = daniel();
    const r = applyOverride(before, "w2_two_years", "reason", "u", AT);
    expect(item(r, "pay_stubs_30_days")).toEqual(item(before, "pay_stubs_30_days"));
    expect(item(before, "w2_two_years").status).toBe("partial");
    expect(before.outstanding).toHaveLength(4);
  });

  it("refuses a missing, blank or too long reason (422)", () => {
    const go = (reason: string) => () => applyOverride(angela(), "bank_statement_2026-08", reason, "u", AT);
    expect(statusOf(go(""))).toBe(422);
    expect(statusOf(go("   "))).toBe(422);
    expect(statusOf(go("x".repeat(501)))).toBe(422);
    expect(statusOf(go("x".repeat(500)))).toBeUndefined();
  });

  it("refuses an unknown item (404), a satisfied item and an item already overridden (422)", () => {
    expect(statusOf(() => applyOverride(angela(), "nope", "reason", "u", AT))).toBe(404);
    expect(statusOf(() => applyOverride(angela(), "hardship_letter", "reason", "u", AT))).toBe(422);
    const done = applyOverride(angela(), "bank_statement_2026-08", "reason", "u", AT);
    expect(statusOf(() => applyOverride(done, "bank_statement_2026-08", "again", "u", AT))).toBe(422);
  });

  it("works out the overall status and the outstanding list from the items", () => {
    expect(overallFrom([])).toBe("complete");
    expect(overallFrom(daniel().items)).toBe("incomplete");
    expect(outstandingFrom(angela().items)).toEqual(["August 2026 bank statement"]);
  });
});

describe("the store keeps overrides", () => {
  it("refuses an override before a run (404), then keeps it as the latest result", () => {
    expect(statusOf(() => overrideCompletenessItemMock(ANGELA_CASE_ID, "bank_statement_2026-08", "r"))).toBe(404);
    runCompletenessMock(ANGELA_CASE_ID, CHECKLIST_BY_PILLAR["loss-mitigation"]);
    const returned = overrideCompletenessItemMock(ANGELA_CASE_ID, "bank_statement_2026-08", "r", 5_000);
    expect(returned.overall_status).toBe("complete");
    const latest = getLatestCompletenessMock(ANGELA_CASE_ID);
    expect(latest.overall_status).toBe("complete");
    expect(item(latest, "bank_statement_2026-08").overridden_at).toBe("1970-01-01T00:00:05.000Z");
  });

  it("leaves the result as it was when the reason is refused", () => {
    runCompletenessMock(ANGELA_CASE_ID, CHECKLIST_BY_PILLAR["loss-mitigation"]);
    expect(statusOf(() => overrideCompletenessItemMock(ANGELA_CASE_ID, "bank_statement_2026-08", ""))).toBe(422);
    expect(getLatestCompletenessMock(ANGELA_CASE_ID).overall_status).toBe("incomplete");
  });

  it("never uses the decision words", () => {
    const text = JSON.stringify([daniel(), angela()]);
    expect(text).not.toMatch(/approv|deny|denied|offer|eligib|qualifies/i);
  });
});
