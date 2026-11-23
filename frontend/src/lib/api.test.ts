import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { realDanielAssets, realDanielScenario } from "./assets-real-sample";
import { realDanielIncome } from "./income-real-sample";
import { realAngelaHardship } from "./hardship-real-sample";

// api.ts reads NEXT_PUBLIC_USE_MOCKS once when it loads, so each test loads a fresh copy.
const loadApi = async (useMocks: "true" | "false") => {
  vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", useMocks);
  vi.resetModules();
  return import("./api");
};

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const doc = { id: "d1", case_id: "c1", file_name: "scan.jpg", status: "processing", flags: [] };
const job = { id: "j1", status: "queued", progress: 0 };

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("real mode: where a call goes, and when the session ends", () => {
  it("the browser calls this app's own /api/proxy, never the backend directly", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, { items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { listDocuments } = await loadApi("false");
    await listDocuments("c1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/cases/c1/documents");
    expect(fetchMock.mock.calls[0][1].headers?.Authorization).toBeUndefined(); // the proxy adds the token, not a script
  });

  it("a 401 sends the person to sign in again, and the call still fails with a clear message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(401, { message: "Sign in to continue." })));
    const api = await loadApi("false");
    const redirect = vi.spyOn(api.sessionEnded, "redirect").mockImplementation(() => {});
    await expect(api.listDocuments("c1")).rejects.toMatchObject({ status: 401, message: "Sign in to continue." });
    expect(redirect).toHaveBeenCalledTimes(1);
  });

  it("another error does not end the session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(403, { message: "Not allowed" })));
    const api = await loadApi("false");
    const redirect = vi.spyOn(api.sessionEnded, "redirect").mockImplementation(() => {});
    await expect(api.listDocuments("c1")).rejects.toMatchObject({ status: 403 });
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("income analysis calls", () => {
  it("real mode: POSTs the run (the backend answers { job, analysis_id }) and GETs the latest result, translated", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(202, { job, analysis_id: "a1" }))
      .mockResolvedValueOnce(reply(200, realDanielIncome()));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestIncome, runIncomeAnalysis } = await loadApi("false");

    expect((await runIncomeAnalysis("c1")).id).toBe("j1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/cases/c1/income-analysis");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");

    const latest = await getLatestIncome("c1");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/proxy/cases/c1/income-analysis/latest");
    expect(latest.case_id).toBe("c1");
    expect(latest.candidate_monthly.value).toBe("5980.00");
    expect(latest.components.map((c) => c.kind)).toEqual(["base_pay", "overtime", "bonus"]);
  });

  it("real mode: a 404 before the first run becomes an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "No analysis yet" })));
    const { getLatestIncome } = await loadApi("false");
    await expect(getLatestIncome("c1")).rejects.toMatchObject({ status: 404, message: "No analysis yet" });
  });

  it("mock mode: runs for Daniel and does not call the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { runIncomeAnalysis } = await loadApi("true");
    const started = await runIncomeAnalysis("11111111-1111-4111-8111-111111111111");
    expect(started.kind).toBe("income_analysis");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("include or exclude an income component", () => {
  it("real mode: PATCHes the decision with a trimmed reason and returns the new analysis, translated", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realDanielIncome()));
    vi.stubGlobal("fetch", fetchMock);
    const { setIncomeComponent } = await loadApi("false");

    const a = await setIncomeComponent("c1", "33333333-3333-4333-8333-000000000002", { included: true, reason: "  Employer letter  " });
    expect(a.id).toBe("99999999-9999-4999-8999-000000000003");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/cases/c1/income-analysis/latest/components/33333333-3333-4333-8333-000000000002");
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ included: true, reason: "Employer letter" });
  });

  it("real mode: a 422 for a missing reason becomes an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(422, { message: "A reason is required" })));
    const { setIncomeComponent } = await loadApi("false");
    await expect(setIncomeComponent("c1", "overtime", { included: true, reason: "" })).rejects.toMatchObject({
      status: 422,
    });
  });

  it("mock mode: answers from the mock store (404 before a run) and does not call the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { setIncomeComponent } = await loadApi("true");
    await expect(
      setIncomeComponent("11111111-1111-4111-8111-111111111111", "overtime", { included: true, reason: "ok" }),
    ).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("completeness calls", () => {
  const result = { id: "r1", case_id: "c1", checklist_id: "pillar1-wage-earner", items: [], outstanding: [] };

  it("real mode: POSTs the checklist id and GETs the latest result from the contract paths", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(200, result)).mockResolvedValueOnce(reply(200, result));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestCompleteness, runCompleteness } = await loadApi("false");

    expect((await runCompleteness("c1", "pillar1-wage-earner@1")).id).toBe("r1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/completeness$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ checklist_id: "pillar1-wage-earner@1" });

    expect((await getLatestCompleteness("c1")).id).toBe("r1");
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/cases\/c1\/completeness\/latest$/);
  });

  it("real mode: a 404 before the first run becomes an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "No result yet" })));
    const { getLatestCompleteness } = await loadApi("false");
    await expect(getLatestCompleteness("c1")).rejects.toMatchObject({ status: 404, message: "No result yet" });
  });

  it("real mode: PATCHes the override with an action and a trimmed reason", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, result));
    vi.stubGlobal("fetch", fetchMock);
    const { overrideCompletenessItem } = await loadApi("false");

    expect((await overrideCompletenessItem("c1", "w2_two_years", "  Letter received  ")).id).toBe("r1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/cases/c1/completeness/latest/items/w2_two_years");
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ action: "override", reason: "Letter received" });
  });

  it("mock mode: runs for Angela and does not call the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { runCompleteness } = await loadApi("true");
    const r = await runCompleteness("22222222-2222-4222-8222-222222222222", "pillar2-hardship@1");
    expect(r.overall_status).toBe("incomplete");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("hardship assessment calls", () => {
  it("real mode: POSTs the run (the backend answers { job }) and GETs the latest result, translated", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(202, { job }))
      .mockResolvedValueOnce(reply(200, realAngelaHardship()));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestHardship, runHardshipAssessment } = await loadApi("false");

    expect((await runHardshipAssessment("c1")).id).toBe("j1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/hardship-assessment$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");

    const latest = await getLatestHardship("c1");
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/cases\/c1\/hardship-assessment\/latest$/);
    expect(latest.id).toBe("99999999-9999-4999-8999-000000000001");
    expect(latest.case_id).toBe("c1");
    expect(latest.profile.map((p) => p.value_label)).toEqual(["Reduction in income", "July 2026", "Unknown", "Keep the home"]);
    expect(latest.measures.find((m) => m.id === "surplus")?.value).toBe("-280.00");
  });

  it("real mode: a 404 before the first run becomes an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "No assessment yet" })));
    const { getLatestHardship } = await loadApi("false");
    await expect(getLatestHardship("c1")).rejects.toMatchObject({ status: 404, message: "No assessment yet" });
  });

  it("real mode: PUTs a confirmation naming the item, and a correction with a trimmed value and reason", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realAngelaHardship())); // a fresh body each call
    vi.stubGlobal("fetch", fetchMock);
    const { confirmProfileItem } = await loadApi("false");

    await confirmProfileItem("c1", { key: "intent", action: "confirm" });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/hardship-assessment\/latest\/confirmations$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ intent: {} });

    await confirmProfileItem("c1", { key: "duration", action: "correct", value: " long_term ", reason: "  Letter from employer  " });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      duration: { value: "long_term", reason: "Letter from employer" },
    });
  });

  it("real mode: PATCHes a budget line with the adjusted amount as trimmed text, and a trimmed reason", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realAngelaHardship()));
    vi.stubGlobal("fetch", fetchMock);
    const { adjustBudgetItem } = await loadApi("false");

    const result = await adjustBudgetItem("c1", "44444444-4444-4444-8444-000000000005", {
      amount: " 200.00 ",
      reason: "  One-off repair  ",
    });
    expect(result.budget.lines).toHaveLength(5); // the answer is translated too
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/hardship-assessment\/latest\/budget\/44444444-4444-4444-8444-000000000005$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ adjusted_amount: "200.00", reason: "One-off repair" });
  });

  it("real mode: a 422 for a missing reason becomes an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(422, { message: "A reason is required" })));
    const { adjustBudgetItem } = await loadApi("false");
    await expect(adjustBudgetItem("c1", "other", { amount: "200.00", reason: "" })).rejects.toMatchObject({ status: 422 });
  });

  it("mock mode: runs for Angela and does not call the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { runHardshipAssessment } = await loadApi("true");
    const started = await runHardshipAssessment("22222222-2222-4222-8222-222222222222");
    expect(started.kind).toBe("hardship_assessment");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("asset and liability calls", () => {
  const caseId = "11111111-1111-4111-8111-111111111111";

  it("real mode: GETs the loan scenario, and PUTs exactly the six fields as trimmed text", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realDanielScenario()));
    vi.stubGlobal("fetch", fetchMock);
    const { getLoanScenario, putLoanScenario } = await loadApi("false");

    expect((await getLoanScenario(caseId)).funds_to_close).toBe("36500.00");
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/proxy/cases/${caseId}/loan-scenario`);

    await putLoanScenario(caseId, {
      purpose: " purchase ",
      occupancy: "primary residence",
      property_value: " 400000.00 ",
      loan_amount: "360000.00",
      proposed_housing_payment: "1980.00",
      funds_to_close: "36500.00",
    });
    expect(fetchMock.mock.calls[1][1].method).toBe("PUT");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      purpose: "purchase",
      occupancy: "primary residence",
      property_value: "400000.00",
      loan_amount: "360000.00",
      proposed_housing_payment: "1980.00",
      funds_to_close: "36500.00",
    });
  });

  it("real mode: a 404 for a case with no scenario becomes an ApiError, and a 422 keeps the backend's message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "No loan scenario has been entered for this case" })));
    const { getLoanScenario } = await loadApi("false");
    await expect(getLoanScenario(caseId)).rejects.toMatchObject({ status: 404 });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(422, { message: "property_value must be greater than 0" })));
    const api = await loadApi("false");
    await expect(
      api.putLoanScenario(caseId, { purpose: "p", occupancy: "o", property_value: "0", loan_amount: "0", proposed_housing_payment: "0", funds_to_close: "0" }),
    ).rejects.toMatchObject({ status: 422, message: "property_value must be greater than 0" });
  });

  it("real mode: POSTs the run (the backend answers { job, analysis_id }) and GETs the latest result, translated", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(202, { job, analysis_id: "a1" }))
      .mockResolvedValueOnce(reply(200, realDanielAssets()));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestAssetAnalysis, runAssetAnalysis } = await loadApi("false");

    expect((await runAssetAnalysis(caseId)).id).toBe("j1");
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/proxy/cases/${caseId}/asset-liability`);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");

    const latest = await getLatestAssetAnalysis(caseId);
    expect(fetchMock.mock.calls[1][0]).toBe(`/api/proxy/cases/${caseId}/asset-liability/latest`);
    expect(latest.case_id).toBe(caseId);
    expect([latest.documented_assets?.value, latest.dti?.value, latest.dti?.unit]).toEqual(["9226.32", "44.70", "percent"]);
  });

  it("real mode: PATCHes a transaction with a category, or with sourced, and a trimmed reason", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realDanielAssets()));
    vi.stubGlobal("fetch", fetchMock);
    const { reviewTransaction } = await loadApi("false");

    const result = await reviewTransaction(caseId, "t-1", { category: "refund", reason: "  Returned item  " });
    expect(result.obligations).toHaveLength(3); // the answer is translated too
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/proxy/cases/${caseId}/asset-liability/latest/transactions/t-1`);
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ category: "refund", reason: "Returned item" });

    await reviewTransaction(caseId, "t-2", { sourced: true, reason: "Gift letter" });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ sourced: true, reason: "Gift letter" });
  });

  it("real mode: PATCHes an obligation with the choice and a trimmed reason", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realDanielAssets()));
    vi.stubGlobal("fetch", fetchMock);
    const { reviewObligation } = await loadApi("false");

    await reviewObligation(caseId, "o-1", { counts_toward_dti: false, reason: "  Deferred  " });
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/proxy/cases/${caseId}/asset-liability/latest/obligations/o-1`);
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ counts_toward_dti: false, reason: "Deferred" });
  });

  it("mock mode: reads Daniel's scenario, runs, and does not call the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { getLoanScenario, runAssetAnalysis } = await loadApi("true");
    expect((await getLoanScenario(caseId)).purpose).toBe("purchase");
    expect((await runAssetAnalysis(caseId)).kind).toBe("asset_analysis");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("guideline calls", () => {
  const answer = {
    id: "a1",
    question: "How is overtime income evaluated?",
    source_set: "all",
    case_id: null,
    asked_at: "2026-11-23T09:00:00Z",
    status: "answered",
    sentences: [],
    citations: [],
    passages: [],
    comparison: null,
    facts_to_check: [],
    notice: null,
    removed_sentences: 0,
  };

  it("real mode: GETs the sources and a passage by ID, translated (the backend sends no page or version)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(200, { items: [{ id: "reg-x-1024-41", title: "12 CFR 1024.41", kind: "regulation", label: "illustrative", passage_count: 3 }] }))
      .mockResolvedValueOnce(
        reply(200, { id: "reg-x-1024-41.b", source_id: "reg-x-1024-41", source_title: "12 CFR 1024.41", heading: "b", text: "t", label: "illustrative", notice: "Seeded sample" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { getGuidelinePassage, listGuidelineSources } = await loadApi("false");

    expect((await listGuidelineSources())[0]).toMatchObject({ id: "reg-x-1024-41", label: "illustrative", passage_count: 3 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/guidelines/sources");

    const p = await getGuidelinePassage("reg-x-1024-41.b");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/proxy/guidelines/passages/reg-x-1024-41.b");
    expect(p).toMatchObject({ page: null, version: null, notice: "Seeded sample" });
  });

  it("real mode: a passage ID is put in the address safely, and a 404 becomes an ApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(404, { message: "Passage not found" }));
    vi.stubGlobal("fetch", fetchMock);
    const { getGuidelinePassage } = await loadApi("false");
    await expect(getGuidelinePassage("a/b c")).rejects.toMatchObject({ status: 404, message: "Passage not found" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/guidelines/passages/a%2Fb%20c");
  });

  it("real mode: POSTs the question with the source set and the case, and trims the question", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, answer));
    vi.stubGlobal("fetch", fetchMock);
    const { askGuideline } = await loadApi("false");
    const result = await askGuideline("  How is overtime income evaluated?  ", "guidelines", "c1");
    expect(result.id).toBe("a1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/guidelines/ask");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: "How is overtime income evaluated?", source_set: "guidelines", case_id: "c1" });
  });

  it("real mode: a backend without the question endpoint gets a plain message, not a raw 404", async () => {
    for (const status of [404, 405]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(status, { detail: "Not Found" })));
      const { askGuideline } = await loadApi("false");
      await expect(askGuideline("q", "all", null)).rejects.toMatchObject({
        status,
        message: expect.stringContaining("not available on this backend yet"),
      });
    }
  });

  it("real mode: another error keeps the backend's message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(422, { message: "A question can be at most 1000 characters" })));
    const { askGuideline } = await loadApi("false");
    await expect(askGuideline("q", "all", null)).rejects.toMatchObject({ status: 422, message: "A question can be at most 1000 characters" });
  });

  it("real mode: POSTs feedback with a trimmed note, or none", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const { sendGuidelineFeedback } = await loadApi("false");
    await sendGuidelineFeedback("a1", "wrongly_cited", "  Marker 2 is the wrong section  ");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/guidelines/answers/a1/feedback");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ rating: "wrongly_cited", note: "Marker 2 is the wrong section" });
    await sendGuidelineFeedback("a1", "helpful");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ rating: "helpful" });
  });

  it("mock mode: answers and records feedback without the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { askGuideline, getGuidelinePassage, sendGuidelineFeedback } = await loadApi("true");
    const a = await askGuideline("How is overtime income evaluated?", "all", null);
    expect(a.status).toBe("answered");
    await expect(sendGuidelineFeedback(a.id, "helpful")).resolves.toBeUndefined();
    expect((await getGuidelinePassage(a.citations[0].passage_id)).label).toBe("authoritative");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("clearing a budget adjustment", () => {
  it("real mode: sends a null adjusted amount with the reason", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, realAngelaHardship()));
    vi.stubGlobal("fetch", fetchMock);
    const { adjustBudgetItem } = await loadApi("false");
    await adjustBudgetItem("c1", "44444444-4444-4444-8444-000000000005", { amount: null, reason: "  Not a one-off after all  " });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ adjusted_amount: null, reason: "Not a one-off after all" });
  });
});

