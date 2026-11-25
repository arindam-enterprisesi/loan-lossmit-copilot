import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import {
  applyObligationReview,
  applyTransactionReview,
  buildDanielAssets,
  checkScenario,
  DANIEL_SCENARIO,
  hasAssetSeed,
  type AssetRun,
} from "./assets";
import {
  getJobMock,
  getLatestAssetsMock,
  getLoanScenarioMock,
  JOB_QUEUE_MS,
  JOB_RUN_MS,
  putLoanScenarioMock,
  resetMockStore,
  reviewObligationMock,
  reviewTransactionMock,
  runAssetsMock,
  runIncomeMock,
} from "./store";

const AT = "2026-11-23T09:00:00.000Z";
const RUN: AssetRun = { scenario: DANIEL_SCENARIO, candidate_monthly: "5980.00", overtime_monthly: "444.41" };
const analysis = (run: AssetRun = RUN) => buildDanielAssets(run, AT);
const by = (a: ReturnType<typeof analysis>, name: string) => a.obligations.find((o) => o.creditor.startsWith(name))!;
const finish = (jobId: string) => getJobMock(jobId, Date.now() + JOB_QUEUE_MS + JOB_RUN_MS + 1);

describe("Daniel's mock asset analysis: the figures in the scenario file", () => {
  it("documented assets 9,226.32 against 36,500.00 needed, a shortfall of 27,273.68", () => {
    const a = analysis();
    expect(a.documented_assets?.value).toBe("9226.32");
    expect(a.funds_to_close?.value).toBe("36500.00");
    expect(a.funds_shortfall?.value).toBe("27273.68");
  });

  it("obligations 693.00 a month: 88 + 40 + 35 + 420 + 110, with the rent left out", () => {
    const a = analysis();
    expect(a.monthly_obligations?.value).toBe("693.00");
    expect(a.monthly_obligations?.working[0].formula).toBe("88.00 + 40.00 + 35.00 + 420.00 + 110.00");
    expect(a.obligations.filter((o) => o.counts_toward_dti).map((o) => o.creditor)).not.toContain("Oakmont Apartments");
  });

  it("front-end ratio 33.11%, DTI 44.70%, LTV 90.00%", () => {
    const a = analysis();
    expect([a.front_end_ratio?.value, a.dti?.value, a.ltv?.value]).toEqual(["33.11", "44.70", "90.00"]);
    expect([a.front_end_ratio?.unit, a.dti?.unit, a.ltv?.unit]).toEqual(["percent", "percent", "percent"]);
  });

  it("every figure carries its working and where it came from", () => {
    const a = analysis();
    for (const f of [a.documented_assets, a.funds_to_close, a.funds_shortfall, a.monthly_obligations, a.front_end_ratio, a.dti, a.ltv]) {
      expect(f!.working.length).toBeGreaterThan(0);
      expect(f!.evidence.length).toBeGreaterThan(0);
    }
    expect(a.dti?.working[0]).toMatchObject({
      formula: "(1,980.00 + 693.00) ÷ 5,980.00 × 100",
      result: "44.70%",
    });
    expect(a.documented_assets?.evidence[0].document_id).toBeTruthy(); // links to the statement
  });

  it("DTI would be 41.61% if overtime were counted, shown beside it for the underwriter to test", () => {
    const other = analysis().other_figures;
    expect(other).toHaveLength(1);
    expect(other[0]).toMatchObject({ id: "dti_with_overtime", label: "DTI if overtime were counted" });
    expect(other[0].figure.value).toBe("41.61");
    expect(other[0].figure.working[0].formula).toBe("(1,980.00 + 693.00) ÷ 6,424.41 × 100");
  });

  it("has no what-if when overtime is already counted", () => {
    expect(analysis({ ...RUN, candidate_monthly: "6424.41", overtime_monthly: null }).other_figures).toEqual([]);
  });

  it("says plainly that the figures are candidates, not a decision", () => {
    expect(analysis().note).toBe("Candidate figures for the underwriter to review. They are not a decision.");
    expect(analysis().settings_label).toBe("illustrative");
  });
});

