// Reads the real backend's asset and liability answers into the shapes the Assets and liabilities screen
// uses. The real shapes are in backend/app/api/schemas/assets.py (on `main` since PR #12, 23 Nov 2026).
// They are not in contracts/openapi.yaml. This file only translates: it renames fields, picks display
// labels, and cuts the backend's working text into steps. It never calculates (CLAUDE.md rule 1). A
// percentage is the one the backend wrote at the end of its own working ("... = 44.70%"), because it
// sends ratios as six-place decimals ("0.446990").
//
// If the backend's shapes change, this is the only file that changes.
import { evidenceOf, shownValue, stepOf, type RealCalc, type RealRef } from "./calc-real";
import { humanize } from "./format";
import type {
  AssetAnalysis,
  AssetChange,
  AssetFigure,
  AssetFlag,
  AssetObligation,
  AssetTransaction,
  LoanScenario,
  LoanScenarioInput,
  ObligationReview,
  ObligationSource,
  OtherFigure,
  TransactionCategory,
  TransactionFlag,
  TransactionReview,
} from "./assets-types";
import type { Severity } from "./types";

// --- what the backend sends ----------------------------------------------------------------

interface RealChange {
  reason: string;
  /** The reviewer's user id. The backend does not send a name yet. */
  by: string;
  at: string;
}

export interface RealTransaction {
  id: string;
  document_id: string;
  line_id: string;
  account_last4: string | null;
  posted_on: string;
  description: string;
  /** The size of the line, as text. The direction says which way the money went. */
  amount: string;
  direction: "credit" | "debit";
  category: TransactionCategory;
  category_source: "ai" | "user";
  system_category: TransactionCategory;
  counterparty: string | null;
  needs_review: boolean;
  sourced: boolean;
  sourced_note: string | null;
  change: RealChange | null;
  payroll_match: RealCalc | null;
  large_deposit: RealCalc | null;
}

export interface RealObligation {
  id: string;
  creditor: string;
  kind: string;
  monthly_payment: string;
  balance: string | null;
  source: ObligationSource;
  counts_toward_dti: boolean;
  reason: string;
  system_counts_toward_dti: boolean;
  change: RealChange | null;
}

export interface RealFlag {
  id: string;
  code: string;
  severity: string;
  message: string;
  status: string;
  working: string | null;
  refs: RealRef[];
}

export interface RealAssetAnalysis {
  id: string;
  case_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  config_versions: Record<string, unknown>;
  note: string;
  documented_assets: RealCalc | null;
  funds_to_close: RealCalc | null;
  funds_shortfall: RealCalc | null;
  monthly_obligations: RealCalc | null;
  front_end_ratio: RealCalc | null;
  dti: RealCalc | null;
  ltv: RealCalc | null;
  /** The other figures: DTI with each left-out income component counted, and so on. */
  calculations: RealCalc[];
  obligations: RealObligation[];
  transactions: RealTransaction[];
  flags: RealFlag[];
}

export interface RealLoanScenario {
  case_id: string;
  purpose: string;
  occupancy: string;
  property_value: string;
  loan_amount: string;
  proposed_housing_payment: string;
  funds_to_close: string;
  updated_at: string | null;
}

// --- figures ---------------------------------------------------------------------------------

function figureOf(calc: RealCalc | null): AssetFigure | null {
  if (!calc) return null;
  const shown = shownValue(calc);
  return { value: shown.value, unit: shown.unit, working: [stepOf(calc)], evidence: evidenceOf(calc.evidence) };
}

/** "dti_with_overtime" -> "DTI if overtime were counted". Only these are shown beside the headline figures. */
const WHAT_IF = /^dti_with_(.+)$/;

function otherFigures(calcs: RealCalc[]): OtherFigure[] {
  const out: OtherFigure[] = [];
  for (const calc of calcs) {
    const m = WHAT_IF.exec(calc.name);
    const figure = figureOf(calc);
    if (m && figure) out.push({ id: calc.name, label: `DTI if ${humanize(m[1]).toLowerCase()} were counted`, figure });
  }
  return out;
}

// --- lines, debts and flags ------------------------------------------------------------------

const SEVERITIES: Severity[] = ["error", "warning", "info"];
const severityOf = (s: string): Severity => (SEVERITIES.includes(s as Severity) ? (s as Severity) : "warning");

const changeOf = (c: RealChange | null): AssetChange | null => (c ? { reason: c.reason, by: c.by, at: c.at } : null);

