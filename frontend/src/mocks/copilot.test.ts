import { describe, expect, it } from "vitest";
import { figureText } from "@/lib/assets";
import { ApiError } from "@/lib/api-error";
import { formatMoney } from "@/lib/format";
import { buildDanielAssets, DANIEL_SCENARIO, DEFAULT_CANDIDATE, DEFAULT_OVERTIME } from "./assets";
import {
  addCondition,
  AGENT_STEP_MS,
  agentRunsAt,
  ANGELA_INPUTS,
  buildLenderView,
  COPILOT_QUEUE_MS,
  decideCondition,
  evaluateAngela,
  hasCopilotSeed,
  LENDER_SETTINGS,
  addAnnotation,
  overrideCondition,
  recommendationAt,
  recomputeWaterfall,
  REVIEWER,
  rerunAgent,
  signOff,
  startRun,
  underwritingAt,
} from "./copilot";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import { buildAngelaHardship } from "./hardship";

const T0 = 1_000_000;
const DONE = T0 + COPILOT_QUEUE_MS + 3 * AGENT_STEP_MS + 1;
const uw = (first = true) => startRun("underwriting", DANIEL_CASE_ID, T0, first);
const lm = (first = true) => startRun("lm", ANGELA_CASE_ID, T0, first);
const status = (run: ReturnType<typeof uw>, now: number) => agentRunsAt(run, now).map((a) => a.status);
const throwsApi = (fn: () => unknown, code: number, text?: RegExp) => {
  try {
    fn();
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).status).toBe(code);
    if (text) expect((e as ApiError).message).toMatch(text);
    return;
  }
  throw new Error("expected an ApiError");
};

describe("who has something for the agents to work on", () => {
  it("is Daniel for the underwriting copilot and Angela for the recommendation, and no one else", () => {
    expect(hasCopilotSeed("underwriting", DANIEL_CASE_ID)).toBe(true);
    expect(hasCopilotSeed("underwriting", ANGELA_CASE_ID)).toBe(false);
    expect(hasCopilotSeed("lm", ANGELA_CASE_ID)).toBe(true);
    expect(hasCopilotSeed("lm", DANIEL_CASE_ID)).toBe(false);
  });

  it("refuses to start for a case with nothing to read (422)", () => {
    throwsApi(() => startRun("underwriting", ANGELA_CASE_ID, T0, true), 422, /nothing for the agents/);
    throwsApi(() => startRun("lm", DANIEL_CASE_ID, T0, true), 422);
  });
});

describe("the three agents run one after the other", () => {
  it("are all waiting at the start, with no report yet", () => {
    const run = uw();
    expect(status(run, T0)).toEqual(["waiting", "waiting", "waiting"]);
    const view = underwritingAt(run, T0);
    expect(view.run_status).toBe("running");
    expect(view.report).toBeNull();
    expect(view.findings).toEqual([]);
    expect(view.conditions).toEqual([]);
  });

  it("start the Researcher first, then the Writer, then the Critic", () => {
    const run = uw(false);
    expect(status(run, T0 + COPILOT_QUEUE_MS + 1)).toEqual(["running", "waiting", "waiting"]);
    expect(status(run, T0 + COPILOT_QUEUE_MS + AGENT_STEP_MS + 1)).toEqual(["done", "running", "waiting"]);
    expect(status(run, T0 + COPILOT_QUEUE_MS + 2 * AGENT_STEP_MS + 1)).toEqual(["done", "done", "running"]);
    expect(status(run, DONE)).toEqual(["done", "done", "done"]);
  });

  it("give each finished agent a one-line summary and a start and finish time", () => {
    const [researcher] = agentRunsAt(uw(false), DONE);
    expect(researcher.summary).toMatch(/Looked up the guideline passage/);
    expect(researcher.started_at).not.toBeNull();
    expect(researcher.finished_at).not.toBeNull();
    expect(researcher.error).toBeNull();
  });

  it("on the first run the Critic fails, and the report still completes with the Critic's check marked not available", () => {
    const run = uw(true);
    expect(status(run, DONE)).toEqual(["done", "done", "failed"]);
    const view = underwritingAt(run, DONE);
    expect(view.run_status).toBe("succeeded");
    expect(view.report?.critic_missing).toBe(true);
    expect(agentRunsAt(run, DONE)[2].error).toMatch(/Critic did not answer/);
    expect(agentRunsAt(run, DONE)[2].summary).toBeNull();
  });

  it("on a later run every agent succeeds", () => {
    const view = underwritingAt(uw(false), DONE);
    expect(view.report?.critic_missing).toBe(false);
  });
});

