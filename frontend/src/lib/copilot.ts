// Display helpers for the Underwriting copilot and the Loss Mitigation recommendation. Labels, grouping
// and links only: every figure arrives from the backend with its working, and nothing here calculates one
// (CLAUDE.md rule 1).
import type { ChipTone } from "@/components/shared/flag-chip";
import { formatMoney, humanize } from "./format";
import { documentHref } from "./income";
import type {
  AgentName,
  AgentRun,
  AgentStatus,
  Annotation,
  AnnotationSection,
  Condition,
  ConditionDecision,
  EvidenceRef,
  Finding,
  OverrideStatus,
  Priority,
  WaterfallOption,
  WaterfallOptionKey,
  WaterfallStatus,
} from "./copilot-types";

/** The sentence beside every sign-off control. The backend sends the same words with a sign-off. */
export const SIGN_OFF_STATEMENT = "Records a review. Not a decision.";

/** The longest reason or note the backend accepts. */
export const REASON_MAX = 500;
/** The longest condition text the backend accepts. */
export const CONDITION_TEXT_MAX = 2000;

// ---- Findings and conditions ----------------------------------------------------------------------

/** Review order, most important first. */
export const PRIORITY_ORDER: Priority[] = ["significant", "attention", "information"];

export const PRIORITY_LABEL: Record<Priority, string> = {
  significant: "Significant",
  attention: "Attention",
  information: "Information",
};

export const PRIORITY_TONE: Record<Priority, ChipTone> = {
  significant: "danger",
  attention: "warning",
  information: "info",
};

/** What the labels mean. They say what to look at first and nothing about the loan. */
export const PRIORITY_NOTE = "Priority is the order to review in. It says nothing about whether the loan can go ahead.";

/** Findings in priority order, with empty groups left out. Order within a group is the order sent. */
export function groupByPriority(findings: Finding[]): { priority: Priority; items: Finding[] }[] {
  return PRIORITY_ORDER.map((priority) => ({ priority, items: findings.filter((f) => f.priority === priority) })).filter(
    (g) => g.items.length > 0,
  );
}

export const DECISION_LABEL: Record<ConditionDecision, string> = {
  pending: "Not reviewed",
  accepted: "Accepted",
  edited: "Edited",
  rejected: "Rejected",
};

export const DECISION_TONE: Record<ConditionDecision, ChipTone> = {
  pending: "neutral",
  accepted: "success",
  edited: "info",
  rejected: "warning",
};

/** How many suggested conditions nobody has looked at yet. */
export const undecidedCount = (conditions: Condition[]): number => conditions.filter((c) => c.decision === "pending").length;

// ---- Agents ---------------------------------------------------------------------------------------

export const AGENT_ORDER: AgentName[] = ["researcher", "writer", "critic"];

export const AGENT_LABEL: Record<AgentName, string> = { researcher: "Researcher", writer: "Writer", critic: "Critic" };

export const AGENT_JOB: Record<AgentName, string> = {
  researcher: "Looks up the guidance that applies",
  writer: "Drafts the report from the stored results",
  critic: "Checks the draft against the evidence",
};

export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = {
  waiting: "Waiting",
  running: "Running",
  done: "Done",
  failed: "Failed",
};

export const AGENT_STATUS_TONE: Record<AgentStatus, ChipTone> = {
  waiting: "neutral",
  running: "info",
  done: "success",
  failed: "danger",
};

/** The three agents in order. An agent with no row yet is shown as waiting. */
export function agentSteps(runs: AgentRun[]): AgentRun[] {
  return AGENT_ORDER.map(
    (agent) =>
      runs.find((r) => r.agent === agent) ?? {
        agent,
        attempt: 1,
        status: "waiting",
        summary: null,
        error: null,
        started_at: null,
        finished_at: null,
      },
  );
}

/** True while any agent is waiting for its turn or running. */
export const agentsBusy = (runs: AgentRun[]): boolean => runs.some((r) => r.status === "running" || r.status === "waiting");

// ---- Evidence links -------------------------------------------------------------------------------

