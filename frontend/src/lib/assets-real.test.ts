import { describe, expect, it } from "vitest";
import { obligationRequest, scenarioRequest, toAssetAnalysis, toLoanScenario, transactionRequest } from "./assets-real";
import { realDanielAssets, realDanielScenario, SAMPLE_BANK_ID, SAMPLE_CASE_ID } from "./assets-real-sample";

const translated = () => toAssetAnalysis(realDanielAssets(), SAMPLE_CASE_ID);
const tx = (a: ReturnType<typeof translated>, description: string) => a.transactions.find((t) => t.description.startsWith(description))!;

describe("the real asset answer, translated for the screen: the figures", () => {
  it("keeps the run, the case, the note and the settings label", () => {
    const a = translated();
    expect(a).toMatchObject({
      id: "99999999-9999-4999-8999-000000000002",
      case_id: SAMPLE_CASE_ID,
      run_at: "2026-11-23T09:00:04Z",
      settings_label: "illustrative",
      note: "Candidate figures for the underwriter to review. They are not a decision.",
    });
  });

  it("shows money as the backend wrote it", () => {
    const a = translated();
    expect([a.documented_assets?.value, a.funds_to_close?.value, a.funds_shortfall?.value, a.monthly_obligations?.value]).toEqual([
      "9226.32",
      "36500.00",
      "27273.68",
      "693.00",
    ]);
    expect(a.documented_assets?.unit).toBe("money");
  });

  it("shows the ratios as the backend's own percentage text, not as the six-place decimal", () => {
    const a = translated();
    expect([a.front_end_ratio?.value, a.dti?.value, a.ltv?.value]).toEqual(["33.11", "44.70", "90.00"]);
    expect([a.front_end_ratio?.unit, a.dti?.unit, a.ltv?.unit]).toEqual(["percent", "percent", "percent"]);
  });

  it("shows a ratio as it came, never multiplied, when the working has no percentage", () => {
    const real = realDanielAssets();
    real.dti!.working = "(1,980.00 + 693.00) / 5,980.00";
    expect(toAssetAnalysis(real, SAMPLE_CASE_ID).dti).toMatchObject({ value: "0.446990", unit: "money" });
  });

  it("cuts the working into a formula and a result, and handles a sum that has only one term", () => {
    const a = translated();
    expect(a.dti?.working[0]).toEqual({
      label: "(proposed housing payment + monthly obligations) / candidate monthly income",
      formula: "(1,980.00 + 693.00) / 5,980.00",
      result: "44.70%",
    });
    expect(a.documented_assets?.working[0]).toMatchObject({ formula: "9,226.32", result: "9226.32" });
  });

  it("links a figure's evidence to the statement line, and names a hand-entered source", () => {
    const a = translated();
    expect(a.documented_assets?.evidence).toEqual([{ label: "Closing balance", document_id: SAMPLE_BANK_ID, line_ids: ["p3-L12"] }]);
    expect(a.funds_to_close?.evidence).toEqual([{ label: "Loan scenario", document_id: undefined, line_ids: [] }]);
    expect(a.front_end_ratio?.evidence.map((e) => e.label)).toEqual(["Loan scenario", "Candidate monthly income"]);
  });

  it("leaves a figure null when the backend could not work it out", () => {
    const real = realDanielAssets();
    real.front_end_ratio = null;
    real.dti = null;
    const a = toAssetAnalysis(real, SAMPLE_CASE_ID);
    expect(a.front_end_ratio).toBeNull();
    expect(a.dti).toBeNull();
    expect(a.ltv?.value).toBe("90.00");
  });

  it("shows the 'if overtime were counted' figure, and only those what-ifs", () => {
    const other = translated().other_figures;
    expect(other.map((o) => [o.id, o.label, o.figure.value])).toEqual([["dti_with_overtime", "DTI if overtime were counted", "41.61"]]);
  });

  it("is authoritative only when every setting says so", () => {
    const real = realDanielAssets();
    real.config_versions = { thresholds: { label: "authoritative" }, income_method: { label: "authoritative" } };
    expect(toAssetAnalysis(real, SAMPLE_CASE_ID).settings_label).toBe("authoritative");
    real.config_versions = { thresholds: { label: "authoritative" }, income_method: { label: "illustrative" } };
    expect(toAssetAnalysis(real, SAMPLE_CASE_ID).settings_label).toBe("illustrative");
    real.config_versions = {};
    expect(toAssetAnalysis(real, SAMPLE_CASE_ID).settings_label).toBe("illustrative");
  });

  it("uses the start time when the run has no finish time", () => {
    const real = realDanielAssets();
    real.finished_at = null;
    expect(toAssetAnalysis(real, SAMPLE_CASE_ID).run_at).toBe("2026-11-23T09:00:00Z");
  });
});