describe("re-running one agent", () => {
  it("runs the failed Critic alone: attempt 2 is running, then done, and the others are untouched", () => {
    const run = uw(true);
    const at = DONE + 10;
    rerunAgent(run, "critic", at);
    const during = agentRunsAt(run, at + 1);
    expect(during.map((a) => a.status)).toEqual(["done", "done", "running"]);
    expect(during[2].attempt).toBe(2);
    expect(during[0].attempt).toBe(1);
    const after = underwritingAt(run, at + AGENT_STEP_MS + 1);
    expect(after.agent_runs.map((a) => a.status)).toEqual(["done", "done", "done"]);
    expect(after.report?.critic_missing).toBe(false);
    expect(after.report?.version).toBe(1); // a re-run does not make a new report
  });

  it("while it runs the report is not there to review", () => {
    const run = uw(true);
    rerunAgent(run, "critic", DONE);
    expect(underwritingAt(run, DONE + 1).report).toBeNull();
  });

  it("cannot be started for an agent that is still running (409) or one that does not exist (404)", () => {
    const run = uw();
    throwsApi(() => rerunAgent(run, "researcher", T0 + COPILOT_QUEUE_MS + 1), 409, /still running/);
    throwsApi(() => rerunAgent(run, "banker", DONE), 404);
  });
});

describe("the underwriting report for Daniel Reyes", () => {
  const view = underwritingAt(uw(false), DONE);

  it("has findings in the three priorities, each with evidence", () => {
    const count = (p: string) => view.findings.filter((f) => f.priority === p).length;
    expect([count("significant"), count("attention"), count("information")]).toEqual([3, 4, 1]);
    expect(view.findings.every((f) => f.evidence.length > 0)).toBe(true);
    expect(new Set(view.findings.map((f) => f.id)).size).toBe(view.findings.length);
  });

  it("shows the DTI conflict openly: 44.70%, or 41.61% if overtime is counted", () => {
    const [conflict] = view.report!.sections.conflicts;
    expect(conflict.title).toBe("DTI changes with the treatment of overtime");
    expect(conflict.figures).toEqual([
      { label: "Overtime and bonus left out", value: "44.70%" },
      { label: "If overtime is counted", value: "41.61%" },
    ]);
    expect(conflict.detail).toMatch(/The underwriter decides which income to use/);
  });

  it("agrees with the figures the assets and income mocks work out", () => {
    const assets = buildDanielAssets(
      { scenario: DANIEL_SCENARIO, candidate_monthly: DEFAULT_CANDIDATE, overtime_monthly: DEFAULT_OVERTIME },
      "2026-11-24T00:00:00Z",
    );
    const snapshot = Object.fromEntries(view.report!.sections.snapshot.map((s) => [s.key, s.value]));
    expect(snapshot.dti).toBe(figureText(assets.dti));
    expect(snapshot.ltv).toBe(figureText(assets.ltv));
    expect(snapshot.candidate_monthly_income).toBe(DEFAULT_CANDIDATE);
    const withOvertime = assets.other_figures.find((o) => o.id === "dti_with_overtime")!;
    expect(view.report!.sections.conflicts[0].figures![1].value).toBe(figureText(withOvertime.figure));
    const text = view.findings.map((f) => f.title + " " + f.detail).join(" ");
    expect(text).toContain(formatMoney(assets.documented_assets!.value));
    expect(text).toContain(formatMoney(assets.funds_shortfall!.value));
  });

  it("cites guideline passages that exist, and says it carries no decision", () => {
    expect(view.report!.sections.guideline_references.map((g) => g.passage_id)).toEqual([
      "fannie-selling-guide.b3-3-1-01.overtime",
      "fannie-selling-guide.b3-4-2-02.large-deposits",
    ]);
    expect(view.report!.sections.note).toMatch(/carries no decision/);
  });

  it("has six suggested conditions, none reviewed yet, and a draft report", () => {
    expect(view.conditions).toHaveLength(6);
    expect(view.conditions.every((c) => c.decision === "pending" && c.source === "agent" && c.current_text === c.text)).toBe(true);
    expect(view.report!.status).toBe("draft");
    expect(view.sign_offs).toEqual([]);
  });
});

