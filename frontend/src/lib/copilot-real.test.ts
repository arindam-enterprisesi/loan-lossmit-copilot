import { describe, expect, it } from "vitest";
import {
  addBody,
  decisionBody,
  overrideBody,
  toAgentRuns,
  toEvidenceRef,
  toLmRecommendation,
  toLmSections,
  toSignOffResult,
  toUnderwritingReport,
  toUnderwritingSections,
} from "./copilot-real";
import { realAngelaRecommendation, realDanielReport, SAMPLE_USER_ID, sampleAgentRuns } from "./copilot-real-sample";

describe("the agents, translated", () => {
  it("shows queued as waiting and succeeded as done, with the agent's own one-line summary", () => {
    const runs = sampleAgentRuns();
    runs[1].status = "queued";
    runs[2].status = "running";
    const out = toAgentRuns(runs);
    expect(out.map((r) => [r.agent, r.status])).toEqual([
      ["researcher", "done"],
      ["writer", "waiting"],
      ["critic", "running"],
    ]);
    expect(out[0].summary).toBe("researcher summary (seeded: not run)");
  });

  it("keeps only the latest attempt of each agent", () => {
    const runs = [
      ...sampleAgentRuns(),
      { ...sampleAgentRuns()[2], attempt: 2, status: "failed" as const, error: "timed out", output: null },
    ];
    const critic = toAgentRuns(runs).find((r) => r.agent === "critic")!;
    expect(critic).toMatchObject({ attempt: 2, status: "failed", error: "timed out", summary: null });
    expect(toAgentRuns(runs)).toHaveLength(3);
  });

  it("has no summary when the agent wrote none", () => {
    const runs = sampleAgentRuns();
    runs[0].output = { other: 1 };
    expect(toAgentRuns(runs)[0].summary).toBeNull();
  });
});

describe("evidence references, translated", () => {
  it("reads each kind by its own field", () => {
    expect(toEvidenceRef({ type: "calculation", name: "dti" })).toEqual({ kind: "calculation", id: "dti" });
    expect(toEvidenceRef({ type: "rule", id: "AL-W106" })).toEqual({ kind: "rule", id: "AL-W106" });
    expect(toEvidenceRef({ type: "checklist", id: "pay_stubs_30_days" })).toEqual({ kind: "checklist", id: "pay_stubs_30_days" });
    expect(toEvidenceRef({ type: "document", document_id: "d1", line_ids: ["p1-L2"] })).toEqual({ kind: "document", id: "d1", line_ids: ["p1-L2"] });
    expect(toEvidenceRef({ type: "document", id: "d2" })).toEqual({ kind: "document", id: "d2" });
    expect(toEvidenceRef({ type: "passage", passage_id: "p1" })).toEqual({ kind: "passage", id: "p1" });
  });

  it("leaves out a reference that names nothing or is of a kind it does not know", () => {
    expect(toEvidenceRef({ type: "calculation" })).toBeNull();
    expect(toEvidenceRef({ type: "mystery", name: "x" })).toBeNull();
    expect(toEvidenceRef({})).toBeNull();
  });
});

describe("the underwriting report, translated", () => {
  const out = toUnderwritingReport(realDanielReport());

  it("keeps the run, the report and who wrote it, with the backend's notice for a seeded sample", () => {
    expect(out.run_status).toBe("succeeded");
    expect(out.report).toMatchObject({ version: 1, status: "draft", source: "seeded_sample", critic_missing: false });
    expect(out.report?.notice).toMatch(/Seeded sample/);
  });

  it("turns the snapshot object into a list, in the order sent", () => {
    expect(out.report?.sections.snapshot).toEqual([
      { key: "borrower", value: "Daniel Reyes" },
      { key: "property_value", value: "400000.00" },
      { key: "dti", value: "44.70%" },
    ]);
  });

  it("keeps the conflict with its evidence", () => {
    expect(out.report?.sections.conflicts).toEqual([
      {
        title: "DTI changes with the treatment of overtime",
        detail: expect.stringContaining("41.61%"),
        evidence: [
          { kind: "calculation", id: "dti" },
          { kind: "calculation", id: "dti_with_overtime" },
        ],
      },
    ]);
  });

  it("translates a finding's evidence, and drops what cannot be read", () => {
    expect(out.findings[0].evidence.map((e) => [e.kind, e.id])).toEqual([
      ["calculation", "dti"],
      ["rule", "AL-W106"],
      ["checklist", "pay_stubs_30_days"],
      ["document", "d1000000-0000-4000-8000-000000000001"],
      ["passage", "fannie-selling-guide.b3-3-1-01.overtime"],
    ]);
  });

  it("keeps the conditions as they came, the agents' text beside any edit", () => {
    expect(out.conditions[0]).toMatchObject({ position: 1, decision: "pending", current_text: out.conditions[0].text });
  });

  it("marks the Critic's check as not available only when the Critic failed", () => {
    const failed = realDanielReport();
    failed.agent_runs[2].status = "failed";
    expect(toUnderwritingReport(failed).report?.critic_missing).toBe(true);
    const noCritic = realDanielReport();
    noCritic.agent_runs = noCritic.agent_runs.slice(0, 2);
    expect(toUnderwritingReport(noCritic).report?.critic_missing).toBe(false);
  });

  it("shows a run that is queued as running", () => {
    const real = realDanielReport();
    real.run_status = "queued";
    expect(toUnderwritingReport(real).run_status).toBe("running");
  });

  it("copes with sections that are missing or have the wrong shape", () => {
    expect(toUnderwritingSections({})).toEqual({
      snapshot: [],
      conflicts: [],
      missing_information: [],
      potential_risks: [],
      guideline_references: [],
      note: null,
    });
    expect(toUnderwritingSections({ conflicts: "no", missing_information: [1, "yes"], snapshot: 4 }).missing_information).toEqual(["yes"]);
  });

  it("reads guideline references given as plain IDs or as objects, and skips ones with no ID", () => {
    const sections = toUnderwritingSections({
      guideline_references: ["p1", { passage_id: "p2", summary: "Why" }, { id: "p3", text: "Because" }, { summary: "no id" }, 5],
    });
    expect(sections.guideline_references).toEqual([
      { passage_id: "p1", summary: "" },
      { passage_id: "p2", summary: "Why" },
      { passage_id: "p3", summary: "Because" },
    ]);
  });
});