describe("the real asset answer: the lines", () => {
  it("shows money out with a minus sign, and money in without", () => {
    const a = translated();
    expect(tx(a, "OAKMONT").amount).toBe("-1425.00");
    expect(tx(a, "CEDAR").amount).toBe("2033.61");
    expect(tx(a, "ZELLE").amount).toBe("2000.00");
  });

  it("does not add a second minus sign to an amount that already has one", () => {
    const real = realDanielAssets();
    real.transactions[0].amount = "-1425.00";
    expect(tx(toAssetAnalysis(real, SAMPLE_CASE_ID), "OAKMONT").amount).toBe("-1425.00");
  });

  it("keeps the category, who chose it, what the system chose, and who changed it, when and why", () => {
    const t = tx(translated(), "TARGET");
    expect(t).toMatchObject({
      category: "everyday spending",
      category_source: "user",
      system_category: "other",
      change: { reason: "A grocery run", by: "user-1", at: "2026-11-23T10:00:00Z" },
    });
  });

  it("shows the backend's note when a deposit matches a pay stub", () => {
    const a = translated();
    expect(tx(a, "CEDAR").payroll_match).toBe("Net pay 2,033.61 matches the pay stub for 2026-09-04");
    expect(tx(a, "OAKMONT").payroll_match).toBeNull();
  });

  it("puts a flag on the line its evidence points at, and only that line", () => {
    const a = translated();
    expect(tx(a, "ZELLE").flags).toEqual([
      {
        code: "AL-W101",
        severity: "warning",
        message: "Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules.",
      },
    ]);
    expect(a.transactions.filter((t) => t.flags.length > 0)).toHaveLength(1);
  });

  it("does not attach a flag whose evidence names another document with the same line number", () => {
    const real = realDanielAssets();
    real.flags[0].refs = [{ document_id: "someone-else", field: "transaction", line_ids: ["p2-L10"] }];
    expect(tx(toAssetAnalysis(real, SAMPLE_CASE_ID), "ZELLE").flags).toEqual([]);
  });

  it("keeps sourced and its note, and an unknown severity becomes a warning", () => {
    const real = realDanielAssets();
    real.transactions[3].sourced = true;
    real.transactions[3].sourced_note = "Gift letter on file";
    real.flags[0].severity = "mystery";
    const a = toAssetAnalysis(real, SAMPLE_CASE_ID);
    expect(tx(a, "ZELLE")).toMatchObject({ sourced: true, sourced_note: "Gift letter on file" });
    expect(a.flags[0].severity).toBe("warning");
  });
});

describe("the real asset answer: debts and flags", () => {
  it("keeps each debt with its source, what counts, and why the system decided that", () => {
    const a = translated();
    expect(a.obligations.map((o) => [o.creditor, o.source, o.counts_toward_dti, o.balance])).toEqual([
      ["Northgate Card", "both", true, "2940.00"],
      ["Harbor Retail Card", "credit_report", true, "300.00"],
      ["Oakmont Apartments", "bank", false, null],
    ]);
    expect(a.obligations[2].reason).toBe("Current rent on a purchase of a primary residence.");
  });

  it("keeps the system's answer beside a person's change", () => {
    const real = realDanielAssets();
    real.obligations[1].counts_toward_dti = false;
    real.obligations[1].change = { reason: "Closed in October", by: "user-1", at: "2026-11-23T10:00:00Z" };
    const o = toAssetAnalysis(real, SAMPLE_CASE_ID).obligations[1];
    expect(o).toMatchObject({ counts_toward_dti: false, system_counts_toward_dti: true });
    expect(o.change).toEqual({ reason: "Closed in October", by: "user-1", at: "2026-11-23T10:00:00Z" });
  });

  it("lists the three flags with their messages and status, and links evidence", () => {
    const flags = translated().flags;
    expect(flags.map((f) => [f.code, f.status])).toEqual([
      ["AL-W101", "open"],
      ["AL-W105", "open"],
      ["AL-W106", "open"],
    ]);
    expect(flags[0].evidence).toEqual([{ label: "Transaction", document_id: SAMPLE_BANK_ID, line_ids: ["p2-L10"] }]);
    expect(flags[1].working).toBe("36,500.00 - 9,226.32 = 27,273.68");
  });
});

describe("the loan scenario", () => {
  it("reads the backend's scenario", () => {
    expect(toLoanScenario(realDanielScenario())).toEqual({
      purpose: "purchase",
      occupancy: "primary residence",
      property_value: "400000.00",
      loan_amount: "360000.00",
      proposed_housing_payment: "1980.00",
      funds_to_close: "36500.00",
      updated_at: "2026-11-23T08:00:00Z",
    });
  });

  it("sends exactly the six fields the backend accepts, as text", () => {
    const body = scenarioRequest({ ...toLoanScenario(realDanielScenario()), extra: "x" } as never);
    expect(Object.keys(body).sort()).toEqual(["funds_to_close", "loan_amount", "occupancy", "property_value", "proposed_housing_payment", "purpose"]);
    expect(body.property_value).toBe("400000.00");
  });
});

describe("what a person sends to the real backend", () => {
  it("a new category carries the category and the reason", () => {
    expect(transactionRequest({ category: "refund", reason: "Returned item" })).toEqual({ category: "refund", reason: "Returned item" });
  });

  it("marking a deposit sourced carries sourced and the reason, and unmarking sends false", () => {
    expect(transactionRequest({ sourced: true, reason: "Gift letter" })).toEqual({ sourced: true, reason: "Gift letter" });
    expect(transactionRequest({ sourced: false, reason: "Wrong deposit" })).toEqual({ sourced: false, reason: "Wrong deposit" });
  });

  it("counting a debt carries the choice and the reason", () => {
    expect(obligationRequest({ counts_toward_dti: false, reason: "Deferred" })).toEqual({ counts_toward_dti: false, reason: "Deferred" });
  });
});