describe("reviewing the conditions", () => {
  const ready = () => uw(false);
  const id = (n: number) => `uwc-${n}`;
  const condition = (run: ReturnType<typeof uw>, n: number) => underwritingAt(run, DONE).conditions.find((c) => c.id === id(n))!;

  it("accepting records who and when, and puts the report in review", () => {
    const run = ready();
    decideCondition(run, id(1), { decision: "accepted" }, DONE);
    expect(condition(run, 1)).toMatchObject({ decision: "accepted", decided_by: REVIEWER, reason: null });
    expect(condition(run, 1).decided_at).not.toBeNull();
    expect(underwritingAt(run, DONE).report!.status).toBe("in_review");
  });

  it("an edit keeps what the agents wrote beside the reviewer's version, and the reason", () => {
    const run = ready();
    const original = condition(run, 3).text;
    decideCondition(run, id(3), { decision: "edited", edited_text: "  Provide the two most recent pay stubs.  ", reason: " Shorter ask " }, DONE);
    expect(condition(run, 3)).toMatchObject({
      decision: "edited",
      text: original,
      edited_text: "Provide the two most recent pay stubs.",
      current_text: "Provide the two most recent pay stubs.",
      reason: "Shorter ask",
    });
  });

  it("rejecting needs a reason, and keeps the condition on the list", () => {
    const run = ready();
    throwsApi(() => decideCondition(run, id(6), { decision: "rejected" }, DONE), 422, /needs a reason/);
    throwsApi(() => decideCondition(run, id(6), { decision: "rejected", reason: "   " }, DONE), 422);
    decideCondition(run, id(6), { decision: "rejected", reason: "not required for this file" }, DONE);
    expect(condition(run, 6)).toMatchObject({ decision: "rejected", reason: "not required for this file" });
    expect(underwritingAt(run, DONE).conditions).toHaveLength(6);
  });

  it("an edit needs both the new text and a reason, and new text only comes with an edit", () => {
    const run = ready();
    throwsApi(() => decideCondition(run, id(1), { decision: "edited", reason: "x" }, DONE), 422);
    throwsApi(() => decideCondition(run, id(1), { decision: "edited", edited_text: "x" }, DONE), 422);
    throwsApi(() => decideCondition(run, id(1), { decision: "accepted", edited_text: "x" }, DONE), 422);
  });

  it("accepting after an edit puts the agents' own text back", () => {
    const run = ready();
    decideCondition(run, id(2), { decision: "edited", edited_text: "Changed", reason: "why" }, DONE);
    decideCondition(run, id(2), { decision: "accepted" }, DONE + 5);
    expect(condition(run, 2)).toMatchObject({ decision: "accepted", edited_text: null, current_text: condition(run, 2).text, reason: null });
  });

  it("refuses an unknown condition (404) and any review while the agents are still working (409)", () => {
    throwsApi(() => decideCondition(ready(), "nope", { decision: "accepted" }, DONE), 404);
    throwsApi(() => decideCondition(ready(), id(1), { decision: "accepted" }, T0 + 5), 409, /still working/);
    throwsApi(() => addCondition(ready(), { text: "x", priority: "attention" }, T0 + 5), 409);
    throwsApi(() => signOff(ready(), undefined, T0 + 5), 409);
  });

  it("a reviewer's own condition is added with their name, as accepted, and needs text", () => {
    const run = ready();
    addCondition(run, { text: "  Provide the gift letter.  ", priority: "significant" }, DONE);
    const added = underwritingAt(run, DONE).conditions[6];
    expect(added).toMatchObject({
      id: id(7),
      position: 7,
      text: "Provide the gift letter.",
      priority: "significant",
      source: "user",
      decision: "accepted",
      decided_by: REVIEWER,
    });
    throwsApi(() => addCondition(run, { text: "   ", priority: "attention" }, DONE), 422, /needs text/);
  });
});