describe("Daniel's mock asset analysis: transactions, flags and obligations", () => {
  it("lists the 30 lines of the September statement on the account ending 6032, in order", () => {
    const a = analysis();
    expect(a.transactions).toHaveLength(30);
    expect(new Set(a.transactions.map((t) => t.account_last4))).toEqual(new Set(["6032"]));
    expect(a.transactions[0]).toMatchObject({ description: "OAKMONT APARTMENTS RENT", amount: "-1425.00", direction: "debit", category: "housing payment" });
    expect(a.transactions[29].posted_on).toBe("2026-09-24");
  });

  it("both September paychecks of 2,033.61 match the pay stubs", () => {
    const matches = analysis().transactions.filter((t) => t.payroll_match);
    expect(matches.map((t) => [t.posted_on, t.amount])).toEqual([
      ["2026-09-04", "2033.61"],
      ["2026-09-18", "2033.61"],
    ]);
    expect(matches[0].payroll_match).toContain("2,033.61");
  });

  it("flags the 2,000.00 transfer from Patricia Owens as a large deposit, and nothing else", () => {
    const flagged = analysis().transactions.filter((t) => t.flags.length > 0);
    expect(flagged).toHaveLength(1);
    expect(flagged[0]).toMatchObject({ posted_on: "2026-09-22", amount: "2000.00", counterparty: "Patricia Owens" });
    expect(flagged[0].flags[0].message).toBe(
      "Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules.",
    );
  });

  it("raises the three flags: large deposit, the shortfall and DTI above the 43% review level", () => {
    const flags = analysis().flags;
    expect(flags.map((f) => f.code)).toEqual(["AL-W101", "AL-W105", "AL-W106"]);
    expect(flags[1].message).toBe("Documented assets of 9,226.32 are 27,273.68 short of the 36,500.00 needed to close.");
    expect(flags[2].message).toBe("DTI 44.70% is above the review level of 43%.");
    expect(flags.every((f) => f.status === "open")).toBe(true);
  });

  it("lists six obligations with their sources; the rent is left out and says why", () => {
    const a = analysis();
    expect(a.obligations).toHaveLength(6);
    expect(by(a, "Harbor").source).toBe("credit_report");
    expect(by(a, "Oakmont")).toMatchObject({ source: "bank", counts_toward_dti: false, kind: "rent", balance: null });
    expect(by(a, "Oakmont").reason).toBe("Current rent on a purchase of a primary residence.");
    expect(by(a, "Northgate").source).toBe("both");
    expect(a.obligations.every((o) => o.change === null && o.counts_toward_dti === o.system_counts_toward_dti)).toBe(true);
  });
});

describe("obligations: counting a debt in or out updates everything at once", () => {
  it("leaving out the student loan drops obligations to 583.00 and DTI to 42.86%, and clears the DTI flag", () => {
    const a = analysis();
    const next = applyObligationReview(a, RUN, by(a, "Brightpath").id, { counts_toward_dti: false, reason: "Deferred until 2027" }, "demo.reviewer", AT);
    expect(next.monthly_obligations?.value).toBe("583.00");
    expect(next.dti?.value).toBe("42.86");
    expect(next.flags.map((f) => f.code)).toEqual(["AL-W101", "AL-W105"]); // 42.86 is below 43
    expect(next.other_figures[0].figure.value).toBe("39.89"); // the what-if follows too: 2,563 / 6,424.41
  });

  it("counting the rent as well makes DTI 68.53% and raises the flag again", () => {
    const a = analysis();
    const next = applyObligationReview(a, RUN, by(a, "Oakmont").id, { counts_toward_dti: true, reason: "Keeping the apartment" }, "u", AT);
    expect(next.monthly_obligations?.value).toBe("2118.00");
    expect(next.dti?.value).toBe("68.53");
    expect(next.flags.map((f) => f.code)).toContain("AL-W106");
  });

  it("keeps who, when and why, and what the system decided, and leaves the front-end ratio alone", () => {
    const a = analysis();
    const next = applyObligationReview(a, RUN, by(a, "Brightpath").id, { counts_toward_dti: false, reason: "Deferred until 2027" }, "demo.reviewer", AT);
    expect(by(next, "Brightpath")).toMatchObject({
      counts_toward_dti: false,
      system_counts_toward_dti: true,
      change: { reason: "Deferred until 2027", by: "demo.reviewer", at: AT },
    });
    expect(next.front_end_ratio?.value).toBe("33.11");
    expect(next.ltv?.value).toBe("90.00");
    expect(a.dti?.value).toBe("44.70"); // the analysis it was given is not changed
  });

  it("refuses a missing, blank or too long reason (422) and an unknown obligation (404)", () => {
    const a = analysis();
    const id = by(a, "Brightpath").id;
    for (const reason of ["", "   ", "x".repeat(501)]) {
      expect(() => applyObligationReview(a, RUN, id, { counts_toward_dti: false, reason }, "u", AT)).toThrow(
        expect.objectContaining({ status: 422 }),
      );
    }
    expect(() => applyObligationReview(a, RUN, "nope", { counts_toward_dti: false, reason: "r" }, "u", AT)).toThrow(
      expect.objectContaining({ status: 404 }),
    );
  });

  it("a candidate income of zero leaves the ratios out rather than dividing by it", () => {
    const a = analysis({ ...RUN, candidate_monthly: "0.00" });
    expect(a.front_end_ratio).toBeNull();
    expect(a.dti).toBeNull();
    expect(a.ltv?.value).toBe("90.00");
    expect(a.flags.map((f) => f.code)).not.toContain("AL-W106");
  });
});