describe("setDocumentType against the real backend", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(reply(202, { document: doc, job }));
    vi.stubGlobal("fetch", fetchMock);
  });

  it("sends PUT with the type and a trimmed reason", async () => {
    const { setDocumentType } = await loadApi("false");
    const result = await setDocumentType("c1", "d1", "w2", "  Scanned W-2, no title  ");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/cases\/c1\/documents\/d1\/type$/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ doc_type: "w2", reason: "Scanned W-2, no title" });
    expect(result.job?.id).toBe("j1"); // 202: extraction was re-queued
  });

  it("leaves the reason out when it is blank", async () => {
    const { setDocumentType } = await loadApi("false");
    await setDocumentType("c1", "d1", "w2", "   ");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ doc_type: "w2" });
  });

  it("treats a 200 as 'type confirmed, no new job'", async () => {
    fetchMock.mockResolvedValue(reply(200, doc));
    const { setDocumentType } = await loadApi("false");
    const result = await setDocumentType("c1", "d1", "w2");
    expect(result.document.id).toBe("d1");
    expect(result.job).toBeUndefined();
  });

  it("turns a 422 into an ApiError with the backend's message", async () => {
    fetchMock.mockResolvedValue(reply(422, { message: "Reason too long" }));
    const { setDocumentType } = await loadApi("false");
    await expect(setDocumentType("c1", "d1", "w2", "x")).rejects.toMatchObject({
      status: 422,
      message: "Reason too long",
    });
  });
});

describe("getPageImage", () => {
  it("on mocks, returns the mock page link for a document that has one", async () => {
    const { getPageImage } = await loadApi("true");
    const { PAYSTUB_DOC_ID } = await import("@/mocks/extraction");
    expect(await getPageImage("c1", PAYSTUB_DOC_ID, 1)).toEqual({ url: "/mock/paystub-p1.svg" });
  });

  it("on mocks, returns nothing for a page that has no picture", async () => {
    const { getPageImage } = await loadApi("true");
    const { PAYSTUB_DOC_ID } = await import("@/mocks/extraction");
    expect(await getPageImage("c1", PAYSTUB_DOC_ID, 9)).toBeUndefined();
  });

  it("against the real backend, returns nothing until the endpoint exists, and never calls fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { getPageImage } = await loadApi("false");
    expect(await getPageImage("c1", "d1", 1)).toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("setDocumentType on mocks", () => {
  it("never calls fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { setDocumentType } = await loadApi("true");
    const { DANIEL_CASE_ID } = await import("@/mocks/data");
    const { PAYSTUB_DOC_ID } = await import("@/mocks/extraction");
    await setDocumentType(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "pay_stub", "same type again");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
