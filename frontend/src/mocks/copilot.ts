// Stand-in for the backend's two agent features while NEXT_PUBLIC_USE_MOCKS=true: the Underwriting copilot
// (Daniel Reyes, Feature Design 6) and the Loss Mitigation recommendation (Angela Whitfield, Feature
// Design 8). It does what the backend does, and the screens never do: runs the three agents one after the
// other, applies the sample investor's rules to the case and works out the lender's comparison in whole
// cents, recomputes the waterfall after an override, and keeps what the agents wrote beside a reviewer's
// edit. The wording and figures follow the backend's own seeded samples (backend/app/db/demo) and the
// Feature Design worked examples. A page reload resets it. It is replaced by the real API.
import { ApiError } from "@/lib/api-error";
import type {
  AgentName,
  AgentRun,
  AgentStatus,
  Condition,
  ConditionAddRequest,
  ConditionDecisionRequest,
  Conflict,
  EvidenceRef,
  Finding,
  LenderFigure,
  LenderView,
  LmRecommendation,
  LmSections,
  OverrideRequest,
  ReportStatus,
  RuleSet,
  SignOff,
  SignOffResult,
  UnderwritingReport,
  UnderwritingSections,
  WaterfallCondition,
  WaterfallOption,
  WaterfallOptionKey,
  WaterfallStatus,
} from "@/lib/copilot-types";
import { AGENT_ORDER, SIGN_OFF_STATEMENT } from "@/lib/copilot";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import { PAYSTUB_DOC_ID } from "./extraction";
import { formatCents, fromCents, toCents } from "./income";

/** The wait before the first agent starts, and how long each agent takes. Exported so tests can step through them. */
export const COPILOT_QUEUE_MS = 400;
export const AGENT_STEP_MS = 1200;
/** Who the mock says made each change. After sign-in the backend fills this in from the token. */
export const REVIEWER = "demo.reviewer";
/**
 * The demo's first run has the Critic fail once, so the failed state and "Re-run" can be seen: the report
 * still completes, with the Critic's check marked not available (Feature Design 6.5), and a re-run fixes it.
 * Set to false to see every agent succeed first time.
 */
export const FAIL_CRITIC_FIRST_RUN = true;

export type CopilotKind = "underwriting" | "lm";

/** Which cases have what the agents need. */
export const hasCopilotSeed = (kind: CopilotKind, caseId: string): boolean =>
  kind === "underwriting" ? caseId === DANIEL_CASE_ID : caseId === ANGELA_CASE_ID;

/** Everything about one run that can change: when it started, what a reviewer did to it. */
export interface CopilotRun {
  kind: CopilotKind;
  caseId: string;
  startedAtMs: number;
  /** The Critic's first try fails (see FAIL_CRITIC_FIRST_RUN). */
  failCritic: boolean;
  reruns: { agent: AgentName; startedAtMs: number }[];
  /** Underwriting: the suggested conditions and what has been done with them. */
  conditions: Condition[];
  /** Loss mitigation: the waterfall with any overrides. */
  options: WaterfallOption[];
  signOffs: SignOff[];
  reportStatus: ReportStatus;
  reportVersion: number;
  counter: number;
}

const iso = (ms: number): string => new Date(ms).toISOString();

// ---- The three agents -----------------------------------------------------------------------------

const SUMMARY: Record<CopilotKind, Record<AgentName, string>> = {
  underwriting: {
    researcher: "Looked up the guideline passage for each finding that needs guidance.",
    writer: "Drafted the report from the stored results. Every figure comes from a stored calculation.",
    critic: "Checked each figure against a stored result and each guideline statement against its passage.",
  },
  lm: {
    researcher: "Found the investor guide passage for each option the rules reached, and the Regulation X provisions that may apply.",
    writer: "Drafted the report from the stored results: the lender view first, then the options in waterfall order.",
    critic: "Checked each figure against a stored result and each citation against a retrieved passage.",
  },
};

const attemptsOf = (run: CopilotRun, agent: AgentName): number => 1 + run.reruns.filter((r) => r.agent === agent).length;