describe("transactions: reclassify, and mark a deposit as sourced", () => {
  const deposit = (a: ReturnType<typeof analysis>) => a.transactions.find((t) => t.amount === "2000.00")!;
  const target = (a: ReturnType<typeof analysis>) => a.transactions.find((t) => t.description === "TARGET T-1124")!;

  it("a new category replaces the chip, keeps the system's label, and records who, when and why", () => {
    const a = analysis();
    const next = applyTransactionReview(a, RUN, target(a).id, { category: "everyday spending", reason: "A grocery run" }, "demo.reviewer", AT);
    const t = next.transactions.find((x) => x.id === target(a).id)!;
    expect(t).toMatchObject({
      category: "everyday spending",
      category_source: "user",
      system_category: "other",
      change: { reason: "A grocery run", by: "demo.reviewer", at: AT },
    });
    expect(target(a).category).toBe("other"); // the analysis it was given is not changed
  });

  it("marking the deposit as sourced resolves its flag and keeps the note", () => {
    const a = analysis();
    const next = applyTransactionReview(a, RUN, deposit(a).id, { sourced: true, reason: "Gift from a relative, letter on file" }, "u", AT);
    expect(deposit(next)).toMatchObject({ sourced: true, sourced_note: "Gift from a relative, letter on file" });
    expect(next.flags.find((f) => f.code === "AL-W101")).toMatchObject({ status: "resolved" });
    expect(next.flags.find((f) => f.code === "AL-W101")?.working).toContain("Gift from a relative");
  });

  it("can be undone: unmarking brings the flag back open", () => {
    const a = analysis();
    const sourced = applyTransactionReview(a, RUN, deposit(a).id, { sourced: true, reason: "Gift" }, "u", AT);
    const undone = applyTransactionReview(sourced, RUN, deposit(a).id, { sourced: false, reason: "Letter was for another transfer" }, "u", AT);
    expect(deposit(undone)).toMatchObject({ sourced: false, sourced_note: null });
    expect(undone.flags.find((f) => f.code === "AL-W101")?.status).toBe("open");
  });

  it("does not change any headline figure", () => {
    const a = analysis();
    const next = applyTransactionReview(a, RUN, target(a).id, { category: "refund", reason: "r" }, "u", AT);
    expect(next.dti?.value).toBe(a.dti?.value);
    expect(next.documented_assets?.value).toBe(a.documented_assets?.value);
  });

  it("refuses: no reason, an unknown category, both or neither change, sourcing a payment, an unknown line", () => {
    const a = analysis();
    const id = target(a).id;
    const refused = (review: Parameters<typeof applyTransactionReview>[3], tid = id) =>
      expect(() => applyTransactionReview(a, RUN, tid, review, "u", AT));
    refused({ category: "refund", reason: "" }).toThrow(expect.objectContaining({ status: 422 }));
    refused({ category: "not a category" as never, reason: "r" }).toThrow(expect.objectContaining({ status: 422 }));
    refused({ reason: "r" }).toThrow(expect.objectContaining({ status: 422 }));
    refused({ category: "refund", sourced: true, reason: "r" }).toThrow(expect.objectContaining({ status: 422 }));
    refused({ sourced: true, reason: "r" }).toThrow(expect.objectContaining({ status: 422, message: "Only a deposit can be marked as sourced" }));
    refused({ category: "refund", reason: "r" }, "nope").toThrow(expect.objectContaining({ status: 404 }));
  });
});

describe("the loan scenario", () => {
  it("accepts Daniel's sample loan, and trims what was typed", () => {
    expect(checkScenario({ ...DANIEL_SCENARIO, purpose: " purchase " }).purpose).toBe("purchase");
  });

  it("refuses what the backend refuses: blanks, odd amounts, a property value of zero (422)", () => {
    const refused = (patch: Partial<typeof DANIEL_SCENARIO>) =>
      expect(() => checkScenario({ ...DANIEL_SCENARIO, ...patch })).toThrow(expect.objectContaining({ status: 422 }));
    refused({ purpose: "  " });
    refused({ occupancy: "" });
    refused({ property_value: "0.00" });
    refused({ property_value: "lots" });
    refused({ loan_amount: "-5" });
    refused({ funds_to_close: "36500.123" });
    expect(() => checkScenario({ ...DANIEL_SCENARIO, loan_amount: "0" })).not.toThrow(); // zero is allowed there
  });

  it("only Daniel's case has statements to analyse", () => {
    expect(hasAssetSeed(DANIEL_CASE_ID)).toBe(true);
    expect(hasAssetSeed(ANGELA_CASE_ID)).toBe(false);
  });
});

