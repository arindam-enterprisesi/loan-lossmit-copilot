// Mock completeness results, shaped like the CompletenessResult in contracts/openapi.yaml.
// Daniel's and Angela's answers are the ones in the scenario files ("expected.completeness") and in
// FSD section 7: Daniel's pay stubs cover 14 of 30 days and his 2024 W-2 and tax return are absent
// (the August bank statement is also short a page); Angela has no August bank statement. The mock only
// repeats those answers. Which item is satisfied, partial or missing is the backend's decision.
//
// What the mock does stand in for are two plain-code steps the backend does after a person overrides
// an item (FSD section 7: "Overrides count as satisfied"): the overall status and the outstanding
// list are worked out again from the items.
import { ApiError } from "@/lib/api-error";
import {
  CHECKLIST_BY_PILLAR,
  OVERRIDE_REASON_MAX,
  type ChecklistItem,
  type ChecklistResult,
} from "@/lib/completeness";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";

const DANIEL_CHECKLIST = CHECKLIST_BY_PILLAR.underwriting;
const ANGELA_CHECKLIST = CHECKLIST_BY_PILLAR["loss-mitigation"];

const D = (n: number) => `d1000000-0000-4000-8000-00000000000${n}`;
const A = (n: number) => `d2000000-0000-4000-8000-00000000000${n}`;

/** What to ask the borrower for, per item. The real backend writes the `outstanding` list itself. */
const REQUEST_TEXT: Record<string, string> = {
  pay_stubs_30_days: "Pay stubs for 16 more days (14 of 30 days found)",
  w2_two_years: "W-2 for 2024",
  tax_returns_two_years: "Form 1040 for 2024",
  bank_statements_2_months: "Page 3 of the August 2026 bank statement (the footer says Page 1 of 3, 2 pages uploaded)",
  "bank_statement_2026-08": "August 2026 bank statement",
};

const item = (
  item_id: string,
  label: string,
  status: ChecklistItem["status"],
  reason: string,
  document_ids: string[] = [],
): ChecklistItem => ({ item_id, label, status, reason, document_ids, override_reason: null });

function danielItems(): ChecklistItem[] {
  return [
    item("pay_stubs_30_days", "Pay stubs covering 30 days", "partial", "14 of 30 days of pay stubs found", [D(1)]),
    item("w2_two_years", "W-2s for the last two tax years", "partial", "W-2 found for 2025. 2024 is missing.", [D(3)]),
    item(
      "tax_returns_two_years",
      "Tax returns for the last two tax years",
      "partial",
      "Form 1040 found for 2025. 2024 is missing.",
    ),
    item(
      "bank_statements_2_months",
      "Bank statements covering 2 months",
      "partial",
      "September 2026 found. The August 2026 statement is incomplete: the footer says Page 1 of 3 but only 2 pages were uploaded.",
      [D(2)],
    ),
    item(
      "credit_report_120_days",
      "Credit report within 120 days",
      "satisfied",
      "Credit report found, dated within 120 days of the reference date (2 Nov 2026)",
    ),
  ];
}

function angelaItems(): ChecklistItem[] {
  return [
    item("signed_application", "Signed mortgage assistance application", "satisfied", "Signed application found", [A(1)]),
    item("hardship_letter", "Hardship letter", "satisfied", "Hardship letter found", [A(2)]),
    item("pay_stubs_30_days", "Pay stubs covering 30 days", "satisfied", "Pay stubs cover 30 days or more", [A(5)]),
    item(
      "bank_statement_2026-08",
      "Bank statements covering 2 months",
      "missing",
      "No bank statement found for August 2026. October 2026 was found.",
      [A(4)],
    ),
  ];
}

/** "incomplete" while any item is partly met or missing. Overridden items count as satisfied. */
export function overallFrom(items: ChecklistItem[]): ChecklistResult["overall_status"] {
  return items.some((i) => i.status === "partial" || i.status === "missing") ? "incomplete" : "complete";
}

/** What is still to be asked for, one line per item that is partly met or missing. */
export function outstandingFrom(items: ChecklistItem[]): string[] {
  return items
    .filter((i) => i.status === "partial" || i.status === "missing")
    .map((i) => REQUEST_TEXT[i.item_id] ?? `${i.label}: ${i.reason}`);
}

/** The checklist that applies to a case, or undefined when the mock has no documents for it. */
const checklistFor = (caseId: string): string | undefined =>
  caseId === DANIEL_CASE_ID ? DANIEL_CHECKLIST : caseId === ANGELA_CASE_ID ? ANGELA_CHECKLIST : undefined;

/** POST .../completeness: what the backend returns after running a checklist for one of the demo cases. */
export function buildCompleteness(caseId: string, checklistId: string, runAt: string, id: string): ChecklistResult {
  const applies = checklistFor(caseId);
  if (!applies) throw new ApiError(404, "Case not found");
  if (!Object.values(CHECKLIST_BY_PILLAR).includes(checklistId)) throw new ApiError(422, "Unknown checklist");
  if (checklistId !== applies) throw new ApiError(422, "This checklist does not apply to this case");
  const items = checklistId === DANIEL_CHECKLIST ? danielItems() : angelaItems();
  const [name, version] = checklistId.split("@");
  return {
    id,
    case_id: caseId,
    checklist_id: name,
    checklist_version: version,
    checklist_label: "illustrative",
    overall_status: overallFrom(items),
    items,
    outstanding: outstandingFrom(items),
    run_at: runAt,
  };
}

/**
 * PATCH .../completeness/items/{item_id}: records a person's override. The item's own answer is kept
 * (`reason` is unchanged and `original_status` is added); the status becomes "overridden"; the overall
 * status and the outstanding list are worked out again. Returns a new result, not a changed one.
 */
export function applyOverride(
  result: ChecklistResult,
  itemId: string,
  reason: string,
  by: string,
  at: string,
): ChecklistResult {
  const cleaned = reason?.trim();
  if (!cleaned) throw new ApiError(422, "A reason is required");
  if (cleaned.length > OVERRIDE_REASON_MAX) {
    throw new ApiError(422, `The reason can be at most ${OVERRIDE_REASON_MAX} characters`);
  }
  const target = result.items.find((i) => i.item_id === itemId);
  if (!target) throw new ApiError(404, "Checklist item not found");
  if (target.status !== "partial" && target.status !== "missing") {
    throw new ApiError(422, "Only an item that is partly met or missing can be overridden");
  }
  const items = result.items.map((i) =>
    i.item_id === itemId
      ? {
          ...i,
          status: "overridden" as const,
          override_reason: cleaned,
          original_status: target.status as "partial" | "missing",
          overridden_by: by,
          overridden_at: at,
        }
      : i,
  );
  return { ...result, items, overall_status: overallFrom(items), outstanding: outstandingFrom(items) };
}
