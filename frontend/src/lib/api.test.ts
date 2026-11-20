import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

describe("income analysis calls", () => {
  it("real mode: POSTs the run and GETs the latest result from the proposed paths", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(202, job))
      .mockResolvedValueOnce(reply(200, { id: "a1", case_id: "c1", components: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestIncome, runIncomeAnalysis } = await loadApi("false");

    expect((await runIncomeAnalysis("c1")).id).toBe("j1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/income\/analysis$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");

    expect((await getLatestIncome("c1")).id).toBe("a1");
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/cases\/c1\/income\/analysis\/latest$/);
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
  it("real mode: PATCHes the decision with a trimmed reason and returns the new analysis", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, { id: "a1", case_id: "c1", components: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { setIncomeComponent } = await loadApi("false");

    const a = await setIncomeComponent("c1", "overtime", { included: true, reason: "  Employer letter  " });
    expect(a.id).toBe("a1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/income\/analysis\/components\/overtime$/);
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

  it("real mode: PATCHes the override with a trimmed reason (the proposed path)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, result));
    vi.stubGlobal("fetch", fetchMock);
    const { overrideCompletenessItem } = await loadApi("false");

    expect((await overrideCompletenessItem("c1", "w2_two_years", "  Letter received  ")).id).toBe("r1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/completeness\/items\/w2_two_years$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ reason: "Letter received" });
  });

  it("mock mode: runs for Angela and does not call the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { runCompleteness } = await loadApi("true");
    const r = await runCompleteness("22222222-2222-4222-8222-222222222222", "pillar2-loss-mitigation@1");
    expect(r.overall_status).toBe("incomplete");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("hardship assessment calls", () => {
  it("real mode: POSTs the run and GETs the latest result from the Feature Design paths", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(202, job))
      .mockResolvedValueOnce(reply(200, { id: "h1", case_id: "c1", measures: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestHardship, runHardshipAssessment } = await loadApi("false");

    expect((await runHardshipAssessment("c1")).id).toBe("j1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/hardship-assessment$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");

    expect((await getLatestHardship("c1")).id).toBe("h1");
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/cases\/c1\/hardship-assessment\/latest$/);
  });

  it("real mode: a 404 before the first run becomes an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "No assessment yet" })));
    const { getLatestHardship } = await loadApi("false");
    await expect(getLatestHardship("c1")).rejects.toMatchObject({ status: 404, message: "No assessment yet" });
  });

  it("real mode: PUTs a confirmation, and a correction with a trimmed value and reason", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, { id: "h1" })); // a fresh body each call
    vi.stubGlobal("fetch", fetchMock);
    const { confirmProfileItem } = await loadApi("false");

    await confirmProfileItem("c1", { key: "intent", action: "confirm" });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/hardship-assessment\/latest\/confirmations$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ key: "intent", action: "confirm" });

    await confirmProfileItem("c1", { key: "duration", action: "correct", value: " long_term ", reason: "  Letter from employer  " });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      key: "duration",
      action: "correct",
      value: "long_term",
      reason: "Letter from employer",
    });
  });

  it("real mode: PATCHes a budget adjustment with a trimmed amount and reason", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, { id: "h1" }));
    vi.stubGlobal("fetch", fetchMock);
    const { adjustBudgetItem } = await loadApi("false");

    expect((await adjustBudgetItem("c1", "other", { amount: " 200.00 ", reason: "  One-off repair  " })).id).toBe("h1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/c1\/hardship-assessment\/latest\/budget-items\/other$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ amount: "200.00", reason: "One-off repair" });
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
