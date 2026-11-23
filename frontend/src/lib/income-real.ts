// Reads the real backend's income answer into the shape the Income analysis screen uses. The real shapes
// are in backend/app/api/schemas/income.py (on `main` since PR #10) and docs/contract-proposal-d4.md. They
// are not in contracts/openapi.yaml. This file only translates: it renames fields, picks display labels,
// sorts the backend's flags into the screen's sections, and cuts the backend's working text into steps. It
// never calculates (CLAUDE.md rule 1).
//
// If the backend's shapes change, this is the only file that changes.
import { evidenceOf, stepOf, type RealCalc, type RealRef } from "./calc-real";
import { humanize } from "./format";
import type {
  EvidenceLink,
  IncomeAnalysis,
  IncomeCheck,
  IncomeComponent,
  IncomeComponentKind,
  IncomeDecision,
  IncomeFigure,
  IncomeFlag,
} from "./income-types";
import type { Severity } from "./types";

// --- what the backend sends ----------------------------------------------------------------

export interface RealIncomeComponent {
  id: string;
  borrower: string;
  employer: string | null;
  component: string;
  current_period: string | null;
  ytd: string | null;
  monthly: string;
  included: boolean;
  exclusion_reason: string | null;
  system_included: boolean;
  system_exclusion_reason: string | null;
  /** A person's include or exclude. `by` is the reviewer's user id: the backend does not send a name yet. */
  override: { included: boolean; reason: string; by: string; at: string } | null;
  calculation: RealCalc | null;
}

export interface RealIncomeFlag {
  id: string;
  code: string;
  severity: string;
  message: string;
  status: string;
  working: string | null;
  refs: RealRef[];
}

export interface RealIncomeAnalysis {
  id: string;
  case_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  /** `{ income_method: { name, version, label, hash }, ... }` */
  config_versions: Record<string, unknown>;
  candidate_monthly_income: string | null;
  candidate_label: string;
  candidate: RealCalc | null;
  components: RealIncomeComponent[];
  flags: RealIncomeFlag[];
  /** Every other figure: periods elapsed, year-to-date checks, the annual history. Not shown yet. */
  calculations: RealCalc[];
  /** income-explain@1 results, each "possible - to be confirmed". Empty until the explanation call is wired in. */
  explanations: string[];
  explanations_note: string;
}

// --- components ----------------------------------------------------------------------------

const KIND: Record<string, IncomeComponentKind> = { base: "base_pay", overtime: "overtime", bonus: "bonus", commission: "commission" };
const KIND_LABEL: Record<string, string> = { base: "Base pay", overtime: "Overtime", bonus: "Bonus", commission: "Commission" };

const plainFigure = (value: string | null): IncomeFigure | null => (value === null ? null : { value, working: [], evidence: [] });

function componentOf(c: RealIncomeComponent, withBorrower: boolean): IncomeComponent {
  const kind = KIND_LABEL[c.component] ?? humanize(c.component);
  const parts = [withBorrower ? c.borrower : null, c.employer].filter((p): p is string => !!p);
  return {
    id: c.id,
    kind: KIND[c.component] ?? "other",
    label: parts.length ? `${kind} (${parts.join(", ")})` : kind,
    // Only the monthly figure comes with working. The others are plain amounts, so they have none to show.
    current_period: plainFigure(c.current_period),
    year_to_date: plainFigure(c.ytd),
    monthly: c.calculation
      ? { value: c.monthly, working: [stepOf(c.calculation)], evidence: evidenceOf(c.calculation.evidence) }
      : { value: c.monthly, working: [], evidence: [] },
    included: c.included,
    rule_included: c.system_included,
    rule_note: c.system_exclusion_reason,
    override: c.override ? { included: c.override.included, reason: c.override.reason, by: c.override.by, at: c.override.at } : null,
  };
}

// --- flags and checks ----------------------------------------------------------------------