/** Where each agent stands at `now`: waiting for its turn, running, done, or failed. */
export function agentRunsAt(run: CopilotRun, now: number): AgentRun[] {
  return AGENT_ORDER.map((agent, i) => {
    const start = run.startedAtMs + COPILOT_QUEUE_MS + i * AGENT_STEP_MS;
    let status: AgentStatus = now < start ? "waiting" : now < start + AGENT_STEP_MS ? "running" : "done";
    let startedAt = start;
    if (status === "done" && agent === "critic" && run.failCritic) status = "failed";
    const lastRerun = [...run.reruns].reverse().find((r) => r.agent === agent);
    if (lastRerun) {
      startedAt = lastRerun.startedAtMs;
      status = now < startedAt + AGENT_STEP_MS ? "running" : "done";
    }
    const finishedAt = startedAt + AGENT_STEP_MS;
    return {
      agent,
      attempt: attemptsOf(run, agent),
      status,
      summary: status === "done" ? SUMMARY[run.kind][agent] : null,
      error: status === "failed" ? "The Critic did not answer in time. Re-run it to check the report." : null,
      started_at: status === "waiting" ? null : iso(startedAt),
      finished_at: status === "done" || status === "failed" ? iso(finishedAt) : null,
    };
  });
}

const busy = (runs: AgentRun[]): boolean => runs.some((r) => r.status === "waiting" || r.status === "running");

/** Starts a run. Throws 422 for a case the agents have nothing to work from. */
export function startRun(kind: CopilotKind, caseId: string, now: number, first: boolean): CopilotRun {
  if (!hasCopilotSeed(kind, caseId)) {
    throw new ApiError(422, "There is nothing for the agents to work from on this case yet.");
  }
  return {
    kind,
    caseId,
    startedAtMs: now,
    failCritic: first && FAIL_CRITIC_FIRST_RUN,
    reruns: [],
    conditions: kind === "underwriting" ? seedConditions() : [],
    options: kind === "lm" ? evaluateAngela(ANGELA_INPUTS) : [],
    signOffs: [],
    reportStatus: "draft",
    reportVersion: 1,
    counter: 0,
  };
}

/** Re-runs one agent alone. Throws 404 for an agent that does not exist and 409 while it is still running. */
export function rerunAgent(run: CopilotRun, agent: string, now: number): void {
  if (!(AGENT_ORDER as string[]).includes(agent)) throw new ApiError(404, "There is no such agent.");
  const current = agentRunsAt(run, now).find((r) => r.agent === agent);
  if (current && (current.status === "running" || current.status === "waiting")) {
    throw new ApiError(409, "That agent is still running.");
  }
  run.reruns.push({ agent: agent as AgentName, startedAtMs: now });
}

// ---- Underwriting: Daniel Reyes --------------------------------------------------------------------

// The figures are the Feature Design 6.8 worked example, the same ones the assets and income mocks work out
// (a test checks they agree). They are text, as the backend sends them; nothing here adds them up.
const calc = (id: string): EvidenceRef => ({ kind: "calculation", id });
const rule = (id: string): EvidenceRef => ({ kind: "rule", id });

type FindingSeed = Omit<Finding, "id">;

const DANIEL_FINDINGS: FindingSeed[] = [
  {
    priority: "significant",
    title: "Documented assets are 27,273.68 short of the funds to close",
    detail: "Documented assets are 9,226.32 against 36,500.00 needed to close: 36,500.00 - 9,226.32 = 27,273.68.",
    evidence: [calc("documented_assets"), calc("funds_shortfall"), rule("AL-W105")],
  },
  {
    priority: "significant",
    title: "A 2,000.00 transfer on 2026-09-22 has no documented source",
    detail: "A transfer of 2,000.00 from an individual on 2026-09-22 is above the large-deposit minimum and is not payroll.",
    evidence: [calc("large_deposit"), rule("AL-W101")],
  },
  {
    priority: "significant",
    title: "DTI is 44.70%, above the illustrative 43% review level",
    detail: "(1,980.00 + 693.00) / 5,980.00 = 44.70%. With overtime counted the figure is 41.61%.",
    evidence: [calc("dti"), calc("dti_with_overtime"), rule("AL-W106")],
  },
  {
    priority: "attention",
    title: "Overtime and bonus are excluded: their history covers 2026 only",
    detail: "Only 2026 is documented for these components, and two years are needed under the illustrative settings.",
    evidence: [rule("INC-W101")],
  },
  {
    priority: "attention",
    title: "A 30-day late payment appears 19 months before the credit report",
    detail: "The Northgate Card shows one 30-day late payment, 19 months before the report date.",
    evidence: [calc("months_since_late_payment")],
  },
  {
    priority: "attention",
    title: "The pay stubs cover 16 days fewer than the 30 days required",
    detail: "The documents in the file do not span the full 30-day period on the checklist.",
    evidence: [{ kind: "checklist", id: "pay_stubs_30_days" }],
  },
  {
    priority: "attention",
    title: "Page 3 of the August 2026 bank statement is missing",
    detail: "The statement prints three pages and two were received.",
    evidence: [rule("DI-W701")],
  },
  {
    priority: "information",
    title: "The printed net pay was corrected by a reviewer",
    detail: "The stub prints 2,083.61; gross 3,070.50 less deductions 1,036.89 is 2,033.61, which matches the bank deposits.",
    evidence: [rule("DI-CHK-06"), { kind: "document", id: PAYSTUB_DOC_ID, line_ids: ["p1-L31"] }],
  },
];

