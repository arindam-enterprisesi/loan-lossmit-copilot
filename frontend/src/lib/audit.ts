// Display helpers for the HITL actions screen. Words and grouping only: nothing here changes or works out a
// value (CLAUDE.md rule 1), and an event is shown as the backend recorded it.
import type { AuditEvent } from "./audit-types";
import { humanize } from "./format";

/** What each action the backend records means, in the words a reviewer uses. */
export const ACTION_LABEL: Record<string, string> = {
  "case.created": "Case created",
  "case.profile_updated": "Case profile updated",
  "loan_scenario.entered": "Loan scenario entered",
  "loan_scenario.replaced": "Loan scenario replaced",
  "document.uploaded": "Document uploaded",
  "document.ingested": "Document read",
  "document.ingest_failed": "Document could not be read",
  "document.classified": "Document type found",
  "document.extracted": "Values extracted",
  "document.validated": "Checks run on a document",
  "document.type_set": "Document type set",
  "field.confirmed": "Value confirmed",
  "field.corrected": "Value corrected",
  "field.rejected": "Value rejected",
  "completeness.run": "Checklist run",
  "completeness.item_overridden": "Checklist item overridden",
  "completeness.override_cleared": "Checklist override cleared",
  "income.run_requested": "Income analysis requested",
  "income.analysed": "Income analysed",
  "income.component_included": "Income included",
  "income.component_excluded": "Income excluded",
  "assets.run_requested": "Assets analysis requested",
  "assets.analysed": "Assets analysed",
  "assets.transaction_reclassified": "Transaction reclassified",
  "assets.deposit_sourced": "Deposit marked sourced",
  "assets.deposit_unsourced": "Deposit marked not sourced",
  "assets.obligation_included": "Debt counted in the DTI",
  "assets.obligation_excluded": "Debt left out of the DTI",
  "hardship.reading_requested": "Hardship letter reading requested",
  "hardship.profile_stored": "Hardship letter read",
  "hardship.confirmed": "Hardship item confirmed or corrected",
  "budget.line_adjusted": "Budget line adjusted",
  "budget.adjustment_cleared": "Budget adjustment cleared",
  "underwriting.condition_accepted": "Condition accepted",
  "underwriting.condition_edited": "Condition edited",
  "underwriting.condition_rejected": "Condition rejected",
  "underwriting.condition_added": "Condition added",
  "lm.condition_overridden": "Waterfall condition overridden",
  "lm.condition_override_removed": "Waterfall override removed",
  "lm.annotation_added": "Note added to the recommendation",
  "report.signed_off": "Review signed off",
};

export const ENTITY_LABEL: Record<string, string> = {
  case: "Case",
  loan_scenario: "Loan scenario",
  document: "Document",
  field: "Extracted value",
  completeness_item: "Checklist item",
  analysis_run: "Analysis run",
  income_component: "Income component",
  income_check: "Income check",
  transaction: "Transaction",
  obligation: "Debt",
  hardship_profile: "Hardship profile",
  hardship_item: "Hardship item",
  budget_line: "Budget line",
  condition: "Suggested condition",
  waterfall_condition: "Waterfall condition",
  annotation: "Note",
  report: "Report",
  job: "Job",
};

export const actionLabel = (action: string): string => ACTION_LABEL[action] ?? humanize(action.replace(/[._]/g, " "));
export const entityLabel = (entityType: string): string => ENTITY_LABEL[entityType] ?? humanize(entityType);

/**
 * Steps the system takes by itself, and requests to run one. They are in the trail, but they are not review
 * actions: nobody looked at a result and changed or confirmed it.
 */
export const AUTOMATIC_ACTIONS = new Set([
  "document.ingested",
  "document.ingest_failed",
  "document.classified",
  "document.extracted",
  "document.validated",
  "completeness.run",
  "income.run_requested",
  "income.analysed",
  "assets.run_requested",
  "assets.analysed",
  "hardship.reading_requested",
  "hardship.profile_stored",
]);

/** A person looked at something and acted on it: confirmed, corrected, overrode, decided, signed off. */
export const isReviewAction = (action: string): boolean => !AUTOMATIC_ACTIONS.has(action);

/** What the Action filter offers, in the order a case usually goes through them. */
export const ACTION_FILTER_OPTIONS: string[] = Object.keys(ACTION_LABEL);
export const ENTITY_FILTER_OPTIONS: string[] = Object.keys(ENTITY_LABEL);

/** "System" for something with no person behind it. */
export const actorLabel = (e: AuditEvent): string => e.actor_name ?? "System";

export const ROLE_LABEL_SHORT: Record<string, string> = {
  underwriter: "Underwriter",
  lm_specialist: "Loss mitigation specialist",
  admin: "Administrator",
  system: "System",
};
export const roleLabel = (role: string): string => ROLE_LABEL_SHORT[role] ?? humanize(role);

// ---- What changed -----------------------------------------------------------------------------------

export interface ChangedValue {
  key: string;
  before: string;
  after: string;
}

const SHOWN_MAX = 120;

/** A value as plain text. Nothing is parsed or rounded; objects are shown as JSON and cut when long. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const json = JSON.stringify(value);
  return json.length > SHOWN_MAX ? `${json.slice(0, SHOWN_MAX - 1)}…` : json;
}

/** The keys whose value differs between "before" and "after", each as before and after text, in the order the backend wrote them. */
export function changedValues(before: Record<string, unknown> | null, after: Record<string, unknown> | null): ChangedValue[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];
  return keys
    .filter((k) => JSON.stringify(before?.[k] ?? null) !== JSON.stringify(after?.[k] ?? null))
    .map((key) => ({ key: humanize(key), before: valueText(before?.[key]), after: valueText(after?.[key]) }));
}

/** Pages of events put together and kept newest first, dropping any event already shown. */
export function mergePages(shown: AuditEvent[], more: AuditEvent[]): AuditEvent[] {
  const seen = new Set(shown.map((e) => e.id));
  return [...shown, ...more.filter((e) => !seen.has(e.id))].sort((a, b) => b.id - a.id);
}
