import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-error";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import { queryAudit, seedAudit, type MockAuditEvent } from "./audit";
import {
  addAnnotationMock,
  addConditionMock,
  adjustBudgetItemMock,
  confirmProfileItemMock,
  decideConditionMock,
  getLatestAssetsMock,
  listAuditMock,
  overrideCompletenessItemMock,
  overrideConditionMock,
  resetMockStore,
  reviewFieldMock,
  runAssetsMock,
  runCompletenessMock,
  runCopilotMock,
  runHardshipMock,
  runIncomeMock,
  setDocumentTypeMock,
  setIncomeComponentMock,
  signOffMock,
  uploadMock,
  getLatestIncomeMock,
  getLatestHardshipMock,
  getJobMock,
  reviewObligationMock,
  reviewTransactionMock,
} from "./store";
import { PAYSTUB_DOC_ID } from "./extraction";

beforeEach(() => resetMockStore());

const thrown = (fn: () => unknown): ApiError => {
  try {
    fn();
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected an error");
};

describe("the seeded audit trail", () => {
  it("numbers events from 1, in time order, for both cases, with the correction on Daniel's pay stub", () => {
    const seed = seedAudit();
    expect(seed.map((e) => e.id)).toEqual(seed.map((_, i) => i + 1));
    expect(new Set(seed.map((e) => e.case_id))).toEqual(new Set([DANIEL_CASE_ID, ANGELA_CASE_ID]));
    const fix = seed.find((e) => e.action === "field.corrected")!;
    expect(fix).toMatchObject({ case_id: DANIEL_CASE_ID, entity_id: PAYSTUB_DOC_ID, actor_name: "demo.reviewer", role: "underwriter" });
    expect(fix.before).toMatchObject({ value: "2083.61" });
    expect(fix.after).toMatchObject({ value: "2033.61" });
    expect(fix.reason).toMatch(/gross minus deductions/);
  });

  it("has automatic steps with no person behind them", () => {
    const auto = seedAudit().filter((e) => e.action === "document.classified");
    expect(auto.length).toBeGreaterThan(0);
    for (const e of auto) expect(e).toMatchObject({ actor_name: null, role: "system" });
  });
});

describe("listing the trail", () => {
  const events = (): MockAuditEvent[] => {
    const base = seedAudit().find((e) => e.case_id === DANIEL_CASE_ID)!;
    return Array.from({ length: 7 }, (_, i) => ({ ...base, id: i + 1, action: i % 2 ? "field.corrected" : "document.uploaded", entity_type: i % 2 ? "field" : "document" }));
  };

  it("lists one case's events newest first, without the case id", () => {
    const page = queryAudit(seedAudit(), DANIEL_CASE_ID);
    expect(page.items.map((e) => e.id)).toEqual([...page.items.map((e) => e.id)].sort((a, b) => b - a));
    expect(page.items.every((e) => !("case_id" in e))).toBe(true);
    expect(page.next_before).toBeNull();
    expect(queryAudit(seedAudit(), "no-such-case").items).toEqual([]);
  });

  it("filters by exact action and by entity type", () => {
    const all = events();
    expect(queryAudit(all, DANIEL_CASE_ID, { action: "field.corrected" }).items.map((e) => e.id)).toEqual([6, 4, 2]);
    expect(queryAudit(all, DANIEL_CASE_ID, { entity_type: "document" }).items.map((e) => e.id)).toEqual([7, 5, 3, 1]);
    expect(queryAudit(all, DANIEL_CASE_ID, { action: "field", entity_type: "field" }).items).toEqual([]); // exact match only
  });

  it("pages back with `before`, and says when it has reached the end", () => {
    const all = events();
    const first = queryAudit(all, DANIEL_CASE_ID, { limit: 3 });
    expect(first.items.map((e) => e.id)).toEqual([7, 6, 5]);
    expect(first.next_before).toBe(5);
    const second = queryAudit(all, DANIEL_CASE_ID, { limit: 3, before: first.next_before! });
    expect(second.items.map((e) => e.id)).toEqual([4, 3, 2]);
    const last = queryAudit(all, DANIEL_CASE_ID, { limit: 3, before: second.next_before! });
    expect(last.items.map((e) => e.id)).toEqual([1]);
    expect(last.next_before).toBeNull();
  });

  it("refuses a page size outside 1 to 200 (422)", () => {
    expect(thrown(() => queryAudit(events(), DANIEL_CASE_ID, { limit: 0 })).status).toBe(422);
    expect(thrown(() => queryAudit(events(), DANIEL_CASE_ID, { limit: 201 })).status).toBe(422);
  });
});

const newest = (caseId: string, n = 1) => listAuditMock(caseId, { limit: n }).items;

describe("review actions are added to the trail as they happen", () => {
  it("records a condition decision with the before and after, the reason and who", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    decideConditionMock(DANIEL_CASE_ID, "uwc-3", { decision: "rejected", reason: "Not needed" }, 10_000);
    expect(newest(DANIEL_CASE_ID)[0]).toMatchObject({
      action: "underwriting.condition_rejected",
      entity_type: "condition",
      entity_id: "uwc-3",
      actor_name: "demo.reviewer",
      role: "underwriter",
      before: { decision: "pending" },
      after: { decision: "rejected" },
      reason: "Not needed",
      at: new Date(10_000).toISOString(),
    });
  });

  it("records an added condition, a sign-off and its note", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    addConditionMock(DANIEL_CASE_ID, { text: "  Gift letter  ", priority: "attention" }, 10_000);
    signOffMock("underwriting", DANIEL_CASE_ID, "Reviewed", 11_000);
    const [signed, added] = newest(DANIEL_CASE_ID, 2);
    expect(added).toMatchObject({ action: "underwriting.condition_added", after: { text: "Gift letter", priority: "attention" } });
    expect(signed).toMatchObject({
      action: "report.signed_off",
      entity_type: "report",
      reason: "Reviewed",
      after: { report_status: "signed_off", report_version: 1, kind: "underwriting", statement: "Records a review. Not a decision." },
    });
  });

  it("records an override and a note on the recommendation under the loss mitigation role", () => {
    runCopilotMock("lm", ANGELA_CASE_ID, 0);
    runCopilotMock("lm", ANGELA_CASE_ID, 0);
    overrideConditionMock(ANGELA_CASE_ID, "loan_modification.intent", { status: "needs_confirmation", reason: "Not yet confirmed" }, 10_000);
    addAnnotationMock(ANGELA_CASE_ID, { section: "lender_view", text: "Check the value" }, 11_000);
    const [note, override] = newest(ANGELA_CASE_ID, 2);
    expect(override).toMatchObject({ action: "lm.condition_overridden", entity_type: "waterfall_condition", role: "lm_specialist", after: { status: "needs_confirmation" }, reason: "Not yet confirmed" });
    expect(note).toMatchObject({ action: "lm.annotation_added", entity_type: "annotation", after: { section: "lender_view", text: "Check the value" } });
  });

  it("does not record an action that was refused", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    const before = listAuditMock(DANIEL_CASE_ID).items.length;
    expect(() => decideConditionMock(DANIEL_CASE_ID, "uwc-3", { decision: "rejected" }, 10_000)).toThrow(); // no reason
    expect(listAuditMock(DANIEL_CASE_ID).items).toHaveLength(before);
  });

  it("records a field correction with the original value, an upload and a type change", () => {
    const { documents } = uploadMock(DANIEL_CASE_ID, ["gift-letter.pdf"], "auto", 5_000);
    setDocumentTypeMock(DANIEL_CASE_ID, documents[0].id, "bank_statement", "Looks like a statement", 6_000);
    reviewFieldMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "employer_name", { action: "correct", value: "Northwind Logistics LLC", reason: "Typo", expected_version: 1 }, 7_000);
    const [field, typeSet, upload] = newest(DANIEL_CASE_ID, 3);
    expect(upload).toMatchObject({ action: "document.uploaded", entity_id: documents[0].id, after: { file_name: "gift-letter.pdf" } });
    expect(typeSet).toMatchObject({ action: "document.type_set", before: { doc_type: null }, after: { doc_type: "bank_statement" }, reason: "Looks like a statement" });
    expect(field).toMatchObject({
      action: "field.corrected",
      before: { field: "employer_name", value: "Northwind Logistics Inc." },
      after: { field: "employer_name", value: "Northwind Logistics LLC", review_status: "corrected" },
      reason: "Typo",
    });
  });

  it("only ever adds: earlier events keep their numbers and content", () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    const before = listAuditMock(DANIEL_CASE_ID).items;
    decideConditionMock(DANIEL_CASE_ID, "uwc-1", { decision: "accepted" }, 10_000);
    decideConditionMock(DANIEL_CASE_ID, "uwc-1", { decision: "rejected", reason: "Changed my mind" }, 11_000);
    const after = listAuditMock(DANIEL_CASE_ID).items;
    expect(after.slice(-before.length)).toEqual(before);
    expect(after.map((e) => e.id)).toEqual([...after.map((e) => e.id)].sort((a, b) => b - a));
    expect(after).toHaveLength(before.length + 2);
  });
});