const DANIEL_CONFLICTS: Conflict[] = [
  {
    title: "DTI changes with the treatment of overtime",
    detail:
      "DTI is 44.70% with overtime and bonus left out of income, or 41.61% if overtime is counted. The underwriter decides which income to use.",
    evidence: [calc("dti"), calc("dti_with_overtime")],
    figures: [
      { label: "Overtime and bonus left out", value: "44.70%" },
      { label: "If overtime is counted", value: "41.61%" },
    ],
  },
];

const DANIEL_CONDITIONS: { text: string; priority: Condition["priority"] }[] = [
  {
    text: "Provide the source of the 2,000.00 transfer received on 2026-09-22, for example a gift letter and the donor's bank record.",
    priority: "significant",
  },
  {
    text: "Document the funds to close: 27,273.68 of the 36,500.00 needed is not yet supported by the statements on file.",
    priority: "significant",
  },
  { text: "Provide pay stubs that cover the full 30-day period before the application.", priority: "attention" },
  { text: "Provide page 3 of the August 2026 bank statement.", priority: "attention" },
  {
    text: "Provide documents covering a second year of overtime and bonus history, since 2026 is the only year on file.",
    priority: "attention",
  },
  { text: "Provide a written explanation of the 30-day late payment on the Northgate Card.", priority: "information" },
];

/** The passages the Researcher cites. They exist in mocks/guidelines.ts, so the citation opens. */
const DANIEL_GUIDELINES = [
  {
    passage_id: "fannie-selling-guide.b3-3-1-01.overtime",
    summary: "Cited for the overtime and bonus finding: the guide's history requirement for counting this income.",
  },
  {
    passage_id: "fannie-selling-guide.b3-4-2-02.large-deposits",
    summary: "Cited for the 2,000.00 transfer: how the guide treats a large deposit without a source.",
  },
];

const conditionId = (n: number): string => `uwc-${n}`;

function seedConditions(): Condition[] {
  return DANIEL_CONDITIONS.map((c, i) => ({
    id: conditionId(i + 1),
    position: i + 1,
    text: c.text,
    priority: c.priority,
    source: "agent",
    decision: "pending",
    edited_text: null,
    current_text: c.text,
    reason: null,
    decided_by: null,
    decided_at: null,
  }));
}

const DANIEL_SECTIONS: UnderwritingSections = {
  snapshot: [
    { key: "borrower", value: "Daniel Reyes" },
    { key: "loan", value: "Purchase of a primary residence" },
    { key: "property_value", value: "400000.00" },
    { key: "loan_amount", value: "360000.00" },
    { key: "ltv", value: "90.00%" },
    { key: "candidate_monthly_income", value: "5980.00" },
    { key: "dti", value: "44.70%" },
    { key: "dti_review_level", value: "43%" },
  ],
  conflicts: DANIEL_CONFLICTS,
  missing_information: ["Pay stubs for the last 16 days of the 30-day period", "Page 3 of the August 2026 bank statement"],
  potential_risks: ["The funds to close are not yet documented.", "A 2,000.00 transfer from an individual has no source on file."],
  guideline_references: DANIEL_GUIDELINES,
  note: "Illustrative sample. Every figure comes from a stored calculation; this text carries no decision.",
};