const SEVERITIES: Severity[] = ["error", "warning", "info"];
const severityOf = (s: string): Severity => (SEVERITIES.includes(s as Severity) ? (s as Severity) : "warning");

/** The cross-document comparisons arrive as flags with these codes (backend/config/income_method.yaml). */
const CHECK_LABELS: Record<string, string> = {
  "INC-CHK-01": "Form 1040 wages against W-2 Box 1",
  "INC-CHK-02": "Employer on the pay stub and the W-2",
  "INC-CHK-03": "W-2 Box 5 against Box 1 and the Box 12 deferrals",
  "INC-CHK-04": "Year-over-year change in pay",
};

const isCheck = (code: string): boolean => code.startsWith("INC-CHK-");
/** "INC-CHK-04:trend" is a sentence about the trend, not a pass or a fail. */
const isTrend = (code: string): boolean => code.endsWith(":trend");

function flagOf(f: RealIncomeFlag): IncomeFlag {
  return {
    code: f.code,
    severity: severityOf(f.severity),
    message: f.message,
    // The backend puts both sides in the message, so there is no side-by-side pair to build.
    values: [],
    explanations: [],
    working: f.working,
    evidence: evidenceOf(f.refs),
    status: f.status,
  };
}

function checkOf(f: RealIncomeFlag): IncomeCheck {
  const base = f.code.split(":")[0];
  return {
    id: f.code,
    label: CHECK_LABELS[base] ?? humanize(base),
    // An info-level result means the comparison agrees or is explained; a warning means it differs.
    status: severityOf(f.severity) === "info" ? "passed" : "flagged",
    detail: f.message,
  };
}

// --- the whole analysis --------------------------------------------------------------------

/** "income_method" -> "income-method@2026-11-19.1" and its label, from the backend's config versions. */
function method(versions: Record<string, unknown>): { version: string; label: IncomeAnalysis["method_label"] } {
  const entries = Object.entries(versions).filter(([, v]) => v && typeof v === "object") as [string, { name?: string; version?: string; label?: string }][];
  const found = entries.find(([key]) => /income/i.test(key)) ?? entries[0];
  if (!found) return { version: "income method", label: "illustrative" };
  const [key, v] = found;
  return {
    version: v.name && v.version ? `${v.name}@${v.version}` : (v.name ?? key),
    label: v.label === "authoritative" ? "authoritative" : "illustrative",
  };
}

export function toIncomeAnalysis(real: RealIncomeAnalysis, caseId: string): IncomeAnalysis {
  const borrowers = new Set(real.components.map((c) => c.borrower));
  const checkFlags = real.flags.filter((f) => isCheck(f.code));
  const m = method(real.config_versions);
  const candidateEvidence: EvidenceLink[] = real.candidate ? evidenceOf(real.candidate.evidence) : [];
  return {
    id: real.id,
    case_id: caseId,
    run_at: real.finished_at ?? real.started_at,
    method_version: m.version,
    method_label: m.label,
    components: real.components.map((c) => componentOf(c, borrowers.size > 1)),
    candidate_monthly: {
      // An empty value shows as a dash: the backend could not work the candidate out.
      value: real.candidate_monthly_income ?? "",
      working: real.candidate ? [stepOf(real.candidate)] : [],
      evidence: candidateEvidence,
    },
    trend: checkFlags.filter((f) => isTrend(f.code)).map((f) => f.message),
    checks: checkFlags.filter((f) => !isTrend(f.code)).map(checkOf),
    flags: real.flags.filter((f) => !isCheck(f.code)).map(flagOf),
    // The suggested documents come with the explanations, which are not generated yet.
    document_requests: [],
    candidate_label: real.candidate_label,
    explanations: real.explanations,
    explanations_note: real.explanations_note || null,
  };
}

// --- what a person sends -------------------------------------------------------------------

/** PATCH .../latest/components/{id} takes exactly these two fields. */
export const componentRequest = (d: IncomeDecision): IncomeDecision => ({ included: d.included, reason: d.reason });