/** What a calculation is called, and the screen that shows it. A name not listed is shown humanized, with no link. */
const CALCULATIONS: Record<string, { label: string; section?: string }> = {
  dti: { label: "DTI", section: "assets-liabilities" },
  dti_with_overtime: { label: "DTI with overtime counted", section: "assets-liabilities" },
  documented_assets: { label: "Documented assets", section: "assets-liabilities" },
  funds_shortfall: { label: "Funds shortfall", section: "assets-liabilities" },
  large_deposit: { label: "Large deposit", section: "assets-liabilities" },
  monthly_obligations: { label: "Monthly obligations", section: "assets-liabilities" },
  front_end_ratio: { label: "Front-end ratio", section: "assets-liabilities" },
  ltv: { label: "LTV", section: "assets-liabilities" },
  candidate_monthly_income: { label: "Candidate monthly income", section: "income-analysis" },
  months_since_late_payment: { label: "Months since the late payment" },
};

/** Rule IDs start with the feature that raised them. */
const RULE_SECTION: Record<string, string> = {
  INC: "income-analysis",
  AL: "assets-liabilities",
  DI: "document-intelligence",
  HS: "hardship-budget",
};

export interface EvidenceLinkView {
  label: string;
  /** Where to read it, or null when no screen shows it. */
  href: string | null;
  kind: EvidenceRef["kind"];
  id: string;
}

/** A reference as a label and a link to the screen that shows what it points at. */
export function evidenceLink(ref: EvidenceRef, pillarSlug: string, caseId: string): EvidenceLinkView {
  const base = { kind: ref.kind, id: ref.id };
  switch (ref.kind) {
    case "calculation": {
      const known = CALCULATIONS[ref.id];
      return {
        ...base,
        label: known?.label ?? humanize(ref.id),
        href: known?.section ? `/${pillarSlug}/${known.section}` : null,
      };
    }
    case "rule": {
      const section = RULE_SECTION[ref.id.split("-")[0]];
      return { ...base, label: `Rule ${ref.id}`, href: section ? `/${pillarSlug}/${section}` : null };
    }
    case "checklist":
      return { ...base, label: `Checklist: ${humanize(ref.id)}`, href: `/${pillarSlug}/document-intelligence/${caseId}` };
    case "document":
      return { ...base, label: "Document", href: documentHref(pillarSlug, caseId, ref.id) };
    case "passage":
      return { ...base, label: "Guideline passage", href: null };
  }
}

// ---- The report snapshot --------------------------------------------------------------------------

const SNAPSHOT_LABEL: Record<string, string> = {
  borrower: "Borrower",
  loan: "Loan",
  property_value: "Property value",
  loan_amount: "Loan amount",
  ltv: "LTV",
  candidate_monthly_income: "Candidate monthly income",
  dti: "DTI",
  dti_review_level: "DTI review level",
};
const SNAPSHOT_MONEY = new Set(["property_value", "loan_amount", "candidate_monthly_income"]);

export const snapshotLabel = (key: string): string => SNAPSHOT_LABEL[key] ?? humanize(key);
export const snapshotValue = (key: string, value: string): string => (SNAPSHOT_MONEY.has(key) ? formatMoney(value) : value);

// ---- The waterfall --------------------------------------------------------------------------------

export const OPTION_LABEL: Record<WaterfallOptionKey, string> = {
  repayment_plan: "Repayment plan",
  forbearance: "Forbearance",
  payment_deferral: "Payment deferral",
  loan_modification: "Loan modification",
  short_sale: "Short sale",
  deed_in_lieu: "Deed-in-lieu",
};

export const WATERFALL_STATUS_LABEL: Record<WaterfallStatus, string> = {
  met: "Met",
  not_met: "Not met",
  not_evaluable: "Not evaluable",
  not_reached: "Not reached",
  needs_confirmation: "Needs confirmation",
};

export const WATERFALL_STATUS_TONE: Record<WaterfallStatus, ChipTone> = {
  met: "success",
  not_met: "warning",
  not_evaluable: "neutral",
  not_reached: "neutral",
  needs_confirmation: "info",
};

/** What a person may set when overriding a condition. A condition the waterfall has not reached is set by the waterfall. */
export const OVERRIDE_STATUS_OPTIONS: { value: OverrideStatus; label: string }[] = [
  { value: "met", label: WATERFALL_STATUS_LABEL.met },
  { value: "not_met", label: WATERFALL_STATUS_LABEL.not_met },
  { value: "needs_confirmation", label: WATERFALL_STATUS_LABEL.needs_confirmation },
  { value: "not_evaluable", label: WATERFALL_STATUS_LABEL.not_evaluable },
];

