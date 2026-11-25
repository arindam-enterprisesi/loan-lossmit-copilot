// Types for the two agent screens: the Underwriting copilot (Feature Design 6) and the Loss Mitigation
// recommendation (Feature Design 8).
//
// The read and review side of both is on `main` (backend/app/api/routers/underwriting.py and
// lm_recommendation.py, shapes in backend/app/api/schemas/reports.py), but not in contracts/openapi.yaml.
// Starting a run and re-running one agent are Arindam's and are not on `main` yet. These types follow the
// backend's own shapes where they exist (see copilot-real.ts for the translation), and are my proposal for
// the rest. Only the mock changes a status or works out a figure: the screens show what they are given.
//
// Nothing here decides anything. A report is a draft until a person reviews it, and a sign-off records
// that a review happened: it is never a decision (CLAUDE.md rule 3).

/** Review order for findings and conditions. It says what to look at first and nothing about the loan. */
export type Priority = "significant" | "attention" | "information";

export type AgentName = "researcher" | "writer" | "critic";

/** The backend's "queued" is shown as waiting and its "succeeded" as done. */
export type AgentStatus = "waiting" | "running" | "done" | "failed";

export interface AgentRun {
  agent: AgentName;
  /** 1 for the first try; goes up each time the agent is re-run. */
  attempt: number;
  status: AgentStatus;
  /** One line on what the agent did. The backend does not promise it. */
  summary: string | null;
  /** Why it failed, when it did. */
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** What a finding, a conflict or a condition came from. `id` is the calculation name, rule ID, checklist item, document or passage. */
export type EvidenceKind = "calculation" | "rule" | "checklist" | "document" | "passage";

export interface EvidenceRef {
  kind: EvidenceKind;
  id: string;
  /** For a document reference: the lines it came from. */
  line_ids?: string[];
}

export interface Finding {
  id: string;
  priority: Priority;
  title: string;
  detail: string;
  evidence: EvidenceRef[];
}

/** Two findings that point different ways, shown openly. `figures` are the values to set side by side, when the sender gives them. */
export interface Conflict {
  title: string;
  detail: string;
  evidence: EvidenceRef[];
  figures?: { label: string; value: string }[];
}

export type ConditionDecision = "pending" | "accepted" | "edited" | "rejected";

export interface Condition {
  id: string;
  position: number;
  /** What the agents (or the reviewer, for their own) wrote. Never changed. */
  text: string;
  priority: Priority;
  source: "agent" | "user";
  decision: ConditionDecision;
  /** The reviewer's version, kept beside the original. */
  edited_text: string | null;
  /** The text to show: the reviewer's edit when there is one. */
  current_text: string;
  reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

/** What a reviewer sends for a condition. An edit needs the new text and a reason; a rejection needs a reason. */
export interface ConditionDecisionRequest {
  decision: "accepted" | "edited" | "rejected";
  edited_text?: string;
  reason?: string;
}

export interface ConditionAddRequest {
  text: string;
  priority: Priority;
}

export type ReportStatus = "draft" | "in_review" | "signed_off";

export interface SignOff {
  id: string;
  report_version: number;
  /** A user ID from the real backend (it sends no name yet); "demo.reviewer" in the mock. */
  signed_by: string;
  role: string;
  signed_at: string;
  note: string | null;
  /** Always "Records a review. Not a decision." */
  statement: string;
}

export interface SignOffResult {
  sign_off: SignOff;
  report_status: ReportStatus;
  /** Conditions still undecided when the review was recorded (underwriting only). */
  pending_conditions: number;
}

/** A guideline statement the report relies on, with the passage that supports it. */
export interface GuidelineReference {
  passage_id: string;
  summary: string;
}

export interface SnapshotItem {
  key: string;
  value: string;
}

/** The underwriting report's sections. */
export interface UnderwritingSections {
  snapshot: SnapshotItem[];
  conflicts: Conflict[];
  missing_information: string[];
  potential_risks: string[];
  guideline_references: GuidelineReference[];
  note: string | null;
}

/** The loss mitigation report's sections, in the order the Writer drafts them. */
export interface LmSections {
  lender_view: string;
  borrower_situation: string;
  missing_information: string[];
  compliance_points: string[];
  items_for_human_review: string[];
  note: string | null;
}

export interface ReportInfo<S> {
  id: string;
  version: number;
  status: ReportStatus;
  /** "seeded_sample" when it was written by hand for the demo and not by the agents. */
  source: "agents" | "seeded_sample";
  notice: string | null;
  created_at: string;
  sections: S;
  /** True when the Critic did not run, so the report was not checked. The section says "not available". */
  critic_missing: boolean;
}

/** Where a run stands. The report is null until the agents have finished. */
export type RunStatus = "running" | "succeeded" | "failed";

export interface UnderwritingReport {
  run_id: string;
  run_status: RunStatus;
  report: ReportInfo<UnderwritingSections> | null;
  findings: Finding[];
  conditions: Condition[];
  agent_runs: AgentRun[];
  sign_offs: SignOff[];
}

// ---- Loss mitigation: the waterfall and the lender view ---------------------------------------------

export type WaterfallOptionKey =
  | "repayment_plan"
  | "forbearance"
  | "payment_deferral"
  | "loan_modification"
  | "short_sale"
  | "deed_in_lieu";

/** What the rules found for a condition or an option. `met` says its conditions are met and nothing more. */
export type WaterfallStatus = "met" | "not_met" | "not_evaluable" | "not_reached" | "needs_confirmation";

/** The statuses a person may set when overriding a condition. */
export type OverrideStatus = Exclude<WaterfallStatus, "not_reached">;

export interface ConditionOverride {
  status: OverrideStatus;
  reason: string;
  by: string;
  at: string;
}

export interface WaterfallCondition {
  id: string;
  label: string;
  /** The rule as written, e.g. "surplus >= arrears / 6". */
  expression: string;
  /** The values the rule used, as the backend wrote them. */
  values: Record<string, string>;
  /** The passage of the investor guide this rule comes from. */
  passage_id: string | null;
  /** Set by the waterfall from the options before it, never by a person. */
  derived: boolean;
  /** What the rules found. */
  status: WaterfallStatus;
  /** What counts now: the override when there is one. */
  effective_status: WaterfallStatus;
  override: ConditionOverride | null;
}

export interface WaterfallOption {
  option: WaterfallOptionKey;
  order_no: number;
  /** After overrides. */
  status: WaterfallStatus;
  /** What the rules found. */
  original_status: WaterfallStatus;
  conditions: WaterfallCondition[];
  overridden: boolean;
}

export interface LenderFigure {
  name: string;
  value: string;
  unit: string;
  formula: string;
  /** One line ending in "= result". */
  working: string;
}

export interface LenderView {
  foreclosure_loss: string;
  modification_cost: string;
  advantage: string;
  /** The illustrative settings the figures use. */
  settings: Record<string, string | number>;
  figures: LenderFigure[];
  /** "Final terms are never computed here: to be calculated under the investor's own method." */
  final_terms: string;
}

export interface RuleSet {
  name: string;
  version: string;
  label: "illustrative" | "authoritative";
  /** "Illustrative: not an actual investor's requirements." when illustrative. */
  banner: string | null;
}

/** The parts of the recommendation a reviewer can leave a note on. */
export type AnnotationSection =
  | "waterfall"
  | "lender_view"
  | "borrower_situation"
  | "missing_information"
  | "compliance_points"
  | "items_for_human_review";

/** A reviewer's note on one part of the recommendation. Notes are only added: the report text is never changed. */
export interface Annotation {
  id: string;
  section: AnnotationSection;
  text: string;
  /** A user ID from the real backend (no name yet); "demo.reviewer" in the mock. */
  by: string;
  at: string;
}

export interface AnnotationRequest {
  section: AnnotationSection;
  text: string;
}

export interface LmRecommendation {
  run_id: string;
  run_status: RunStatus;
  source: "rules_engine" | "seeded_sample";
  notice: string | null;
  rule_set: RuleSet | null;
  waterfall: WaterfallOption[];
  lender_view: LenderView | null;
  /** Null until the agents have written one. */
  report: ReportInfo<LmSections> | null;
  /** The reviewer's notes, oldest first. The backend has no endpoint for them yet (see the going-live checklist). */
  annotations: Annotation[];
  agent_runs: AgentRun[];
  sign_offs: SignOff[];
}

export interface OverrideRequest {
  status: OverrideStatus;
  reason: string;
}
