// Types and small display helpers for the Completeness panel (Feature Design 1.2 step 5, FSD section 7).
// The run and latest endpoints are in contracts/openapi.yaml and their shapes are generated into
// src/lib/types.ts. The override is not in the contract yet, so its path and the extra fields it
// needs are a proposal to Arindam (see overrideCompletenessItem in src/lib/api.ts).
//
// Nothing here decides a status. Code on the backend does that; the screen only shows it.
import type { ChipTone } from "@/components/shared/flag-chip";
import type { CompletenessItem, CompletenessResult } from "./types";

/**
 * A checklist item as the screen needs it. The first fields are the contract's. The last three are
 * proposed: when a person overrides an item, the status becomes "overridden", so the checklist's own
 * answer must travel with it (project rule 6: corrections never overwrite) and so must who and when.
 */
export type ChecklistItem = CompletenessItem & {
  /** What the checklist found before the override. Only set once the item is overridden. */
  original_status?: Exclude<CompletenessItem["status"], "overridden"> | null;
  overridden_by?: string | null;
  overridden_at?: string | null;
};

export type ChecklistResult = Omit<CompletenessResult, "items"> & { items: ChecklistItem[] };

/**
 * Which checklist each menu section runs. The ids are configuration on the backend
 * (backend/config); the one in the contract's example is "pillar1-wage-earner@1". The loss
 * mitigation id is my guess until Abhay confirms it.
 */
export const CHECKLIST_BY_PILLAR: Record<string, string> = {
  underwriting: "pillar1-wage-earner@1",
  "loss-mitigation": "pillar2-loss-mitigation@1",
};

/** The longest reason accepted when an item is overridden (same limit as other reasons). */
export const OVERRIDE_REASON_MAX = 500;

export const ITEM_STATUS_LABEL: Record<CompletenessItem["status"], string> = {
  satisfied: "Satisfied",
  partial: "Partially satisfied",
  missing: "Missing",
  overridden: "Overridden",
};

export const ITEM_STATUS_TONE: Record<CompletenessItem["status"], ChipTone> = {
  satisfied: "success",
  partial: "warning",
  missing: "danger",
  overridden: "info",
};

/** Only an item that is partly met or missing can be overridden. */
export function canOverride(item: ChecklistItem): boolean {
  return item.status === "partial" || item.status === "missing";
}

/** "Complete for this checklist" is the wording from the FSD: it is never a loan decision. */
export function overallLabel(status: ChecklistResult["overall_status"]): string {
  return status === "complete" ? "Complete for this checklist" : "Incomplete";
}

/** The text that "Copy outstanding items" puts on the clipboard. */
export function outstandingText(outstanding: string[]): string {
  if (outstanding.length === 0) return "";
  return ["Outstanding items for this case:", ...outstanding.map((o) => `- ${o}`)].join("\n");
}