/** One card on the screen: an option, or short sale and deed-in-lieu together when they share a status. */
export interface WaterfallCard {
  key: string;
  title: string;
  /** "1", or "5–6" for the two together. */
  position: string;
  status: WaterfallStatus;
  options: WaterfallOption[];
}

/** The options as cards in waterfall order. Short sale and deed-in-lieu share one card while their statuses match. */
export function waterfallCards(options: WaterfallOption[]): WaterfallCard[] {
  const ordered = [...options].sort((a, b) => a.order_no - b.order_no);
  const cards: WaterfallCard[] = [];
  for (let i = 0; i < ordered.length; i++) {
    const o = ordered[i];
    const next = ordered[i + 1];
    if (o.option === "short_sale" && next?.option === "deed_in_lieu" && next.status === o.status) {
      cards.push({
        key: "short_sale_deed_in_lieu",
        title: "Short sale and deed-in-lieu",
        position: `${o.order_no}–${next.order_no}`,
        status: o.status,
        options: [o, next],
      });
      i++;
      continue;
    }
    cards.push({ key: o.option, title: OPTION_LABEL[o.option], position: String(o.order_no), status: o.status, options: [o] });
  }
  return cards;
}

const VALUE_LABEL: Record<string, string> = {
  surplus: "Monthly surplus",
  arrears: "Arrears",
  needed: "Needed",
  months_delinquent: "Months delinquent",
  limit: "Limit",
  duration: "Hardship duration",
  intent: "Intent",
  gross_monthly_income: "Documented gross monthly income",
  target_payment: "Target payment",
  contractual_payment: "Contractual payment",
};
const VALUE_MONEY = new Set(["surplus", "arrears", "needed", "gross_monthly_income", "target_payment", "contractual_payment"]);

export const valueLabel = (key: string): string => VALUE_LABEL[key] ?? humanize(key);

/** An amount with thousands separators; a count as it came; a word such as "long_term" as "Long term". */
export function conditionValue(key: string, value: string): string {
  if (VALUE_MONEY.has(key)) return formatMoney(value);
  return /^-?\d+(\.\d+)?$/.test(value) ? value : humanize(value);
}

// ---- The lender view ------------------------------------------------------------------------------

const SETTING_LABEL: Record<string, string> = {
  property_value: "Property value",
  liquidation_discount_pct: "Liquidation discount",
  foreclosure_and_carrying_costs: "Foreclosure and carrying costs",
  horizon_months: "Review horizon",
  redefault_chance_pct: "Chance of re-default after a modification",
};

export const settingLabel = (key: string): string => SETTING_LABEL[key] ?? humanize(key);

export function settingValue(key: string, value: string | number): string {
  const text = String(value);
  if (key.endsWith("_pct")) return `${text}%`;
  if (key === "horizon_months") return `${text} months`;
  return /^-?\d+(\.\d+)?$/.test(text) && text.includes(".") ? formatMoney(text) : text;
}

/** The three figures the lender view leads with, each with the calculations that show its working. */
export const LENDER_FIGURES = [
  { key: "foreclosure_loss", label: "Foreclosure loss", chain: ["foreclosure_claim", "foreclosure_net_recovery", "foreclosure_loss"] },
  {
    key: "modification_cost",
    label: "Modification expected cost",
    chain: ["modification_payment_reduction_total", "modification_expected_redefault_loss", "modification_cost"],
  },
  { key: "advantage", label: "Advantage of the modification", chain: ["modification_advantage"] },
] as const;

// ---- Notes on the recommendation ---------------------------------------------------------------------

export const ANNOTATION_MAX = 1000;

export const ANNOTATION_SECTION_LABEL: Record<AnnotationSection, string> = {
  waterfall: "Waterfall",
  lender_view: "Lender view",
  borrower_situation: "The borrower's situation",
  missing_information: "Missing information",
  compliance_points: "Compliance points",
  items_for_human_review: "Items for human review",
};

export const ANNOTATION_SECTIONS = Object.keys(ANNOTATION_SECTION_LABEL) as AnnotationSection[];

/** The notes on one part of the recommendation, in the order they were written. */
export const notesFor = (annotations: Annotation[], section: AnnotationSection): Annotation[] =>
  annotations.filter((a) => a.section === section);
