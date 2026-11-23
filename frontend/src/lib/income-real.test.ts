import { describe, expect, it } from "vitest";
import { componentRequest, toIncomeAnalysis } from "./income-real";
import { realDanielIncome, SAMPLE_CANDIDATE_LABEL, SAMPLE_CASE_ID, SAMPLE_STUB_ID } from "./income-real-sample";

const translated = () => toIncomeAnalysis(realDanielIncome(), SAMPLE_CASE_ID);
const component = (a: ReturnType<typeof translated>, kind: string) => a.components.find((c) => c.kind === kind)!;

describe("the real income answer, translated for the screen: top level", () => {
  it("keeps the run, the case and the finish time", () => {
    expect(translated()).toMatchObject({
      id: "99999999-9999-4999-8999-000000000003",
      case_id: SAMPLE_CASE_ID,
      run_at: "2026-11-23T09:00:04Z",
    });
  });

  it("reads the method's name, version and label from the backend's config versions", () => {
    expect(translated()).toMatchObject({ method_version: "income-method@2026-11-19.1", method_label: "illustrative" });
  });

  it("is authoritative only when the method says so, and copes with versions it cannot read", () => {
    const real = realDanielIncome();
    real.config_versions = { income_method: { name: "income-method", version: "2", label: "authoritative" } };
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID)).toMatchObject({ method_version: "income-method@2", method_label: "authoritative" });
    real.config_versions = { other: { label: "authoritative" } }; // no income entry: the first one is used
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID).method_label).toBe("authoritative");
    real.config_versions = { income_method: { name: "income-method" } };
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID).method_version).toBe("income-method");
    real.config_versions = {};
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID)).toMatchObject({ method_version: "income method", method_label: "illustrative" });
  });

  it("uses the start time when the run has no finish time", () => {
    const real = realDanielIncome();
    real.finished_at = null;
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID).run_at).toBe("2026-11-23T09:00:00Z");
  });

  it("keeps the backend's wording for the candidate label", () => {
    expect(translated().candidate_label).toBe(SAMPLE_CANDIDATE_LABEL);
  });
});

describe("the real income answer: the components", () => {
  it("shows base pay, overtime and bonus with the employer, in the backend's order", () => {
    const a = translated();
    expect(a.components.map((c) => [c.kind, c.label])).toEqual([
      ["base_pay", "Base pay (Cedar Valley Manufacturing)"],
      ["overtime", "Overtime (Cedar Valley Manufacturing)"],
      ["bonus", "Bonus (Cedar Valley Manufacturing)"],
    ]);
  });

  it("adds the borrower to the label when there is more than one", () => {
    const real = realDanielIncome();
    real.components[1].borrower = "Maria Reyes";
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID).components.map((c) => c.label)).toEqual([
      "Base pay (Daniel Reyes, Cedar Valley Manufacturing)",
      "Overtime (Maria Reyes, Cedar Valley Manufacturing)",
      "Bonus (Daniel Reyes, Cedar Valley Manufacturing)",
    ]);
  });

  it("names a component with no employer by its kind alone, and an unknown kind plainly", () => {
    const real = realDanielIncome();
    real.components[0].employer = null;
    real.components[1].component = "tips";
    const a = toIncomeAnalysis(real, SAMPLE_CASE_ID);
    expect(a.components[0].label).toBe("Base pay");
    expect(a.components[1]).toMatchObject({ kind: "other", label: "Tips (Cedar Valley Manufacturing)" });
  });

  it("shows the monthly amount with its working, cut into a formula and a result, and where it was read", () => {
    const base = component(translated(), "base_pay");
    expect(base.monthly.value).toBe("5980.00");
    expect(base.monthly.working).toEqual([
      { label: "Rate x regular hours x pay periods per year / 12", formula: "34.50 x 80.00 x 26 / 12", result: "5980.00" },
    ]);
    expect(base.monthly.evidence).toEqual([
      { label: "Gross pay current", document_id: SAMPLE_STUB_ID, line_ids: ["p1-L14"] },
      { label: "Pay frequency", document_id: SAMPLE_STUB_ID, line_ids: ["p1-L8"] },
    ]);
  });

  it("shows the current period and year to date as plain amounts, with no working, and a dash when missing", () => {
    const overtime = component(translated(), "overtime");
    expect(overtime.current_period).toEqual({ value: "204.93", working: [], evidence: [] });
    expect(overtime.year_to_date).toEqual({ value: "4217.43", working: [], evidence: [] });
    expect(component(translated(), "bonus").current_period).toBeNull();
  });

  it("keeps what the method decided and why, even when it was counted or left out", () => {
    const a = translated();
    expect(component(a, "base_pay")).toMatchObject({ included: true, rule_included: true, rule_note: null });
    expect(component(a, "overtime")).toMatchObject({
      included: false,
      rule_included: false,
      rule_note: "Documented history covers 2026 only. 24 months are needed to count it.",
    });
  });

  it("a person's decision keeps who, when and why, beside what the method said", () => {
    const real = realDanielIncome();
    real.components[1].included = true;
    real.components[1].exclusion_reason = null;
    real.components[1].override = { included: true, reason: "Employer letter received", by: "user-1", at: "2026-11-23T10:00:00Z" };
    const overtime = component(toIncomeAnalysis(real, SAMPLE_CASE_ID), "overtime");
    expect(overtime).toMatchObject({ included: true, rule_included: false });
    expect(overtime.override).toEqual({ included: true, reason: "Employer letter received", by: "user-1", at: "2026-11-23T10:00:00Z" });
  });

  it("shows a monthly amount with no working when the backend sent no calculation", () => {
    const real = realDanielIncome();
    real.components[0].calculation = null;
    expect(component(toIncomeAnalysis(real, SAMPLE_CASE_ID), "base_pay").monthly).toEqual({ value: "5980.00", working: [], evidence: [] });
  });
});

