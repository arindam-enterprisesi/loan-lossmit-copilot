// Types for the Income analysis screen (Feature Design section 2).
//
// PROPOSAL, not generated: contracts/openapi.yaml only has a TODO for the income endpoints
// (POST /cases/{id}/income/analysis, GET .../latest, PATCH components). These shapes follow Feature
// Design 2.2 and the income-explain@1 schema (backend/app/prompts/schemas/income.py). When Arindam
// adds the endpoints, replace this file with types generated from the contract.
//
// Every money figure is a string exactly as the backend calculated it ("5980.00"), never a number,
// and every figure carries its working and evidence (CLAUDE.md rules 1 and 2).
import type { WorkingStep } from "@/components/shared/show-working-drawer";
import type { Severity } from "./types";

/** Where a value came from: a document line, shown as a link on the screen. */
export interface EvidenceLink {
  label: string;
  document_id?: string;
  page?: number;
  line_ids?: string[];
}

/** One calculated figure with the steps that produced it. */
export interface IncomeFigure {
  /** Unformatted, e.g. "5980.00". */
  value: string;
  working: WorkingStep[];
  evidence: EvidenceLink[];
}

export type IncomeComponentKind = "base_pay" | "overtime" | "bonus" | "commission" | "other";

/** A person's include or exclude decision on a component. The reason is required. */
export interface IncomeOverride {
  included: boolean;
  reason: string;
  by: string;
  at: string;
}

export interface IncomeComponent {
  id: string;
  kind: IncomeComponentKind;
  label: string;
  current_period: IncomeFigure | null;
  year_to_date: IncomeFigure | null;
  monthly: IncomeFigure;
  /** Counted in the candidate monthly income right now (the rule's answer, or the person's override). */
  included: boolean;
  /** What the configured method decided on its own. Never changes, so the original answer stays visible. */
  rule_included: boolean;
  /** Why the configured method leaves it out, when it does. */
  rule_note: string | null;
  /** The person's latest decision, when they changed what the rule said. Null means the rule's answer stands. */
  override: IncomeOverride | null;
}

/**
 * Body of PATCH /cases/{id}/income/analysis/components/{component_id}: include or exclude one
 * component. The reason is required and the backend answers 422 without it.
 */
export interface IncomeDecision {
  included: boolean;
  reason: string;
}

/** One side of a flag: a value and where it came from. */
export interface FlagValue {
  label: string;
  value: string;
  source: EvidenceLink;
}

/** An AI suggestion for a flag. Always labelled as possible, never as a finding. */
export interface IncomeExplanation {
  text: string;
  /** Always "possible — to be confirmed" (the backend's constant). */
  label: string;
  evidence_refs: string[];
  suggested_documents: string[];
  /** False when a figure in the text did not match its inputs: shown as "unverified figure". */
  figures_verified: boolean;
}

export interface IncomeFlag {
  code: string;
  severity: Severity;
  message: string;
  /** Both sides of the comparison, shown side by side. */
  values: FlagValue[];
  explanations: IncomeExplanation[];
}

/** One cross-document comparison from Feature Design 2.5: wages, employer, deferrals, trend. */
export interface IncomeCheck {
  id: string;
  label: string;
  status: "passed" | "flagged";
  detail: string;
}

export interface IncomeAnalysis {
  id: string;
  case_id: string;
  run_at: string;
  method_version: string;
  method_label: "illustrative" | "authoritative";
  components: IncomeComponent[];
  /** Sum of the included components' monthly figures. A candidate: a person decides what counts as qualifying income. */
  candidate_monthly: IncomeFigure;
  /** Sentences built from the numbers by a template (no AI). */
  trend: string[];
  checks: IncomeCheck[];
  flags: IncomeFlag[];
  /** Documents that would settle the flags, collected from the explanations, ready to copy. */
  document_requests: string[];
}