/** The underwriting report as the screen shows it at `now`. */
export function underwritingAt(run: CopilotRun, now: number): UnderwritingReport {
  const agent_runs = agentRunsAt(run, now);
  const working = busy(agent_runs);
  const critic = agent_runs.find((a) => a.agent === "critic");
  return {
    run_id: `run-uw-${run.startedAtMs}`,
    run_status: working ? "running" : "succeeded",
    report: working
      ? null
      : {
          id: `report-uw-${run.caseId}`,
          version: run.reportVersion,
          status: run.reportStatus,
          source: "agents",
          notice: null,
          created_at: iso(run.startedAtMs + COPILOT_QUEUE_MS + 3 * AGENT_STEP_MS),
          sections: structuredClone(DANIEL_SECTIONS),
          critic_missing: critic?.status === "failed",
        },
    findings: working ? [] : DANIEL_FINDINGS.map((f, i) => ({ ...structuredClone(f), id: `f-${i + 1}` })),
    conditions: working ? [] : structuredClone(run.conditions),
    agent_runs,
    sign_offs: structuredClone(run.signOffs),
  };
}

function touched(run: CopilotRun): void {
  // Any change to a report that was signed off puts it back in review; the earlier sign-off stays.
  run.reportStatus = "in_review";
}

function requireReport(run: CopilotRun, now: number): void {
  if (busy(agentRunsAt(run, now))) throw new ApiError(409, "The agents are still working. Wait for the report before reviewing it.");
}

const reasonOf = (value: string | undefined): string => (value ?? "").trim();

/** Accept, edit or reject a suggested condition. An edit needs the new text and a reason; a rejection needs a reason. */
export function decideCondition(run: CopilotRun, id: string, req: ConditionDecisionRequest, now: number): void {
  requireReport(run, now);
  const c = run.conditions.find((x) => x.id === id);
  if (!c) throw new ApiError(404, "Condition not found");
  const reason = reasonOf(req.reason);
  const edited = reasonOf(req.edited_text);
  if (req.decision === "edited" && (!edited || !reason)) throw new ApiError(422, "An edit needs the new text and a reason.");
  if (req.decision === "rejected" && !reason) throw new ApiError(422, "A rejection needs a reason.");
  if (req.decision !== "edited" && edited) throw new ApiError(422, "The new text is only for an edit.");
  c.decision = req.decision;
  c.edited_text = req.decision === "edited" ? edited : null;
  c.current_text = req.decision === "edited" ? edited : c.text; // the agents' own text is never changed
  c.reason = req.decision === "accepted" ? null : reason;
  c.decided_by = REVIEWER;
  c.decided_at = iso(now);
  touched(run);
}

/** The reviewer's own condition. It is theirs, so it starts as accepted. */
export function addCondition(run: CopilotRun, req: ConditionAddRequest, now: number): void {
  requireReport(run, now);
  const text = req.text.trim();
  if (!text) throw new ApiError(422, "A condition needs text.");
  const n = run.conditions.length + 1;
  run.conditions.push({
    id: conditionId(n),
    position: n,
    text,
    priority: req.priority,
    source: "user",
    decision: "accepted",
    edited_text: null,
    current_text: text,
    reason: null,
    decided_by: REVIEWER,
    decided_at: iso(now),
  });
  touched(run);
}

/** Records that a person reviewed this version of the report. A sign-off with undecided conditions is allowed, and says how many. */
export function signOff(run: CopilotRun, note: string | undefined, now: number): SignOffResult {
  requireReport(run, now);
  const trimmed = (note ?? "").trim();
  const entry: SignOff = {
    id: `so-${run.signOffs.length + 1}`,
    report_version: run.reportVersion,
    signed_by: REVIEWER,
    role: run.kind === "underwriting" ? "underwriter" : "lm_specialist",
    signed_at: iso(now),
    note: trimmed || null,
    statement: SIGN_OFF_STATEMENT,
  };
  run.signOffs.push(entry);
  run.reportStatus = "signed_off";
  return {
    sign_off: structuredClone(entry),
    report_status: "signed_off",
    pending_conditions: run.conditions.filter((c) => c.decision === "pending").length,
  };
}

// ---- Loss mitigation: Angela Whitfield -------------------------------------------------------------

const RULE_SET: RuleSet = {
  name: "Sample Investor A",
  version: "1",
  label: "illustrative",
  banner: "Illustrative: not an actual investor's requirements.",
};

/** What the rules read: the confirmed hardship profile, the budget, and the loan record (Feature Design 8.3). */
export const ANGELA_INPUTS = {
  duration: "unknown",
  intent: "keep",
  surplus: "-70.00",
  arrears: "5160.00",
  months_delinquent: 3,
  gross_monthly_income: "4200.00",
  contractual_payment: "1720.00",
  unpaid_balance: "212400.00",
};