describe("the real income answer: the candidate", () => {
  it("is the backend's figure and its working (one term is written without an equals sign)", () => {
    const c = translated().candidate_monthly;
    expect(c.value).toBe("5980.00");
    expect(c.working).toEqual([
      { label: "Sum of the monthly amounts of the components that count", formula: "5,980.00", result: "5980.00" },
    ]);
    expect(c.evidence).toHaveLength(1);
  });

  it("is an empty value, shown as a dash, when the backend could not work it out", () => {
    const real = realDanielIncome();
    real.candidate_monthly_income = null;
    real.candidate = null;
    expect(toIncomeAnalysis(real, SAMPLE_CASE_ID).candidate_monthly).toEqual({ value: "", working: [], evidence: [] });
  });
});

describe("the real income answer: flags, checks and the trend", () => {
  it("keeps the INC-W flags as flags, with the backend's sentence, working, evidence and status", () => {
    const flags = translated().flags;
    expect(flags.map((f) => f.code)).toEqual(["INC-W101", "INC-W101", "INC-W102"]);
    expect(flags[2]).toMatchObject({
      severity: "warning",
      message: "Year-to-date overtime averages 233.19 per pay period, against 204.93 this period (difference 28.26).",
      working: "4,217.43 / 18.09 periods = 233.19",
      status: "open",
      values: [],
      explanations: [],
    });
    expect(flags[0].evidence).toEqual([{ label: "Overtime ytd", document_id: SAMPLE_STUB_ID, line_ids: ["p1-L16"] }]);
  });

  it("turns the INC-CHK flags into checks, and an info-level one is consistent", () => {
    const checks = translated().checks;
    expect(checks).toEqual([
      {
        id: "INC-CHK-03:explained",
        label: "W-2 Box 5 against Box 1 and the Box 12 deferrals",
        status: "passed",
        detail: "W-2 Box 5 is 3,866.80 above Box 1 for 2025, which the Box 12 deferral codes (D) account for.",
      },
    ]);
  });

  it("a warning check is flagged", () => {
    const real = realDanielIncome();
    real.flags.push({
      id: "f9",
      code: "INC-CHK-02",
      severity: "warning",
      message: "The latest pay stub names Cedar Valley, but the latest W-2 names Cedar Valley Mfg.",
      status: "open",
      working: null,
      refs: [],
    });
    const check = toIncomeAnalysis(real, SAMPLE_CASE_ID).checks.find((c) => c.id === "INC-CHK-02")!;
    expect(check).toMatchObject({ label: "Employer on the pay stub and the W-2", status: "flagged" });
  });

  it("puts the trend sentence in the trend, not among the checks", () => {
    const a = translated();
    expect(a.trend).toEqual(["Gross pay rose 5.49% from 2024 (70,431.80) to 2025 (74,298.60)."]);
    expect(a.checks.map((c) => c.id)).not.toContain("INC-CHK-04:trend");
    expect(a.flags.map((f) => f.code)).not.toContain("INC-CHK-04:trend");
  });

  it("an unknown severity is a warning, an unknown check code is named plainly, and a resolved flag says so", () => {
    const real = realDanielIncome();
    real.flags[0].severity = "mystery";
    real.flags[0].status = "resolved";
    real.flags.push({ id: "f8", code: "INC-CHK-09", severity: "mystery", message: "m", status: "open", working: null, refs: [] });
    const a = toIncomeAnalysis(real, SAMPLE_CASE_ID);
    expect(a.flags[0]).toMatchObject({ severity: "warning", status: "resolved" });
    expect(a.checks.find((c) => c.id === "INC-CHK-09")).toMatchObject({ label: "INC-CHK-09", status: "flagged" });
  });
});

describe("the real income answer: explanations and document requests", () => {
  it("has no explanations yet, and says why in the backend's words; no document requests without them", () => {
    const a = translated();
    expect(a.explanations).toEqual([]);
    expect(a.explanations_note).toBe("explanations not generated");
    expect(a.document_requests).toEqual([]);
  });

  it("passes the explanations through once the backend sends them, and drops an empty note", () => {
    const real = realDanielIncome();
    real.explanations = ["Overtime was paid for 9 months; possible — to be confirmed."];
    real.explanations_note = "";
    const a = toIncomeAnalysis(real, SAMPLE_CASE_ID);
    expect(a.explanations).toEqual(["Overtime was paid for 9 months; possible — to be confirmed."]);
    expect(a.explanations_note).toBeNull();
  });
});

describe("what a person sends to the real backend", () => {
  it("includes or excludes a component with exactly two fields", () => {
    expect(componentRequest({ included: true, reason: "Employer letter" })).toEqual({ included: true, reason: "Employer letter" });
    expect(Object.keys(componentRequest({ included: false, reason: "x", extra: 1 } as never)).sort()).toEqual(["included", "reason"]);
  });
});
