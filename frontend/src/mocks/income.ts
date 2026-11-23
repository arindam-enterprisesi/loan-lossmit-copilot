// Mock income analysis for Daniel Reyes, shaped like the income response we propose to Arindam
// (src/lib/income-types.ts). The figures are the ones in data/synthetic/scenarios/daniel_reyes.json
// ("expected.income") and the backend test that checks them, so the screen shows what the real
// calculation must return. The mock only repeats those answers: it does not calculate income.
// The one sum it does, the candidate total, stands in for the backend re-adding included components
// (Feature Design 2.4, steps 7 and 10: plain Python, no AI), using whole cents so nothing is a float.
import type { WorkingStep } from "@/components/shared/show-working-drawer";
import { ApiError } from "@/lib/api-error";
import { INCOME_REASON_MAX } from "@/lib/income";
import type {
  EvidenceLink,
  IncomeAnalysis,
  IncomeComponent,
  IncomeDecision,
  IncomeFigure,
  IncomeFlag,
} from "@/lib/income-types";
import { DANIEL_CASE_ID } from "./data";
import { PAYSTUB_DOC_ID } from "./extraction";

/** The label the backend gives every AI suggestion (backend/app/prompts/schemas/income.py). */
export const POSSIBLE_LABEL = "possible — to be confirmed";

/** "5980.00" to 598000. Money in the mock is always written with two decimals. */
export function toCents(amount: string): number {
  const [whole, frac = ""] = amount.split(".");
  return Number(whole) * 100 + Number(frac.padEnd(2, "0").slice(0, 2));
}