/** The lender view settings, illustrative (Feature Design 8.3). */
export const LENDER_SETTINGS = {
  property_value: "265000.00",
  liquidation_discount_pct: 15,
  foreclosure_and_carrying_costs: "24000.00",
  horizon_months: 36,
  redefault_chance_pct: 30,
};

const FINAL_TERMS = "Final terms are never computed here: to be calculated under the investor's own method.";
const pid = (name: string): string => `sample-investor-a-v1.${name}`;

type Inputs = typeof ANGELA_INPUTS;

const cond = (
  id: string,
  label: string,
  expression: string,
  values: Record<string, string>,
  passage: string,
  status: WaterfallStatus,
  derived = false,
): WaterfallCondition => ({
  id,
  label,
  expression,
  values,
  passage_id: pid(passage),
  derived,
  status,
  effective_status: status,
  override: null,
});

const verdict = (ok: boolean): WaterfallStatus => (ok ? "met" : "not_met");

/** The rules, applied to what the case holds. The mock does this; the screens only show the result. */
export function evaluateAngela(inputs: Inputs): WaterfallOption[] {
  const surplus = toCents(inputs.surplus);
  const needed = Math.round(toCents(inputs.arrears) / 6);
  const target = Math.round((toCents(inputs.gross_monthly_income) * 35) / 100);
  const contractual = toCents(inputs.contractual_payment);
  const reached = (): WaterfallCondition => cond("reached", "No earlier option's conditions are met", "no earlier option met", {}, "order.1", "not_reached", true);
  const none = (): WaterfallCondition =>
    cond("rules", "The sample rule set defines no further conditions for this option", "none defined", {}, "order.1", "not_evaluable");
  const longTermOrUnknown = inputs.duration === "long_term" || inputs.duration === "unknown";

  const defs: { option: WaterfallOptionKey; conditions: WaterfallCondition[] }[] = [
    {
      option: "repayment_plan",
      conditions: [
        cond("repayment_plan.hardship_resolved", "Hardship resolved (confirmed)", "hardship.duration == resolved", { duration: inputs.duration }, "repayment-plan.1", verdict(inputs.duration === "resolved")),
        cond("repayment_plan.surplus", "Monthly surplus at least arrears / 6", "surplus >= arrears / 6", { surplus: inputs.surplus, arrears: inputs.arrears, needed: fromCents(needed) }, "repayment-plan.2", verdict(surplus >= needed)),
      ],
    },
    {
      option: "forbearance",
      conditions: [
        cond("forbearance.hardship_temporary", "Hardship temporary (confirmed)", "hardship.duration == temporary", { duration: inputs.duration }, "forbearance.1", verdict(inputs.duration === "temporary")),
      ],
    },
    {
      option: "payment_deferral",
      conditions: [
        cond("payment_deferral.hardship_resolved", "Hardship resolved (confirmed)", "hardship.duration == resolved", { duration: inputs.duration }, "payment-deferral.1", verdict(inputs.duration === "resolved")),
        cond("payment_deferral.surplus", "Surplus at the contractual payment of zero or more", "surplus >= 0", { surplus: inputs.surplus }, "payment-deferral.2", verdict(surplus >= 0)),
        cond("payment_deferral.months_delinquent", "6 or fewer months delinquent", "months_delinquent <= 6", { months_delinquent: String(inputs.months_delinquent), limit: "6" }, "payment-deferral.3", verdict(inputs.months_delinquent <= 6)),
      ],
    },
    {
      option: "loan_modification",
      conditions: [
        cond("loan_modification.hardship_long_term", "Hardship long-term or unknown (confirmed)", "hardship.duration in (long_term, unknown)", { duration: inputs.duration }, "loan-modification.1", verdict(longTermOrUnknown)),
        cond("loan_modification.intent", "Intent to keep the home (confirmed)", "hardship.intent == keep", { intent: inputs.intent }, "loan-modification.2", verdict(inputs.intent === "keep")),
        cond(
          "loan_modification.target_payment",
          "Target payment of 35% of documented gross monthly income is below the contractual payment",
          "0.35 * gross_monthly_income < contractual_payment",
          { gross_monthly_income: inputs.gross_monthly_income, target_payment: fromCents(target), contractual_payment: inputs.contractual_payment },
          "loan-modification.3",
          verdict(target < contractual),
        ),
      ],
    },
    { option: "short_sale", conditions: [{ ...reached(), id: "short_sale.reached" }, { ...none(), id: "short_sale.rules" }] },
    { option: "deed_in_lieu", conditions: [{ ...reached(), id: "deed_in_lieu.reached" }, { ...none(), id: "deed_in_lieu.rules" }] },
  ];

  const options: WaterfallOption[] = defs.map((d, i) => ({
    option: d.option,
    order_no: i + 1,
    status: "not_evaluable",
    original_status: "not_evaluable",
    conditions: d.conditions,
    overridden: false,
  }));
  recomputeWaterfall(options);
  return options;
}