describe("signing off", () => {
  it("records a review, with the statement that it is not a decision, and says how many conditions were left", () => {
    const run = uw(false);
    decideCondition(run, "uwc-1", { decision: "accepted" }, DONE);
    const result = signOff(run, "  Looks complete  ", DONE + 1);
    expect(result.report_status).toBe("signed_off");
    expect(result.pending_conditions).toBe(5);
    expect(result.sign_off).toMatchObject({
      report_version: 1,
      signed_by: REVIEWER,
      role: "underwriter",
      note: "Looks complete",
      statement: "Records a review. Not a decision.",
    });
    expect(underwritingAt(run, DONE + 2).report!.status).toBe("signed_off");
  });

  it("a change after a sign-off puts the report back in review and keeps the earlier sign-off", () => {
    const run = uw(false);
    signOff(run, undefined, DONE);
    decideCondition(run, "uwc-1", { decision: "accepted" }, DONE + 1);
    const view = underwritingAt(run, DONE + 2);
    expect(view.report!.status).toBe("in_review");
    expect(view.sign_offs).toHaveLength(1);
    signOff(run, undefined, DONE + 3);
    expect(underwritingAt(run, DONE + 4).sign_offs).toHaveLength(2);
  });

  it("has no note when none was given", () => {
    expect(signOff(uw(false), "   ", DONE).sign_off.note).toBeNull();
  });

  it("is the specialist's review for the recommendation", () => {
    expect(signOff(lm(false), undefined, DONE).sign_off.role).toBe("lm_specialist");
  });
});