// The income, assets, hardship and completeness screens have their own tests. Here, only that each review action they
// offer leaves a record of itself.
describe("every other review action leaves a record", () => {
  const settle = (jobId: string) => getJobMock(jobId, Date.now() + 60_000);

  it("income: including or excluding a component", () => {
    const job = runIncomeMock(DANIEL_CASE_ID, 0);
    settle(job.id);
    const component = getLatestIncomeMock(DANIEL_CASE_ID).components[0].id;
    setIncomeComponentMock(DANIEL_CASE_ID, component, { included: false, reason: "Not documented long enough" }, 10_000);
    expect(newest(DANIEL_CASE_ID)[0]).toMatchObject({ action: "income.component_excluded", entity_type: "income_component", entity_id: component, after: { included: false }, reason: "Not documented long enough" });
    setIncomeComponentMock(DANIEL_CASE_ID, component, { included: true, reason: "Now documented" }, 11_000);
    expect(newest(DANIEL_CASE_ID)[0].action).toBe("income.component_included");
  });

  it("completeness: an override, with the reason", () => {
    const result = runCompletenessMock(ANGELA_CASE_ID, "pillar2-hardship@1", 0);
    const open = result.items.find((i) => i.status === "partial" || i.status === "missing")!;
    overrideCompletenessItemMock(ANGELA_CASE_ID, open.item_id, "Waived by the lender", 10_000);
    expect(newest(ANGELA_CASE_ID)[0]).toMatchObject({
      action: "completeness.item_overridden",
      entity_type: "completeness_item",
      entity_id: open.item_id,
      role: "lm_specialist",
      reason: "Waived by the lender",
    });
  });

  it("assets: a reclassified deposit and a debt left out of the DTI", () => {
    const job = runAssetsMock(DANIEL_CASE_ID, 0);
    settle(job.id);
    const analysis = getLatestAssetsMock(DANIEL_CASE_ID);
    const tx = analysis.transactions.find((t) => t.direction === "credit")!.id;
    reviewTransactionMock(DANIEL_CASE_ID, tx, { sourced: true, reason: "Payroll" }, 10_000);
    expect(newest(DANIEL_CASE_ID)[0]).toMatchObject({ action: "assets.deposit_sourced", entity_type: "transaction", entity_id: tx, after: { sourced: true }, reason: "Payroll" });
    const debt = analysis.obligations[0].id;
    reviewObligationMock(DANIEL_CASE_ID, debt, { counts_toward_dti: false, reason: "Paid off at closing" }, 11_000);
    expect(newest(DANIEL_CASE_ID)[0]).toMatchObject({ action: "assets.obligation_excluded", entity_type: "obligation", after: { counts_toward_dti: false } });
  });

  it("hardship: a confirmation and a budget adjustment, and a cleared one", () => {
    const job = runHardshipMock(ANGELA_CASE_ID, 0);
    settle(job.id);
    confirmProfileItemMock(ANGELA_CASE_ID, { key: "duration", action: "confirm", reason: "Spoke to the borrower" }, 10_000);
    expect(newest(ANGELA_CASE_ID)[0]).toMatchObject({ action: "hardship.confirmed", entity_type: "hardship_profile", role: "lm_specialist", reason: "Spoke to the borrower" });
    const item = getLatestHardshipMock(ANGELA_CASE_ID).budget.lines[0].id;
    adjustBudgetItemMock(ANGELA_CASE_ID, item, { amount: "10.00", reason: "One-off" }, 11_000);
    expect(newest(ANGELA_CASE_ID)[0]).toMatchObject({ action: "budget.line_adjusted", entity_type: "budget_line", entity_id: item, after: { amount: "10.00" } });
    adjustBudgetItemMock(ANGELA_CASE_ID, item, { amount: null, reason: "Counts again" }, 12_000);
    expect(newest(ANGELA_CASE_ID)[0].action).toBe("budget.adjustment_cleared");
  });
});