// The waterfall's one status rule (backend/app/services/waterfall_status.py): an option is not reached once
// an earlier one is met; otherwise not met beats needs confirmation beats not evaluable, and met needs
// every condition met. A derived condition is set from the options before it, never by a person.
function optionStatus(conditions: WaterfallCondition[], pick: (c: WaterfallCondition) => WaterfallStatus): WaterfallStatus {
  const statuses = conditions.map(pick);
  if (statuses.includes("not_reached")) return "not_reached";
  for (const wanted of ["not_met", "needs_confirmation", "not_evaluable"] as const) if (statuses.includes(wanted)) return wanted;
  return statuses.length ? "met" : "not_evaluable";
}

/** Brings every status up to date: what the rules found, and what counts after the overrides. */
export function recomputeWaterfall(options: WaterfallOption[]): void {
  // Pass 1: the rules alone, which is what "Not met" or "Met" originally said.
  let earlierMet = false;
  for (const o of options) {
    for (const c of o.conditions) if (c.derived) c.status = earlierMet ? "not_reached" : "met";
    o.original_status = earlierMet ? "not_reached" : optionStatus(o.conditions, (c) => c.status);
    earlierMet = earlierMet || o.original_status === "met";
  }
  // Pass 2: with the overrides.
  earlierMet = false;
  for (const o of options) {
    for (const c of o.conditions) {
      c.effective_status = c.derived ? (earlierMet ? "not_reached" : "met") : (c.override?.status ?? c.status);
    }
    o.status = earlierMet ? "not_reached" : optionStatus(o.conditions, (c) => c.effective_status);
    o.overridden = o.conditions.some((c) => c.override !== null);
    earlierMet = earlierMet || o.status === "met";
  }
}

/** Override one condition, with a reason. The rules' own status stays beside it, and every option's status is recomputed. */
export function overrideCondition(run: CopilotRun, conditionId: string, req: OverrideRequest, now: number): void {
  const found = run.options.flatMap((o) => o.conditions).find((c) => c.id === conditionId);
  if (!found) throw new ApiError(404, "Condition not found");
  if (found.derived) throw new ApiError(422, "This condition follows from the options before it and cannot be overridden.");
  const reason = reasonOf(req.reason);
  if (!reason) throw new ApiError(422, "A reason is required.");
  found.override = { status: req.status, reason, by: REVIEWER, at: iso(now) };
  recomputeWaterfall(run.options);
  touched(run);
}

/** How much a modification lowers the monthly payment: the contractual payment less the target payment (35% of documented gross income). */
const paymentReduction = (inputs: Inputs): number =>
  toCents(inputs.contractual_payment) - Math.round((toCents(inputs.gross_monthly_income) * 35) / 100);

