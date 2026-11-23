// Types for the Hardship and budget screen (Feature Design section 7).
//
// PROPOSAL, not generated: contracts/openapi.yaml has no hardship endpoints yet. The paths come from
// Feature Design 7.8 (POST /cases/{id}/hardship-assessment, GET .../latest, PUT .../latest/confirmations,
// PATCH .../latest/budget-items/{item}); the shapes follow 7.5 and 7.8. When Arindam adds the
// endpoints, replace this file with types generated from the contract.
//
// Every money figure and ratio is a string exactly as the backend calculated it ("-280.00", "40.95"),
// never a number, and every figure carries its working and evidence (CLAUDE.md rules 1 and 2).
import type { WorkingStep } from "@/components/shared/show-working-drawer";
import type { EvidenceLink } from "./income-types";

/** One line of the hardship letter, with the line ID that evidence links point at (e.g. "p1-L6"). */
export interface LetterLine {
  id: string;
  text: string;
}

export interface HardshipLetter {
  /** The letter's document, or an empty string when the backend did not say which one it is. */
  document_id: string;
  lines: LetterLine[];
  /**
   * True when `lines` holds only the quoted lines because the backend does not return the whole
   * letter yet. The screen says so instead of pretending it is the full letter.
   */
  partial?: boolean;
}

export type ProfileKey = "primary_reason" | "onset" | "duration" | "intent";

/** The allowed answers for a judgement that comes from a fixed list. */
export interface ProfileOption {
  value: string;
  label: string;
}

/** A short exact piece of the letter and the lines it was found on. The backend checks it in code. */
export interface ProfileQuote {
  text: string;
  line_ids: string[];
}

/** A specialist's decision on one profile item. Corrections keep what was originally read (rule 6). */
export interface ProfileReview {
  status: "confirmed" | "corrected";
  /** Required for a correction. */
  reason: string | null;
  by: string;
  at: string;
  /** What the letter reading said before any correction. */
  original_label: string;
}

export interface ProfileItem {
  key: ProfileKey;
  /** "Primary reason", "Onset", "Duration", "Intent". */
  label: string;
  /** The category or month as stored, e.g. "reduction_in_income" or "2026-07". */
  value: string;
  /** What the screen shows, e.g. "Reduction in income". */
  value_label: string;
  quote: ProfileQuote | null;
  /** True when the quote is an exact piece of its cited lines (checked in code). */
  quote_verified: boolean;
  /** The allowed values, or null when the answer is typed (the onset, a month written YYYY-MM). */
  options: ProfileOption[] | null;
  review: ProfileReview | null;
}

/** One side of a comparison: what was said or found, and where. */
export interface ConsistencySide {
  value: string;
  source: EvidenceLink;
}

/** Stated against documented, with both values shown (Feature Design 7.2 step 2). */
export interface ConsistencyCheck {
  id: string;
  label: string;
  stated: ConsistencySide;
  documented: ConsistencySide;
  status: "consistent" | "flagged";
  detail: string;
}

/** A person's change to what is counted for one expense. The observed amount it replaced is kept. */
export interface BudgetAdjustment {
  original_observed: string;
  reason: string;
  by: string;
  at: string;
}

export interface BudgetLine {
  id: string;
  category: string;
  stated: string;
  /** What the documents show, or the amount a person set (see `adjustment`). */
  observed: string;
  /** observed minus stated, e.g. "210.00" or "-5.00". */
  difference: string;
  /**
   * True when `difference` has no sign (the real backend sends the gap as a positive amount). The
   * screen then shows it as it came and does not add a plus sign it cannot know is right.
   */
  difference_unsigned?: boolean;
  flagged: boolean;
  /** A template sentence, e.g. "Observed 'other' spending 410.00 against 200.00 stated — ask the borrower". */
  flag_message: string | null;
  adjustment: BudgetAdjustment | null;
  evidence: EvidenceLink[];
}

export interface Budget {
  lines: BudgetLine[];
  stated_total: string;
  observed_total: string;
  /** Where the observed amounts come from, in a sentence. */
  observed_basis: string;
}

export type MeasureUnit = "money" | "percent";

/** One affordability measure: a figure with its working. */
export interface Measure {
  id: string;
  label: string;
  value: string;
  unit: MeasureUnit;
  /** A second figure to show beside it, e.g. the stated surplus or the ratio before the cut. */
  compare: { label: string; value: string; unit: MeasureUnit } | null;
  /** A short sentence from the backend, e.g. "12.41% of arrears". */
  note: string | null;
  flagged: boolean;
  flag_message: string | null;
  working: WorkingStep[];
  evidence: EvidenceLink[];
}

export interface HardshipAssessment {
  id: string;
  case_id: string;
  run_at: string;
  /** The tolerances and categories come from configuration, labelled illustrative or authoritative. */
  settings_label: "illustrative" | "authoritative";
  letter: HardshipLetter;
  profile: ProfileItem[];
  checks: ConsistencyCheck[];
  budget: Budget;
  measures: Measure[];
}

/**
 * Body of PUT /cases/{id}/hardship-assessment/latest/confirmations: confirm what the letter reading
 * said, or correct it. A correction needs both the new value and a reason.
 */
export interface ProfileConfirmation {
  key: ProfileKey;
  action: "confirm" | "correct";
  value?: string;
  reason?: string;
}

/**
 * Body of PATCH /cases/{id}/hardship-assessment/latest/budget-items/{item}: set how much of an
 * expense counts each month (for example, marking a one-off spend). The reason is required.
 */
export interface BudgetAdjustmentRequest {
  amount: string;
  reason: string;
}