describe("the mock store: scenario, run, read, review", () => {
  beforeEach(() => resetMockStore());

  it("starts with Daniel's sample loan already entered, and no analysis", () => {
    expect(getLoanScenarioMock(DANIEL_CASE_ID)).toMatchObject({ purpose: "purchase", loan_amount: "360000.00" });
    expect(() => getLatestAssetsMock(DANIEL_CASE_ID)).toThrow(expect.objectContaining({ status: 404 }));
  });

  it("has no scenario for a case that has none", () => {
    expect(() => getLoanScenarioMock(ANGELA_CASE_ID)).toThrow(expect.objectContaining({ status: 404 }));
  });

  it("saving the scenario keeps it, with the time it was saved", () => {
    const saved = putLoanScenarioMock(DANIEL_CASE_ID, { ...DANIEL_SCENARIO, proposed_housing_payment: "2100.00" }, Date.parse(AT));
    expect(saved).toMatchObject({ proposed_housing_payment: "2100.00", updated_at: AT });
    expect(getLoanScenarioMock(DANIEL_CASE_ID).proposed_housing_payment).toBe("2100.00");
  });

  it("refuses an acceptable-looking scenario only when it breaks a rule (422), and a case with no statements (404)", () => {
    expect(() => putLoanScenarioMock(DANIEL_CASE_ID, { ...DANIEL_SCENARIO, property_value: "0" })).toThrow(expect.objectContaining({ status: 422 }));
    expect(() => putLoanScenarioMock(ANGELA_CASE_ID, DANIEL_SCENARIO)).toThrow(expect.objectContaining({ status: 404 }));
  });

  it("a run queues, finishes, and leaves the latest analysis to read: DTI 44.70%", () => {
    const job = runAssetsMock(DANIEL_CASE_ID);
    expect(job).toMatchObject({ kind: "asset_analysis", status: "queued" });
    finish(job.id);
    expect(getLatestAssetsMock(DANIEL_CASE_ID).dti?.value).toBe("44.70");
  });

  it("a changed scenario changes the next run: a 2,100.00 housing payment gives a front-end ratio of 35.12%", () => {
    putLoanScenarioMock(DANIEL_CASE_ID, { ...DANIEL_SCENARIO, proposed_housing_payment: "2100.00" });
    finish(runAssetsMock(DANIEL_CASE_ID).id);
    expect(getLatestAssetsMock(DANIEL_CASE_ID).front_end_ratio?.value).toBe("35.12");
  });

  it("uses the candidate income from the income analysis when there is one", () => {
    // Overtime counted in the income analysis would make 6,424.41, so the DTI is the 41.61% case.
    const incomeJob = runIncomeMock(DANIEL_CASE_ID);
    getJobMock(incomeJob.id, Date.now() + JOB_QUEUE_MS + JOB_RUN_MS + 1);
    const withIncome = (finish(runAssetsMock(DANIEL_CASE_ID).id), getLatestAssetsMock(DANIEL_CASE_ID));
    expect(withIncome.dti?.value).toBe("44.70"); // overtime is left out by the method, so 5,980.00 stands
    expect(withIncome.other_figures[0].figure.value).toBe("41.61");
  });

  it("refuses a run for a case with no statements (422)", () => {
    expect(() => runAssetsMock(ANGELA_CASE_ID)).toThrow(expect.objectContaining({ status: 422 }));
  });

  it("reviews change the latest analysis, which is still there when read again", () => {
    finish(runAssetsMock(DANIEL_CASE_ID).id);
    const before = getLatestAssetsMock(DANIEL_CASE_ID);
    const brightpath = before.obligations.find((o) => o.creditor.startsWith("Brightpath"))!;
    const after = reviewObligationMock(DANIEL_CASE_ID, brightpath.id, { counts_toward_dti: false, reason: "Deferred" });
    expect(after.dti?.value).toBe("42.86");
    expect(getLatestAssetsMock(DANIEL_CASE_ID).dti?.value).toBe("42.86");

    const deposit = after.transactions.find((t) => t.amount === "2000.00")!;
    const sourced = reviewTransactionMock(DANIEL_CASE_ID, deposit.id, { sourced: true, reason: "Gift" });
    expect(sourced.flags.find((f) => f.code === "AL-W101")?.status).toBe("resolved");
    expect(sourced.dti?.value).toBe("42.86"); // the earlier change is kept
  });

  it("reviewing before any run is a 404", () => {
    expect(() => reviewObligationMock(DANIEL_CASE_ID, "x", { counts_toward_dti: true, reason: "r" })).toThrow(expect.objectContaining({ status: 404 }));
    expect(() => reviewTransactionMock(DANIEL_CASE_ID, "x", { sourced: true, reason: "r" })).toThrow(expect.objectContaining({ status: 404 }));
  });
});