/** The lender's comparison with foreclosure, with working, in whole cents (Feature Design 8.3). */
export function buildLenderView(inputs: Inputs = ANGELA_INPUTS, settings = LENDER_SETTINGS): LenderView {
  const balance = toCents(inputs.unpaid_balance);
  const arrears = toCents(inputs.arrears);
  const value = toCents(settings.property_value);
  const costs = toCents(settings.foreclosure_and_carrying_costs);
  const discount = Math.round((value * settings.liquidation_discount_pct) / 100);
  const claim = balance + arrears;
  const recovery = value - discount - costs;
  const loss = claim - recovery;
  const reduction = paymentReduction(inputs);
  const reductionTotal = reduction * settings.horizon_months;
  const redefault = Math.round((loss * settings.redefault_chance_pct) / 100);
  const cost = reductionTotal + redefault;
  const advantage = loss - cost;
  const f = formatCents;
  const figures: LenderFigure[] = [
    { name: "foreclosure_claim", value: fromCents(claim), unit: "usd", formula: "unpaid balance + arrears", working: `${f(balance)} + ${f(arrears)} = ${f(claim)}` },
    {
      name: "foreclosure_net_recovery",
      value: fromCents(recovery),
      unit: "usd",
      formula: "property value less the liquidation discount, less foreclosure and carrying costs",
      working: `${f(value)} - ${settings.liquidation_discount_pct}% (${f(discount)}) - ${f(costs)} = ${f(recovery)}`,
    },
    { name: "foreclosure_loss", value: fromCents(loss), unit: "usd", formula: "claim - net recovery", working: `${f(claim)} - ${f(recovery)} = ${f(loss)}` },
    {
      name: "modification_payment_reduction_total",
      value: fromCents(reductionTotal),
      unit: "usd",
      formula: "monthly payment reduction x horizon months",
      working: `${f(reduction)} x ${settings.horizon_months} = ${f(reductionTotal)}`,
    },
    {
      name: "modification_expected_redefault_loss",
      value: fromCents(redefault),
      unit: "usd",
      formula: "foreclosure loss x chance of re-default",
      working: `${f(loss)} x ${settings.redefault_chance_pct}% = ${f(redefault)}`,
    },
    {
      name: "modification_cost",
      value: fromCents(cost),
      unit: "usd",
      formula: "payment reduction over the horizon + expected re-default loss",
      working: `${f(reductionTotal)} + ${f(redefault)} = ${f(cost)}`,
    },
    { name: "modification_advantage", value: fromCents(advantage), unit: "usd", formula: "foreclosure loss - modification cost", working: `${f(loss)} - ${f(cost)} = ${f(advantage)}` },
  ];
  return {
    foreclosure_loss: fromCents(loss),
    modification_cost: fromCents(cost),
    advantage: fromCents(advantage),
    settings: { ...settings },
    figures,
    final_terms: FINAL_TERMS,
  };
}

function lmSections(view: LenderView): LmSections {
  const v = (name: string) => formatCents(toCents(view.figures.find((x) => x.name === name)!.value));
  return {
    lender_view:
      `Foreclosure: a claim of ${v("foreclosure_claim")} against a net recovery of ${v("foreclosure_net_recovery")} is a loss of ${v("foreclosure_loss")}. ` +
      `Modification: a payment reduction of ${formatCents(paymentReduction(ANGELA_INPUTS))} for ${LENDER_SETTINGS.horizon_months} months (${v("modification_payment_reduction_total")}) ` +
      `plus a ${LENDER_SETTINGS.redefault_chance_pct}% chance of that loss (${v("modification_expected_redefault_loss")}) is an expected cost of ${v("modification_cost")}, which is ${v("modification_advantage")} lower. ` +
      "These figures use illustrative settings.",
    borrower_situation:
      "Income fell by 25% from July 2026 after hours were cut from 40 to 30. The borrower says they intend to keep the home.",
    missing_information: ["The August 2026 bank statement"],
    compliance_points: [
      "12 CFR 1024.41(b): notify the borrower about missing documents. The date the application was received is a fact to check.",
    ],
    items_for_human_review: ["Confirm the hardship duration and intent before relying on the waterfall."],
    note: "Illustrative sample. The rules mark one option as 'conditions met'. Nothing here is a decision.",
  };
}

/** The recommendation as the screen shows it at `now`. The rules and the lender view are code, so they are there from the start. */
export function recommendationAt(run: CopilotRun, now: number): LmRecommendation {
  const agent_runs = agentRunsAt(run, now);
  const working = busy(agent_runs);
  const critic = agent_runs.find((a) => a.agent === "critic");
  const lender = buildLenderView();
  return {
    run_id: `run-lm-${run.startedAtMs}`,
    run_status: working ? "running" : "succeeded",
    source: "rules_engine",
    notice: null,
    rule_set: { ...RULE_SET },
    waterfall: structuredClone(run.options),
    lender_view: lender,
    report: working
      ? null
      : {
          id: `report-lm-${run.caseId}`,
          version: run.reportVersion,
          status: run.reportStatus,
          source: "agents",
          notice: null,
          created_at: iso(run.startedAtMs + COPILOT_QUEUE_MS + 3 * AGENT_STEP_MS),
          sections: lmSections(lender),
          critic_missing: critic?.status === "failed",
        },
    agent_runs,
    sign_offs: structuredClone(run.signOffs),
  };
}
