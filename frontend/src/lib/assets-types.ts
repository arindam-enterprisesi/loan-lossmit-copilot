// Types for the Assets and liabilities screen (Feature Design section 3).
//
// These are the shapes the screen uses. contracts/openapi.yaml has no entries for these endpoints
// yet (Abhay's router, backend/app/api/routers/asset_liability.py, follows Feature Design 3.7 and
// docs/contract-proposal-d4.md). The real answer has its own shape, which assets-real.ts translates
// into these, so the screen sees one shape in demo and real mode.
//
// Every money figure and ratio is a string exactly as the backend calculated it ("9226.32", "44.70"),
// never a number, and every figure carries its working and evidence (CLAUDE.md rules 1 and 2).
import type { WorkingStep } from "@/components/shared/show-working-drawer";
import type { EvidenceLink } from "./income-types";
import type { Severity } from "./types";

/** The sample loan, entered by hand. Nothing is priced (Feature Design 3.3). All amounts are text. */
export interface LoanScenario {
  purpose: string;
  occupancy: string;
  property_value: string;
  loan_amount: string;
  proposed_housing_payment: string;
  funds_to_close: string;
  /** When it was last saved, or null if it never was. */
  updated_at: string | null;
}

/** What a person types into the form. Same fields, none of the ones the backend fills in. */
export type LoanScenarioInput = Omit<LoanScenario, "updated_at">;

export type FigureUnit = "money" | "percent";

/** One calculated figure with the steps that produced it. */
export interface AssetFigure {
  /** Unformatted, e.g. "9226.32" or "44.70" for a percentage. */
  value: string;
  unit: FigureUnit;
  working: WorkingStep[];
  evidence: EvidenceLink[];
}

/** The categories a bank line can have (Feature Design 3.5). */
export type TransactionCategory =
  | "payroll deposit"
  | "other income deposit"
  | "transfer in"
  | "transfer out"
  | "housing payment"
  | "loan payment"
  | "credit card payment"
  | "utility"
  | "insurance"
  | "everyday spending"
  | "overdraft or returned-item fee"
  | "other fee"
  | "refund"
  | "other";

/** A person's change to what the system decided. The system's own answer is kept beside it (rule 6). */
export interface AssetChange {
  reason: string;
  by: string;
  at: string;
}

export interface TransactionFlag {
  code: string;
  severity: Severity;
  message: string;
}

export interface AssetTransaction {
  id: string;
  document_id: string;
  /** The statement line, e.g. "p2-L14". */
  line_id: string;
  /** The last four digits of the account the line is on. */
  account_last4: string | null;
  /** ISO date. */
  posted_on: string;
  description: string;
  /** Signed as the bank shows it: "-1425.00" for money out, "2033.61" for money in. */
  amount: string;
  direction: "credit" | "debit";
  category: TransactionCategory;
  /** Who chose the category now shown: the model ("ai") or a person ("user"). */
  category_source: "ai" | "user";
  /** What the system labelled it, which never changes. */
  system_category: TransactionCategory;
  counterparty: string | null;
  /** The model could not label it with confidence. */
  needs_review: boolean;
  /** A person marked this deposit as sourced. */
  sourced: boolean;
  sourced_note: string | null;
  change: AssetChange | null;
  /** The backend's working when the deposit matches a pay stub, e.g. "2,033.61 matches the 4 Sep pay date". */
  payroll_match: string | null;
  flags: TransactionFlag[];
}

export type ObligationSource = "bank" | "credit_report" | "both";

export interface AssetObligation {
  id: string;
  creditor: string;
  /** "auto loan", "credit card", "rent", "student loan". */
  kind: string;
  monthly_payment: string;
  balance: string | null;
  source: ObligationSource;
  /** Counts toward the DTI right now (the system's answer, or the person's change). */
  counts_toward_dti: boolean;
  /** What the settings decided on their own. Never changes. */
  system_counts_toward_dti: boolean;
  /** Why the system decided that. */
  reason: string;
  change: AssetChange | null;
}

export interface AssetFlag {
  code: string;
  severity: Severity;
  message: string;
  /** "open", or "resolved" once a person dealt with it (for example a deposit marked as sourced). */
  status: string;
  working: string | null;
  evidence: EvidenceLink[];
}

/** A figure beyond the headline ones, e.g. "DTI if overtime were counted". */
export interface OtherFigure {
  id: string;
  label: string;
  figure: AssetFigure;
}

export interface AssetAnalysis {
  id: string;
  case_id: string;
  run_at: string;
  settings_label: "illustrative" | "authoritative";
  /** "Candidate figures for the underwriter to review. They are not a decision." */
  note: string;
  // The headline figures. Null when the backend could not work one out (see `flags`, code AL-I101).
  documented_assets: AssetFigure | null;
  funds_to_close: AssetFigure | null;
  funds_shortfall: AssetFigure | null;
  monthly_obligations: AssetFigure | null;
  front_end_ratio: AssetFigure | null;
  dti: AssetFigure | null;
  ltv: AssetFigure | null;
  other_figures: OtherFigure[];
  obligations: AssetObligation[];
  transactions: AssetTransaction[];
  flags: AssetFlag[];
}

/**
 * Body of PATCH .../asset-liability/latest/transactions/{id}: give a line another category, or mark a
 * deposit as sourced. Exactly one of `category` and `sourced`, and a reason (required).
 */
export interface TransactionReview {
  category?: TransactionCategory;
  sourced?: boolean;
  reason: string;
}

/** Body of PATCH .../asset-liability/latest/obligations/{id}: count a debt toward the DTI or leave it out. */
export interface ObligationReview {
  counts_toward_dti: boolean;
  reason: string;
}
