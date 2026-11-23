// A sample of what the real backend sends for Daniel Reyes's income analysis, written from
// backend/app/api/schemas/income.py (on `main` since PR #10), backend/config/income_method.yaml (the flag
// messages) and data/synthetic/scenarios/daniel_reyes.json ("expected.income"). It is test data for the
// translation in income-real.ts, not a mock the screens use. Replace it with a recorded real answer once
// the backend runs.
import type { RealCalc, RealRef } from "./calc-real";
import type { RealIncomeAnalysis, RealIncomeComponent, RealIncomeFlag } from "./income-real";

export const SAMPLE_STUB_ID = "11111111-1111-4111-8111-aaaaaaaaaaaa";
export const SAMPLE_CASE_ID = "11111111-1111-4111-8111-111111111111";
export const SAMPLE_CANDIDATE_LABEL = "candidate — qualifying income is determined by the underwriter";

const ref = (field: string, lines: string[]): RealRef => ({ document_id: SAMPLE_STUB_ID, field, line_ids: lines });

const calc = (name: string, value: string, formula: string, working: string, evidence: RealRef[] = []): RealCalc => ({
  id: `calc-${name}`,
  name,
  value,
  unit: "usd",
  formula,
  inputs: {},
  working,
  config_version: "income_method@2026-11-19.1",
  evidence,
});

const component = (
  n: number,
  kind: string,
  monthly: string,
  current: string | null,
  ytd: string | null,
  included: boolean,
  why: string | null,
): RealIncomeComponent => ({
  id: `33333333-3333-4333-8333-00000000000${n}`,
  borrower: "Daniel Reyes",
  employer: "Cedar Valley Manufacturing",
  component: kind,
  current_period: current,
  ytd,
  monthly,
  included,
  exclusion_reason: why,
  system_included: included,
  system_exclusion_reason: why,
  override: null,
  calculation: calc(`${kind}_monthly`, monthly, "rate x regular hours x pay periods per year / 12", `34.50 x 80.00 x 26 / 12 = ${monthly}`, [
    ref("gross_pay_current", ["p1-L14"]),
    ref("pay_frequency", ["p1-L8"]),
  ]),
});

const flag = (n: number, code: string, severity: string, message: string, refs: RealRef[] = [], working: string | null = null): RealIncomeFlag => ({
  id: `44444444-4444-4444-8444-00000000000${n}`,
  code,
  severity,
  message,
  status: "open",
  working,
  refs,
});

export function realDanielIncome(): RealIncomeAnalysis {
  return {
    id: "99999999-9999-4999-8999-000000000003",
    case_id: SAMPLE_CASE_ID,
    status: "succeeded",
    started_at: "2026-11-23T09:00:00Z",
    finished_at: "2026-11-23T09:00:04Z",
    config_versions: {
      income_method: { name: "income-method", version: "2026-11-19.1", label: "illustrative", hash: "abc123" },
      thresholds: { name: "thresholds", version: "2026-11-19.1", label: "illustrative", hash: "def456" },
    },
    candidate_monthly_income: "5980.00",
    candidate_label: SAMPLE_CANDIDATE_LABEL,
    // A single included component is written without " = ", as the backend does for a one-term sum.
    candidate: calc("candidate_monthly_income", "5980.00", "sum of the monthly amounts of the components that count", "5,980.00", [
      ref("gross_pay_current", ["p1-L14"]),
    ]),
    components: [
      component(1, "base", "5980.00", "2760.00", "52440.00", true, null),
      component(2, "overtime", "444.41", "204.93", "4217.43", false, "Documented history covers 2026 only. 24 months are needed to count it."),
      component(3, "bonus", "228.34", null, "2055.00", false, "Documented history covers 2026 only. 24 months are needed to count it."),
    ],
    flags: [
      flag(1, "INC-W101", "warning", "Overtime is excluded: its documented history is 9 months, and 24 months are needed.", [ref("overtime_ytd", ["p1-L16"])]),
      flag(2, "INC-W101", "warning", "Bonus is excluded: its documented history is 9 months, and 24 months are needed.", [ref("bonus_ytd", ["p1-L17"])]),
      flag(
        3,
        "INC-W102",
        "warning",
        "Year-to-date overtime averages 233.19 per pay period, against 204.93 this period (difference 28.26).",
        [],
        "4,217.43 / 18.09 periods = 233.19",
      ),
      flag(4, "INC-CHK-03:explained", "info", "W-2 Box 5 is 3,866.80 above Box 1 for 2025, which the Box 12 deferral codes (D) account for."),
      flag(5, "INC-CHK-04:trend", "info", "Gross pay rose 5.49% from 2024 (70,431.80) to 2025 (74,298.60)."),
    ],
    calculations: [
      calc("periods_elapsed", "19.00", "pay periods elapsed this year", "19.00", []),
      calc("w2_box5_growth", "0.054900", "W-2 Box 5 growth", "(74,298.60 - 70,431.80) / 70,431.80 = 5.49%"),
    ],
    explanations: [],
    explanations_note: "explanations not generated",
  };
}