describe("the sample investor's rules applied to Angela Whitfield", () => {
  const options = evaluateAngela(ANGELA_INPUTS);
  const byKey = (k: string) => options.find((o) => o.option === k)!;

  it("finds repayment plan, forbearance and payment deferral not met, the modification met, and the last two not reached", () => {
    expect(options.map((o) => [o.option, o.status])).toEqual([
      ["repayment_plan", "not_met"],
      ["forbearance", "not_met"],
      ["payment_deferral", "not_met"],
      ["loan_modification", "met"],
      ["short_sale", "not_reached"],
      ["deed_in_lieu", "not_reached"],
    ]);
    expect(options.map((o) => o.order_no)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("works out the values each condition used: 860.00 needed (5,160.00 / 6) and a target payment of 1,470.00 (35% of 4,200.00)", () => {
    const surplus = byKey("repayment_plan").conditions[1];
    expect(surplus.values).toEqual({ surplus: "-70.00", arrears: "5160.00", needed: "860.00" });
    expect(surplus.status).toBe("not_met");
    const target = byKey("loan_modification").conditions[2];
    expect(target.values).toEqual({ gross_monthly_income: "4200.00", target_payment: "1470.00", contractual_payment: "1720.00" });
    expect(target.status).toBe("met");
  });

  it("finds 3 months delinquent within the limit of 6, even though the option is not met", () => {
    const months = byKey("payment_deferral").conditions[2];
    expect(months).toMatchObject({ status: "met", values: { months_delinquent: "3", limit: "6" } });
    expect(byKey("payment_deferral").conditions.map((c) => c.status)).toEqual(["not_met", "not_met", "met"]);
  });

  it("gives every rule the passage of the investor guide it comes from", () => {
    const rules = options.flatMap((o) => o.conditions);
    expect(rules.every((c) => c.passage_id?.startsWith("sample-investor-a-v1."))).toBe(true);
    expect(byKey("repayment_plan").conditions[1].passage_id).toBe("sample-investor-a-v1.repayment-plan.2");
  });

  it("marks the two last options' first condition as derived: it follows from the options before them", () => {
    for (const k of ["short_sale", "deed_in_lieu"]) {
      const [reached, rules] = byKey(k).conditions;
      expect(reached).toMatchObject({ derived: true, status: "not_reached" });
      expect(rules).toMatchObject({ derived: false, status: "not_evaluable" });
    }
  });

  it("starts with nothing overridden, and every effective status equal to the rules' own", () => {
    expect(options.every((o) => !o.overridden && o.original_status === o.status)).toBe(true);
    expect(options.flatMap((o) => o.conditions).every((c) => c.override === null && c.effective_status === c.status)).toBe(true);
  });

  it("agrees with the hardship mock on the surplus and the arrears", () => {
    const hardship = buildAngelaHardship("2026-11-24T00:00:00Z");
    const surplus = hardship.measures.find((m) => m.id === "surplus")!;
    expect(surplus.compare?.value).toBe(ANGELA_INPUTS.surplus);
    expect(hardship.measures.some((m) => m.value === ANGELA_INPUTS.arrears)).toBe(true);
  });

  it("reads a different case differently: a hardship that is resolved makes a repayment plan possible", () => {
    const resolved = evaluateAngela({ ...ANGELA_INPUTS, duration: "resolved", surplus: "900.00" });
    expect(resolved.find((o) => o.option === "repayment_plan")!.status).toBe("met");
    // the waterfall stops at the first option that is met, so the modification is not reached
    expect(resolved.find((o) => o.option === "loan_modification")!.status).toBe("not_reached");
  });
});

describe("overriding a waterfall condition", () => {
  const ready = () => lm(false);
  const options = (run: ReturnType<typeof lm>) => recommendationAt(run, DONE).waterfall;
  const option = (run: ReturnType<typeof lm>, k: string) => options(run).find((o) => o.option === k)!;

  it("keeps the rules' own status beside the override, and recomputes the option and the ones after it", () => {
    const run = ready();
    overrideCondition(run, "loan_modification.target_payment", { status: "not_met", reason: " Income documents are being re-checked " }, DONE);
    const mod = option(run, "loan_modification");
    const target = mod.conditions[2];
    expect(target).toMatchObject({ status: "met", effective_status: "not_met" });
    expect(target.override).toMatchObject({ status: "not_met", reason: "Income documents are being re-checked", by: REVIEWER });
    expect(mod).toMatchObject({ status: "not_met", original_status: "met", overridden: true });
    // the waterfall now reaches short sale and deed-in-lieu; no rules are defined for them
    expect(option(run, "short_sale")).toMatchObject({ status: "not_evaluable", original_status: "not_reached" });
    expect(option(run, "short_sale").conditions[0]).toMatchObject({ status: "not_reached", effective_status: "met" });
  });

  it("an override that makes an earlier option met stops the waterfall there", () => {
    const run = ready();
    overrideCondition(run, "repayment_plan.hardship_resolved", { status: "met", reason: "Confirmed with the borrower" }, DONE);
    overrideCondition(run, "repayment_plan.surplus", { status: "met", reason: "Budget adjusted" }, DONE);
    expect(option(run, "repayment_plan")).toMatchObject({ status: "met", original_status: "not_met", overridden: true });
    expect(option(run, "loan_modification")).toMatchObject({ status: "not_reached", original_status: "met" });
  });

  it("'needs confirmation' beats 'not evaluable' and loses to 'not met'", () => {
    const run = ready();
    overrideCondition(run, "loan_modification.intent", { status: "needs_confirmation", reason: "Intent not yet confirmed" }, DONE);
    expect(option(run, "loan_modification").status).toBe("needs_confirmation");
  });

  it("needs a reason (422), cannot touch a derived condition (422), and knows when a condition is missing (404)", () => {
    const run = ready();
    throwsApi(() => overrideCondition(run, "loan_modification.intent", { status: "not_met", reason: "   " }, DONE), 422, /reason is required/);
    throwsApi(() => overrideCondition(run, "short_sale.reached", { status: "met", reason: "x" }, DONE), 422, /cannot be overridden/);
    throwsApi(() => overrideCondition(run, "nothing", { status: "met", reason: "x" }, DONE), 404);
    expect(options(run).every((o) => !o.overridden)).toBe(true);
  });

  it("overriding again replaces the earlier override but the rules' status is still there", () => {
    const run = ready();
    overrideCondition(run, "loan_modification.intent", { status: "not_met", reason: "first" }, DONE);
    overrideCondition(run, "loan_modification.intent", { status: "met", reason: "second" }, DONE + 1);
    const intent = option(run, "loan_modification").conditions[1];
    expect(intent).toMatchObject({ status: "met", effective_status: "met" });
    expect(intent.override?.reason).toBe("second");
  });

  it("recomputing with no overrides gives the same statuses the rules found", () => {
    const fresh = evaluateAngela(ANGELA_INPUTS);
    const again = structuredClone(fresh);
    recomputeWaterfall(again);
    expect(again).toEqual(fresh);
  });
});

describe("notes on the recommendation", () => {
  it("adds a trimmed note on one part, with who and when, and shows it in the recommendation", () => {
    const run = lm(false);
    addAnnotation(run, { section: "lender_view", text: "  Confirm the property value with the servicer  " }, DONE);
    const notes = recommendationAt(run, DONE).annotations;
    expect(notes).toEqual([
      { id: "an-1", section: "lender_view", text: "Confirm the property value with the servicer", by: "demo.reviewer", at: new Date(DONE).toISOString() },
    ]);
  });

  it("keeps every note in the order written, and never changes what the agents wrote", () => {
    const run = lm(false);
    const before = JSON.stringify(recommendationAt(run, DONE).report?.sections);
    addAnnotation(run, { section: "waterfall", text: "first" }, DONE);
    addAnnotation(run, { section: "waterfall", text: "second" }, DONE + 1);
    expect(recommendationAt(run, DONE + 2).annotations.map((a) => a.text)).toEqual(["first", "second"]);
    expect(JSON.stringify(recommendationAt(run, DONE + 2).report?.sections)).toBe(before);
  });

  it("refuses a blank note, an unknown part and a very long note (422), and a note while the agents work (409)", () => {
    const run = lm(false);
    throwsApi(() => addAnnotation(run, { section: "waterfall", text: "   " }, DONE), 422, /needs text/);
    throwsApi(() => addAnnotation(run, { section: "nothing" as never, text: "x" }, DONE), 422, /Choose a part/);
    throwsApi(() => addAnnotation(run, { section: "waterfall", text: "x".repeat(1001) }, DONE), 422, /at most 1000/);
    throwsApi(() => addAnnotation(run, { section: "waterfall", text: "x" }, T0 + 1), 409);
    expect(recommendationAt(run, DONE).annotations).toEqual([]);
  });

  it("puts a signed-off report back in review, and keeps the sign-off", () => {
    const run = lm(false);
    signOff(run, undefined, DONE);
    addAnnotation(run, { section: "compliance_points", text: "Check the date again" }, DONE + 1);
    const rec = recommendationAt(run, DONE + 2);
    expect(rec.report?.status).toBe("in_review");
    expect(rec.sign_offs).toHaveLength(1);
  });

  it("starts a new run with no notes", () => {
    const run = lm(false);
    addAnnotation(run, { section: "waterfall", text: "x" }, DONE);
    expect(recommendationAt(lm(false), DONE).annotations).toEqual([]);
  });
});

describe("the lender view", () => {
  const view = buildLenderView();
  const figure = (name: string) => view.figures.find((f) => f.name === name)!;

  it("works out the foreclosure loss of 16,310.00, the modification cost of 13,893.00 and the advantage of 2,417.00", () => {
    expect([view.foreclosure_loss, view.modification_cost, view.advantage]).toEqual(["16310.00", "13893.00", "2417.00"]);
  });

  it("shows the working of every figure, ending in its value", () => {
    expect(figure("foreclosure_claim").working).toBe("212,400.00 + 5,160.00 = 217,560.00");
    expect(figure("foreclosure_net_recovery").working).toBe("265,000.00 - 15% (39,750.00) - 24,000.00 = 201,250.00");
    expect(figure("foreclosure_loss").working).toBe("217,560.00 - 201,250.00 = 16,310.00");
    expect(figure("modification_payment_reduction_total").working).toBe("250.00 x 36 = 9,000.00");
    expect(figure("modification_expected_redefault_loss").working).toBe("16,310.00 x 30% = 4,893.00");
    expect(figure("modification_cost").working).toBe("9,000.00 + 4,893.00 = 13,893.00");
    expect(figure("modification_advantage").working).toBe("16,310.00 - 13,893.00 = 2,417.00");
    for (const f of view.figures) expect(f.working.endsWith(`= ${formatMoney(f.value)}`)).toBe(true);
  });

  it("lists the illustrative settings and says final terms are never computed here", () => {
    expect(view.settings).toEqual({
      property_value: "265000.00",
      liquidation_discount_pct: 15,
      foreclosure_and_carrying_costs: "24000.00",
      horizon_months: 36,
      redefault_chance_pct: 30,
    });
    expect(view.final_terms).toMatch(/Final terms are never computed here/);
  });

  it("changes when the settings change, because the mock works it out", () => {
    const other = buildLenderView(ANGELA_INPUTS, { ...LENDER_SETTINGS, redefault_chance_pct: 50 });
    expect(other.modification_cost).toBe("17155.00"); // 9,000.00 + 50% of 16,310.00
    expect(other.advantage).toBe("-845.00");
  });
});

describe("the recommendation for Angela Whitfield", () => {
  it("has the rules, the lender view and the sample rule set from the moment it starts", () => {
    const view = recommendationAt(lm(), T0);
    expect(view.run_status).toBe("running");
    expect(view.report).toBeNull();
    expect(view.waterfall).toHaveLength(6);
    expect(view.lender_view?.advantage).toBe("2417.00");
    expect(view.rule_set).toEqual({
      name: "Sample Investor A",
      version: "1",
      label: "illustrative",
      banner: "Illustrative: not an actual investor's requirements.",
    });
  });

  it("writes the report when the agents are done, with the lender view first and the figures from the stored results", () => {
    const view = recommendationAt(lm(false), DONE);
    expect(view.run_status).toBe("succeeded");
    const sections = view.report!.sections;
    expect(sections.lender_view).toContain("a loss of 16,310.00");
    expect(sections.lender_view).toContain("an expected cost of 13,893.00, which is 2,417.00 lower");
    expect(sections.lender_view).toContain("payment reduction of 250.00 for 36 months (9,000.00)");
    expect(sections.compliance_points[0]).toMatch(/12 CFR 1024\.41\(b\)/);
    expect(sections.missing_information).toEqual(["The August 2026 bank statement"]);
    expect(sections.note).toMatch(/Nothing here is a decision/);
  });

  it("the Critic fails on the first run here too, and a re-run fixes it", () => {
    const run = lm(true);
    expect(recommendationAt(run, DONE).report!.critic_missing).toBe(true);
    rerunAgent(run, "critic", DONE);
    expect(recommendationAt(run, DONE + AGENT_STEP_MS + 5).report!.critic_missing).toBe(false);
  });
});
