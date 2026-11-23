// What the real backend sends for the two agent screens, written from backend/app/api/schemas/reports.py and
// the seeded samples in backend/app/db/demo (daniel_underwriting_report.json, angela_lm_recommendation.json).
// Used by the tests for copilot-real.ts. Not a recording of a running backend.
import type { RealAgentRun, RealLmRecommendation, RealReportBundle } from "./copilot-real";

export const SAMPLE_REPORT_ID = "77777777-7777-4777-8777-000000000001";
export const SAMPLE_USER_ID = "55555555-5555-4555-8555-000000000001";

const AT = "2026-11-24T09:00:00Z";

/** The three agents of a seeded report: every one succeeded, and says it was not really run. */
export const sampleAgentRuns = (): RealAgentRun[] =>
  (["researcher", "writer", "critic"] as const).map((agent, i) => ({
    agent,
    attempt: 1,
    status: "succeeded",
    output: { summary: `${agent} summary (seeded: not run)` },
    error: null,
    started_at: `2026-11-24T09:00:0${i}Z`,
    finished_at: `2026-11-24T09:00:0${i + 1}Z`,
  }));

export const realDanielReport = (): RealReportBundle => ({
  run_id: "88888888-8888-4888-8888-000000000001",
  run_status: "succeeded",
  report: {
    id: SAMPLE_REPORT_ID,
    version: 1,
    status: "draft",
    source: "seeded_sample",
    notice: "Seeded sample: written by hand, not by the agents or the rules engine.",
    created_at: AT,
    sections: {
      snapshot: { borrower: "Daniel Reyes", property_value: "400000.00", dti: "44.70%" },
      conflicts: [
        {
          title: "DTI changes with the treatment of overtime",
          detail: "DTI is 44.70% with overtime and bonus left out of income, or 41.61% if overtime is counted.",
          evidence: [
            { type: "calculation", name: "dti" },
            { type: "calculation", name: "dti_with_overtime" },
          ],
        },
      ],
      missing_information: ["Page 3 of the August 2026 bank statement"],
      potential_risks: ["The funds to close are not yet documented."],
      guideline_references: [],
      automated_findings_comparison: null,
      note: "Illustrative sample.",
    },
    guardrail_results: {},
  },
  findings: [
    {
      id: "f1000000-0000-4000-8000-000000000001",
      priority: "significant",
      title: "DTI is 44.70%, above the illustrative 43% review level",
      detail: "(1,980.00 + 693.00) / 5,980.00 = 44.70%.",
      evidence: [
        { type: "calculation", name: "dti" },
        { type: "rule", id: "AL-W106" },
        { type: "checklist", id: "pay_stubs_30_days" },
        { type: "document", document_id: "d1000000-0000-4000-8000-000000000001", line_ids: ["p1-L31"] },
        { type: "passage", passage_id: "fannie-selling-guide.b3-3-1-01.overtime" },
        { type: "mystery", name: "x" },
        { type: "calculation" },
      ],
    },
  ],
  conditions: [
    {
      id: "c1000000-0000-4000-8000-000000000001",
      position: 1,
      text: "Provide page 3 of the August 2026 bank statement.",
      priority: "attention",
      source: "agent",
      decision: "pending",
      edited_text: null,
      current_text: "Provide page 3 of the August 2026 bank statement.",
      reason: null,
      decided_by: null,
      decided_at: null,
    },
  ],
  agent_runs: sampleAgentRuns(),
  sign_offs: [],
});

export const realAngelaRecommendation = (): RealLmRecommendation => ({
  run_id: "99999999-9999-4999-8999-000000000001",
  run_status: "succeeded",
  source: "seeded_sample",
  notice: "Seeded sample: written by hand, not by the agents or the rules engine.",
  rule_set: { name: "Sample Investor A", version: "1", label: "illustrative", banner: "Illustrative: not an actual investor's requirements." },
  waterfall: [
    {
      option: "repayment_plan",
      order_no: 1,
      status: "not_met",
      original_status: "not_met",
      overridden: false,
      conditions: [
        {
          id: "repayment_plan.surplus",
          label: "Monthly surplus at least arrears / 6",
          expression: "surplus >= arrears / 6",
          values: { surplus: "-70.00", arrears: "5160.00", needed: "860.00" },
          passage_id: "sample-investor-a-v1.repayment-plan.2",
          derived: false,
          status: "not_met",
          effective_status: "not_met",
          override: null,
        },
      ],
    },
    {
      option: "loan_modification",
      order_no: 4,
      status: "not_met",
      original_status: "met",
      overridden: true,
      conditions: [
        {
          id: "loan_modification.intent",
          label: "Intent to keep the home (confirmed)",
          expression: "hardship.intent == keep",
          values: { intent: "keep", months: 3 },
          passage_id: null,
          derived: false,
          status: "met",
          effective_status: "not_met",
          override: { status: "not_met", reason: "Intent not yet confirmed", by: SAMPLE_USER_ID, at: "2026-11-24T10:00:00Z" },
        },
      ],
    },
  ],
  lender_view: {
    foreclosure_loss: "16310.00",
    modification_cost: "13893.00",
    advantage: "2417.00",
    settings: { property_value: "265000.00", horizon_months: 36 },
    figures: [
      { name: "foreclosure_loss", value: "16310.00", unit: "usd", formula: "claim - net recovery", working: "217,560.00 - 201,250.00 = 16,310.00" },
    ],
    final_terms: "Final terms are never computed here: to be calculated under the investor's own method.",
  },
  report: {
    ...realDanielReport(),
    report: {
      ...realDanielReport().report,
      sections: {
        lender_view: "Foreclosure: a loss of 16,310.00.",
        borrower_situation: "Income fell by 25% from July 2026.",
        missing_information: ["The August 2026 bank statement"],
        compliance_points: ["12 CFR 1024.41(b): notify the borrower about missing documents."],
        items_for_human_review: ["Confirm the hardship duration and intent."],
        note: "Illustrative sample.",
      },
    },
    findings: [],
    conditions: [],
  },
});
