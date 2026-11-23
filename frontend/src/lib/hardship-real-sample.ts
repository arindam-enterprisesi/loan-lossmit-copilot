// A sample of what the real backend sends for Angela Whitfield's hardship assessment, written from
// backend/app/api/schemas/hardship.py (on `main` since PR #12) and the figures in
// data/synthetic/scenarios. It is test data for the translation in hardship-real.ts, not a mock the
// screens use. Replace it with a recorded real answer once the backend runs.
import type { RealCalc, RealHardshipAssessment, RealRef } from "./hardship-real";

export const SAMPLE_LETTER_ID = "11111111-1111-4111-8111-aaaaaaaaaaaa";
export const SAMPLE_STUB_ID = "11111111-1111-4111-8111-bbbbbbbbbbbb";
export const SAMPLE_LINE_IDS = {
  other: "33333333-3333-4333-8333-000000000005",
  housing: "33333333-3333-4333-8333-000000000001",
};

const ref = (document_id: string, field: string, lines: string[]): RealRef => ({ document_id, field, line_ids: lines });

const calc = (
  name: string,
  value: string,
  unit: string,
  formula: string,
  working: string,
  evidence: RealRef[] = [],
): RealCalc => ({
  id: `calc-${name}`,
  name,
  value,
  unit,
  formula,
  inputs: {},
  working,
  config_version: "hardship@2026-11-19.1, thresholds@2026-11-19.1",
  evidence,
});

const quoted = (quote: string, line: string) => ({ quote, lines: [line], verified: true, check_flags: [] as string[] });

export function realAngelaHardship(): RealHardshipAssessment {
  return {
    run_id: "99999999-9999-4999-8999-000000000001",
    source: "seeded_sample",
    created_at: "2026-11-20T09:00:00Z",
    letter_document_id: SAMPLE_LETTER_ID,
    config_version: "2026-11-19.1",
    config_label: "illustrative",
    profile: {
      primary_reason: {
        ...quoted("cut my hours from 40 to 30 a week in July", "p1-L6"),
        category: "reduction_in_income",
        category_label: "Reduction in income",
        sensitive: false,
        financial_effect: "Lower monthly income",
        confirmation: null,
      },
      onset: { ...quoted("in July", "p1-L6"), as_stated: "July", month: "2026-07", confirmation: null },
      duration: {
        ...quoted("I do not know whether my hours will return to 40 a week", "p1-L9"),
        category: "unknown",
        confirmation: null,
      },
      intent: { ...quoted("I want to keep my home", "p1-L14"), category: "keep", confirmation: null },
    },
    budget: [
      ["housing", "1720.00", "1720.00"],
      ["utilities", "310.00", "310.00"],
      ["food", "780.00", "780.00"],
      ["loans", "410.00", "410.00"],
      ["other", "200.00", "410.00"],
    ].map(([category, stated, observed], i) => ({
      id: `44444444-4444-4444-8444-00000000000${i + 1}`,
      category,
      stated,
      observed,
      observed_month: "July",
      adjusted: null,
      adjustment_reason: null,
      effective_observed: observed,
      difference: stated === observed ? "0.00" : "210.00",
      flagged: stated !== observed,
      change: null,
      stated_calc: calc(`stated_${category}`, stated, "usd", "stated amount", `${stated} = ${stated}`, [
        ref(SAMPLE_LETTER_ID, "stated_expense", ["p1-L3"]),
      ]),
      observed_calc: calc(`observed_${category}`, observed, "usd", "observed amount", `${observed} = ${observed}`, [
        ref(SAMPLE_STUB_ID, "debit", ["p1-L9"]),
      ]),
    })),
    measures: [
      calc("surplus_observed", "-280.00", "usd", "net monthly income - observed expenses", "3,350.00 - 3,630.00 = -280.00", [
        ref(SAMPLE_STUB_ID, "net_pay_current", ["p1-L12"]),
      ]),
      calc("surplus_stated", "-70.00", "usd", "net monthly income - stated expenses", "3,350.00 - 3,420.00 = -70.00"),
      calc("housing_ratio", "0.409524", "ratio", "contractual payment / documented gross monthly income", "1,720.00 / 4,200.00 = 40.95%", [
        ref(SAMPLE_STUB_ID, "regular_monthly_payment", ["p1-L4"]),
      ]),
      calc("housing_ratio_before_cut", "0.307143", "ratio", "contractual payment / gross monthly income before the change", "1,720.00 / 5,600.00 = 30.71%"),
      calc("arrears", "5160.00", "usd", "the mortgage statement's past due amount", "5,160.00 = 5,160.00", [
        ref(SAMPLE_STUB_ID, "past_due_amount", ["p1-L7"]),
      ]),
      calc("liquid_assets", "640.25", "usd", "sum of closing balances", "412.10 + 228.15 = 640.25"),
      calc("liquid_assets_share_of_arrears", "0.124080", "ratio", "liquid assets / arrears", "640.25 / 5,160.00 = 12.41%"),
      calc("income_change", "-0.250000", "ratio", "(latest gross monthly income - earliest gross monthly income) / earliest", "(4,200.00 - 5,600.00) / 5,600.00 = -25.00%"),
      calc("stated_expenses_total", "3420.00", "usd", "sum of stated expenses", "3,420.00 = 3,420.00"),
      calc("observed_expenses_total", "3630.00", "usd", "sum of observed expenses", "3,630.00 = 3,630.00"),
    ],
    checks: [
      {
        name: "check_income_stated_vs_documented",
        agrees: true,
        working: "Stated 4,200.00; documented 4,200.00. They agree.",
        values: { stated: "4200.00", documented: "4200.00" },
      },
      {
        name: "check_pay_vs_hours",
        agrees: true,
        working:
          "Pay on the stubs changed by -25.00% (5,600.00 to 4,200.00 a month); the letter says hours changed by -25.00% (40 to 30 a week). They agree.",
        values: { pay_change: "-0.250000", hours_change: "-0.250000" },
      },
      {
        name: "check_reason_vs_letter",
        agrees: true,
        working: "The application ticks Reduction of income; the letter's main reason is reduction_in_income. They agree.",
        values: { application: "Reduction of income", letter: "reduction_in_income" },
      },
      {
        name: "check_intent_vs_letter",
        agrees: true,
        working: "The application says keep; the letter says keep. They agree.",
        values: { application: "keep", letter: "keep" },
      },
    ],
    budget_flags: [
      {
        id: "flag-1",
        code: "HB-W101",
        severity: "warning",
        message: "Observed other spending 410.00 against 200.00 stated — ask the borrower",
        status: "open",
        working: null,
        refs: [],
      },
    ],
    budget_note: null,
  };
}