/** 598000 to "5980.00". */
export function fromCents(cents: number): string {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

/** 598000 to "5,980.00", the way the backend writes working. */
export function formatCents(cents: number): string {
  const [whole, frac] = fromCents(cents).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${frac}`;
}

const payStubLine = (page: number, line: number): EvidenceLink => ({
  label: `Pay stub, 27 Sep 2026, page ${page}`,
  document_id: PAYSTUB_DOC_ID,
  page,
  line_ids: [`p${page}-L${line}`],
});

const figure = (value: string, working: WorkingStep[], evidence: EvidenceLink[]): IncomeFigure => ({
  value,
  working,
  evidence,
});

const METHOD_NOTE_BASE = "Rate × regular hours × pay periods per year ÷ 12 (illustrative method)";
const METHOD_NOTE_YTD =
  "Year-to-date amount × periods per year ÷ (periods elapsed × 12) (illustrative method)";
const SHORT_HISTORY = "Documented history covers 2026 only. 24 months are needed to count it.";

function danielComponents(): IncomeComponent[] {
  return [
    {
      id: "base_pay",
      kind: "base_pay",
      label: "Base pay (hourly)",
      current_period: figure(
        "2760.00",
        [{ label: "Regular pay, current period", formula: "34.50 × 80.00 hours", result: "2,760.00" }],
        [payStubLine(1, 14)],
      ),
      year_to_date: figure(
        "52440.00",
        [
          {
            label: "Regular pay, year to date",
            formula: "Printed on the pay stub, period 19 of 26",
            result: "52,440.00",
          },
        ],
        [payStubLine(2, 6)],
      ),
      monthly: figure(
        "5980.00",
        [
          {
            label: "Base pay, monthly",
            formula: "34.50 × 80.00 hours × 26 periods ÷ 12",
            result: "5,980.00",
            note: METHOD_NOTE_BASE,
          },
        ],
        [payStubLine(1, 14), payStubLine(1, 8)],
      ),
      included: true,
      rule_included: true,
      rule_note: null,
      override: null,
    },
    {
      id: "overtime",
      kind: "overtime",
      label: "Overtime (1.5x)",
      current_period: figure(
        "204.93",
        [{ label: "Overtime, current period", formula: "51.75 × 3.96 hours", result: "204.93" }],
        [payStubLine(1, 15)],
      ),
      year_to_date: figure(
        "3897.10",
        [
          {
            label: "Overtime, year to date",
            formula: "Printed on the pay stub, period 19 of 26",
            result: "3,897.10",
          },
        ],
        [payStubLine(2, 7)],
      ),
      monthly: figure(
        "444.41",
        [
          {
            label: "Overtime, monthly average",
            formula: "3,897.10 × 26 ÷ (19 × 12)",
            result: "444.41",
            note: METHOD_NOTE_YTD,
          },
        ],
        [payStubLine(2, 7)],
      ),
      included: false,
      rule_included: false,
      rule_note: SHORT_HISTORY,
      override: null,
    },
    {
      id: "bonus",
      kind: "bonus",
      label: "Bonus",
      current_period: figure(
        "105.57",
        [{ label: "Bonus, current period", formula: "Printed on the pay stub", result: "105.57" }],
        [payStubLine(1, 16)],
      ),
      year_to_date: figure(
        "2002.40",
        [
          {
            label: "Bonus, year to date",
            formula: "Printed on the pay stub, period 19 of 26",
            result: "2,002.40",
          },
        ],
        [payStubLine(2, 8)],
      ),
      monthly: figure(
        "228.34",
        [
          {
            label: "Bonus, monthly average",
            formula: "2,002.40 × 26 ÷ (19 × 12)",
            result: "228.34",
            note: METHOD_NOTE_YTD,
          },
        ],
        [payStubLine(2, 8)],
      ),
      included: false,
      rule_included: false,
      rule_note: SHORT_HISTORY,
      override: null,
    },
  ];
}

/**
 * Candidate monthly income: the sum of the included components' monthly figures. Whole cents, so no
 * rounding. Used for the first run and again whenever a component is included or excluded.
 */
export function candidateFrom(components: IncomeComponent[]): IncomeFigure {
  const included = components.filter((c) => c.included);
  const left = components.filter((c) => !c.included);
  const total = included.reduce((sum, c) => sum + toCents(c.monthly.value), 0);
  const parts = included.map((c) => formatCents(toCents(c.monthly.value)));
  const note = left.length
    ? `Left out: ${left.map((c) => `${c.label} (${formatCents(toCents(c.monthly.value))})`).join(", ")}`
    : "Nothing is left out";
  return figure(
    fromCents(total),
    [
      {
        label: "Sum of the components counted",
        formula: parts.length ? parts.join(" + ") : "0.00",
        result: formatCents(total),
        note,
      },
    ],
    included.flatMap((c) => c.monthly.evidence),
  );
}

/**
 * Records a person's include or exclude decision and re-adds the candidate. Stands in for the backend
 * (PATCH .../components/{id}): the figures and their working are the same as before, only the set of
 * components that are added up changes, and the decision is kept with who, when and why. The rule's
 * own answer (`rule_included`, `rule_note`) is never touched. Returns a new analysis, not a changed one.
 */
export function applyIncomeDecision(
  analysis: IncomeAnalysis,
  componentId: string,
  decision: IncomeDecision,
  by: string,
  at: string,
): IncomeAnalysis {
  const reason = decision.reason?.trim();
  if (!reason) throw new ApiError(422, "A reason is required");
  if (reason.length > INCOME_REASON_MAX) {
    throw new ApiError(422, `The reason can be at most ${INCOME_REASON_MAX} characters`);
  }
  if (!analysis.components.some((c) => c.id === componentId)) throw new ApiError(404, "Income component not found");
  const components = analysis.components.map((c) =>
    c.id === componentId
      ? { ...c, included: decision.included, override: { included: decision.included, reason, by, at } }
      : c,
  );
  return { ...analysis, components, candidate_monthly: candidateFrom(components) };
}

const shortHistoryFlag: IncomeFlag = {
  code: "income.short_history",
  severity: "warning",
  message: "Overtime and bonus are left out of the candidate figure: their documented history is under 24 months.",
  values: [
    {
      label: "Documented history",
      value: "2026 only (pay period 19 of 26)",
      source: payStubLine(2, 7),
    },
    {
      label: "History needed to count it",
      value: "24 months or more",
      source: { label: "Income method income-method@1 (illustrative)" },
    },
  ],
  explanations: [
    {
      text:
        "Overtime and bonus may have started this year, or earlier years of them may be on a previous " +
        "year's pay stubs. A year-end pay stub or an employer letter would show how long they have been paid.",
      label: POSSIBLE_LABEL,
      evidence_refs: ["paystub_2026.ytd.overtime", "paystub_2026.ytd.bonus"],
      suggested_documents: [
        "Final pay stub of 2025 showing year-to-date overtime and bonus",
        "Employer letter stating how long overtime and bonus have been paid",
      ],
      figures_verified: true,
    },
  ],
};

/** What the backend would return after a run for Daniel. */
export function buildDanielIncome(runAt: string, id = "ab000000-0000-4000-8000-000000000001"): IncomeAnalysis {
  const components = danielComponents();
  const flags = [structuredClone(shortHistoryFlag)];
  return {
    id,
    case_id: DANIEL_CASE_ID,
    run_at: runAt,
    method_version: "income-method@1",
    method_label: "illustrative",
    components,
    candidate_monthly: candidateFrom(components),
    trend: [
      "Gross pay rose 5.49% in 2025 (W-2 Box 5: 70,431.80 to 74,298.60).",
      "Annualized 2026 gross pay is 79,833.00, up 7.45% on 2025.",
    ],
    checks: [
      {
        id: "wages",
        label: "Wages: Form 1040 against W-2 Box 1",
        status: "passed",
        detail: "2025: 69,840.68 on both. 2024: 66,205.89 on both.",
      },
      {
        id: "employer",
        label: "Employer: latest pay stub against latest W-2",
        status: "passed",
        detail: "Cedar Valley Manufacturing, Inc. on both.",
      },
      {
        id: "deferrals",
        label: "Deferrals: W-2 Box 5 minus Box 1 against Box 12 code D",
        status: "passed",
        detail: "2025: 4,457.92 and 2024: 4,225.91, each equal to the code D amount.",
      },
      {
        id: "trend",
        label: "Trend: year-over-year change",
        status: "passed",
        detail: "Up 5.49%. A drop above 5% would be flagged.",
      },
    ],
    flags,
    document_requests: documentRequestsFrom(flags),
  };
}

/** The suggested documents from every explanation, once each, in order. */
export function documentRequestsFrom(flags: IncomeFlag[]): string[] {
  return [...new Set(flags.flatMap((f) => f.explanations.flatMap((e) => e.suggested_documents)))];
}

/** Which cases have an income analysis to run. Only Daniel's wage-earner purchase does for now. */
export function hasIncomeSeed(caseId: string): boolean {
  return caseId === DANIEL_CASE_ID;
}