/** The flags whose evidence points at this statement line. */
function flagsFor(t: RealTransaction, flags: RealFlag[]): TransactionFlag[] {
  return flags
    .filter((f) => f.refs.some((r) => r.document_id === t.document_id && r.line_ids.includes(t.line_id)))
    .map((f) => ({ code: f.code, severity: severityOf(f.severity), message: f.message }));
}

function transactionOf(t: RealTransaction, flags: RealFlag[]): AssetTransaction {
  return {
    id: t.id,
    document_id: t.document_id,
    line_id: t.line_id,
    account_last4: t.account_last4,
    posted_on: t.posted_on,
    description: t.description,
    // Money out is shown with a minus sign, as a bank statement shows it. Only a sign is added to the text.
    amount: t.direction === "debit" && !t.amount.startsWith("-") ? `-${t.amount}` : t.amount,
    direction: t.direction,
    category: t.category,
    category_source: t.category_source,
    system_category: t.system_category,
    counterparty: t.counterparty,
    needs_review: t.needs_review,
    sourced: t.sourced,
    sourced_note: t.sourced_note,
    change: changeOf(t.change),
    payroll_match: t.payroll_match?.working ?? null,
    flags: flagsFor(t, flags),
  };
}

const obligationOf = (o: RealObligation): AssetObligation => ({
  id: o.id,
  creditor: o.creditor,
  kind: o.kind,
  monthly_payment: o.monthly_payment,
  balance: o.balance,
  source: o.source,
  counts_toward_dti: o.counts_toward_dti,
  system_counts_toward_dti: o.system_counts_toward_dti,
  reason: o.reason,
  change: changeOf(o.change),
});

const flagOf = (f: RealFlag): AssetFlag => ({
  code: f.code,
  severity: severityOf(f.severity),
  message: f.message,
  status: f.status,
  working: f.working,
  evidence: evidenceOf(f.refs),
});

/** The settings are "illustrative" unless one of them says it is authoritative. */
function settingsLabel(versions: Record<string, unknown>): AssetAnalysis["settings_label"] {
  const labels = Object.values(versions).map((v) => (v && typeof v === "object" ? (v as { label?: unknown }).label : undefined));
  return labels.length > 0 && labels.every((l) => l === "authoritative") ? "authoritative" : "illustrative";
}

// --- the whole analysis ----------------------------------------------------------------------

export function toAssetAnalysis(real: RealAssetAnalysis, caseId: string): AssetAnalysis {
  return {
    id: real.id,
    case_id: caseId,
    run_at: real.finished_at ?? real.started_at,
    settings_label: settingsLabel(real.config_versions),
    note: real.note,
    documented_assets: figureOf(real.documented_assets),
    funds_to_close: figureOf(real.funds_to_close),
    funds_shortfall: figureOf(real.funds_shortfall),
    monthly_obligations: figureOf(real.monthly_obligations),
    front_end_ratio: figureOf(real.front_end_ratio),
    dti: figureOf(real.dti),
    ltv: figureOf(real.ltv),
    other_figures: otherFigures(real.calculations),
    obligations: real.obligations.map(obligationOf),
    transactions: real.transactions.map((t) => transactionOf(t, real.flags)),
    flags: real.flags.map(flagOf),
  };
}

export function toLoanScenario(real: RealLoanScenario): LoanScenario {
  return {
    purpose: real.purpose,
    occupancy: real.occupancy,
    property_value: real.property_value,
    loan_amount: real.loan_amount,
    proposed_housing_payment: real.proposed_housing_payment,
    funds_to_close: real.funds_to_close,
    updated_at: real.updated_at,
  };
}

// --- what a person sends ---------------------------------------------------------------------

/** PUT .../loan-scenario takes exactly these six fields. Amounts stay text, so nothing is rounded on the way. */
export function scenarioRequest(input: LoanScenarioInput): LoanScenarioInput {
  return {
    purpose: input.purpose,
    occupancy: input.occupancy,
    property_value: input.property_value,
    loan_amount: input.loan_amount,
    proposed_housing_payment: input.proposed_housing_payment,
    funds_to_close: input.funds_to_close,
  };
}

/** PATCH .../transactions/{id} takes a category or `sourced`, never both, and a reason. */
export function transactionRequest(r: TransactionReview): { category: TransactionCategory; reason: string } | { sourced: boolean; reason: string } {
  return r.category !== undefined ? { category: r.category, reason: r.reason } : { sourced: r.sourced === true, reason: r.reason };
}

/** PATCH .../obligations/{id}. */
export const obligationRequest = (r: ObligationReview): ObligationReview => ({
  counts_toward_dti: r.counts_toward_dti,
  reason: r.reason,
});