describe("the recommendation, translated", () => {
  const out = toLmRecommendation(realAngelaRecommendation());

  it("keeps the rule set, its banner and the seeded notice", () => {
    expect(out.rule_set).toEqual({ name: "Sample Investor A", version: "1", label: "illustrative", banner: "Illustrative: not an actual investor's requirements." });
    expect(out.source).toBe("seeded_sample");
  });

  it("keeps the waterfall with the rules' status beside the override", () => {
    const mod = out.waterfall[1];
    expect(mod).toMatchObject({ option: "loan_modification", status: "not_met", original_status: "met", overridden: true });
    expect(mod.conditions[0]).toMatchObject({
      status: "met",
      effective_status: "not_met",
      passage_id: null,
      override: { status: "not_met", reason: "Intent not yet confirmed", by: SAMPLE_USER_ID },
    });
  });

  it("writes every value the rule used as text", () => {
    expect(out.waterfall[0].conditions[0].values).toEqual({ surplus: "-70.00", arrears: "5160.00", needed: "860.00" });
    expect(out.waterfall[1].conditions[0].values).toEqual({ intent: "keep", months: "3" });
  });

  it("keeps the lender view with each figure's working", () => {
    expect(out.lender_view).toMatchObject({ foreclosure_loss: "16310.00", modification_cost: "13893.00", advantage: "2417.00" });
    expect(out.lender_view?.figures[0]).toEqual({
      name: "foreclosure_loss",
      value: "16310.00",
      unit: "usd",
      formula: "claim - net recovery",
      working: "217,560.00 - 201,250.00 = 16,310.00",
    });
  });

  it("takes the agents, the sign-offs and the report text out of the report", () => {
    expect(out.agent_runs).toHaveLength(3);
    expect(out.sign_offs).toEqual([]);
    expect(out.report?.sections.lender_view).toBe("Foreclosure: a loss of 16,310.00.");
    expect(out.report?.sections.compliance_points).toEqual(["12 CFR 1024.41(b): notify the borrower about missing documents."]);
  });

  it("has no report, agents or lender view while the agents have not written anything", () => {
    const real = realAngelaRecommendation();
    real.report = null;
    real.lender_view = null;
    real.run_status = "running";
    const early = toLmRecommendation(real);
    expect(early).toMatchObject({ report: null, lender_view: null, agent_runs: [], sign_offs: [], run_status: "running" });
  });

  it("copes with report text that is missing", () => {
    expect(toLmSections({})).toEqual({
      lender_view: "",
      borrower_situation: "",
      missing_information: [],
      compliance_points: [],
      items_for_human_review: [],
      note: null,
    });
  });
});

describe("what a person sends", () => {
  it("a decision carries only the fields it needs, trimmed", () => {
    expect(decisionBody({ decision: "accepted" })).toEqual({ decision: "accepted" });
    expect(decisionBody({ decision: "edited", edited_text: "  New  ", reason: " Why " })).toEqual({ decision: "edited", edited_text: "New", reason: "Why" });
    expect(decisionBody({ decision: "rejected", reason: " no " })).toEqual({ decision: "rejected", reason: "no" });
  });

  it("an added condition has its text and priority", () => {
    expect(addBody({ text: "  Gift letter ", priority: "significant" })).toEqual({ text: "Gift letter", priority: "significant" });
  });

  it("an override has a status and a trimmed reason", () => {
    expect(overrideBody({ status: "met", reason: "  Confirmed  " })).toEqual({ status: "met", reason: "Confirmed" });
  });

  it("a sign-off result is kept with the statement that it is not a decision", () => {
    const out = toSignOffResult({
      sign_off: {
        id: "s1",
        report_version: 2,
        signed_by: SAMPLE_USER_ID,
        role: "underwriter",
        signed_at: "2026-11-24T11:00:00Z",
        note: null,
        statement: "Records a review. Not a decision.",
      },
      report_status: "signed_off",
      pending_conditions: 3,
    });
    expect(out).toMatchObject({ report_status: "signed_off", pending_conditions: 3 });
    expect(out.sign_off.statement).toBe("Records a review. Not a decision.");
  });
});
