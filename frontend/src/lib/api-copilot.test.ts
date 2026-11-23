import { afterEach, describe, expect, it, vi } from "vitest";
import { realAngelaRecommendation, realDanielReport } from "./copilot-real-sample";

// api.ts reads NEXT_PUBLIC_USE_MOCKS once when it loads, so each test loads a fresh copy.
const loadApi = async (useMocks: "true" | "false") => {
  vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", useMocks);
  vi.resetModules();
  return import("./api");
};

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const call = (fetchMock: ReturnType<typeof vi.fn>, n = 0) => ({
  url: fetchMock.mock.calls[n][0] as string,
  method: fetchMock.mock.calls[n][1]?.method as string | undefined,
  body: fetchMock.mock.calls[n][1]?.body ? JSON.parse(fetchMock.mock.calls[n][1].body) : undefined,
});

describe("the underwriting copilot, real mode", () => {
  it("starts a run with POST, and reads the latest report translated", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(202, { job: { id: "j1" } })).mockResolvedValueOnce(reply(200, realDanielReport()));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestUnderwritingReport, runUnderwritingReport } = await loadApi("false");

    await runUnderwritingReport("c1");
    expect(call(fetchMock, 0)).toMatchObject({ url: "/api/proxy/cases/c1/underwriting-report", method: "POST" });

    const report = await getLatestUnderwritingReport("c1");
    expect(call(fetchMock, 1).url).toBe("/api/proxy/cases/c1/underwriting-report/latest");
    expect(report.report?.sections.snapshot[0]).toEqual({ key: "borrower", value: "Daniel Reyes" });
    expect(report.agent_runs.map((a) => a.status)).toEqual(["done", "done", "done"]);
  });

  it("says plainly that starting is not available when the backend has no such endpoint (404 or 405)", async () => {
    for (const status of [404, 405]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(status, { message: "Not Found" })));
      const { runUnderwritingReport } = await loadApi("false");
      await expect(runUnderwritingReport("c1")).rejects.toMatchObject({
        status,
        message: expect.stringMatching(/Starting the underwriting copilot is not available on this backend yet/),
      });
    }
  });

  it("any other failure to start keeps its own message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(422, { message: "No documents to read" })));
    const { runUnderwritingReport } = await loadApi("false");
    await expect(runUnderwritingReport("c1")).rejects.toMatchObject({ status: 422, message: "No documents to read" });
  });

  it("a 404 before the first run is passed on, so the screen can say nothing has run yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "No report yet" })));
    const { getLatestUnderwritingReport } = await loadApi("false");
    await expect(getLatestUnderwritingReport("c1")).rejects.toMatchObject({ status: 404 });
  });

  it("re-runs one agent with POST on its own path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(202, {}));
    vi.stubGlobal("fetch", fetchMock);
    const { rerunUnderwritingAgent } = await loadApi("false");
    await rerunUnderwritingAgent("c1", "critic");
    expect(call(fetchMock)).toMatchObject({ url: "/api/proxy/cases/c1/underwriting-report/latest/agents/critic/rerun", method: "POST" });
  });

  it("re-running says plainly when it is not there yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { message: "Not Found" })));
    const { rerunUnderwritingAgent } = await loadApi("false");
    await expect(rerunUnderwritingAgent("c1", "critic")).rejects.toMatchObject({ message: expect.stringMatching(/Re-running an agent is not available/) });
  });

  it("PATCHes a decision with a trimmed reason and returns the report as it now stands", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, realDanielReport()));
    vi.stubGlobal("fetch", fetchMock);
    const { decideUnderwritingCondition } = await loadApi("false");
    const out = await decideUnderwritingCondition("c1", "cond 1", { decision: "rejected", reason: "  not required for this file  " });
    expect(call(fetchMock)).toEqual({
      url: "/api/proxy/cases/c1/underwriting-report/latest/conditions/cond%201",
      method: "PATCH",
      body: { decision: "rejected", reason: "not required for this file" },
    });
    expect(out.conditions).toHaveLength(1);
  });

  it("POSTs an added condition with its text and priority", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(201, realDanielReport()));
    vi.stubGlobal("fetch", fetchMock);
    const { addUnderwritingCondition } = await loadApi("false");
    await addUnderwritingCondition("c1", { text: "  Gift letter  ", priority: "significant" });
    expect(call(fetchMock)).toEqual({
      url: "/api/proxy/cases/c1/underwriting-report/latest/conditions",
      method: "POST",
      body: { text: "Gift letter", priority: "significant" },
    });
  });

  it("POSTs the sign-off with a trimmed note, or none, and reads how many conditions were left", async () => {
    const result = {
      sign_off: { id: "s1", report_version: 1, signed_by: "u1", role: "underwriter", signed_at: "2026-11-24T10:00:00Z", note: "ok", statement: "Records a review. Not a decision." },
      report_status: "signed_off",
      pending_conditions: 2,
    };
    const fetchMock = vi.fn().mockImplementation(async () => reply(201, result));
    vi.stubGlobal("fetch", fetchMock);
    const { signOffUnderwriting } = await loadApi("false");
    const out = await signOffUnderwriting("c1", "  ok  ");
    expect(call(fetchMock)).toEqual({ url: "/api/proxy/cases/c1/underwriting-report/latest/sign-off", method: "POST", body: { note: "ok" } });
    expect(out.pending_conditions).toBe(2);
    await signOffUnderwriting("c1", "   ");
    expect(call(fetchMock, 1).body).toEqual({});
  });
});

describe("the loss mitigation recommendation, real mode", () => {
  it("starts with POST and reads the latest translated", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(202, {})).mockResolvedValueOnce(reply(200, realAngelaRecommendation()));
    vi.stubGlobal("fetch", fetchMock);
    const { getLatestLmRecommendation, runLmRecommendation } = await loadApi("false");
    await runLmRecommendation("c2");
    expect(call(fetchMock, 0)).toMatchObject({ url: "/api/proxy/cases/c2/lm-recommendation", method: "POST" });
    const rec = await getLatestLmRecommendation("c2");
    expect(call(fetchMock, 1).url).toBe("/api/proxy/cases/c2/lm-recommendation/latest");
    expect(rec.lender_view?.advantage).toBe("2417.00");
    expect(rec.waterfall[1].overridden).toBe(true);
  });

  it("says plainly that starting is not available when the endpoint is missing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(405, { message: "Method Not Allowed" })));
    const { runLmRecommendation } = await loadApi("false");
    await expect(runLmRecommendation("c2")).rejects.toMatchObject({ message: expect.stringMatching(/Starting the recommendation is not available/) });
  });

  it("PUTs an override with a status and a trimmed reason, and returns the recomputed recommendation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, realAngelaRecommendation()));
    vi.stubGlobal("fetch", fetchMock);
    const { overrideLmCondition } = await loadApi("false");
    const out = await overrideLmCondition("c2", "loan_modification.intent", { status: "not_met", reason: "  Not yet confirmed  " });
    expect(call(fetchMock)).toEqual({
      url: "/api/proxy/cases/c2/lm-recommendation/latest/conditions/loan_modification.intent/override",
      method: "PUT",
      body: { status: "not_met", reason: "Not yet confirmed" },
    });
    expect(out.waterfall).toHaveLength(2);
  });

  it("re-runs one agent and signs off on the recommendation's own paths", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => reply(201, { sign_off: { id: "s", report_version: 1, signed_by: "u", role: "lm_specialist", signed_at: "2026-11-24T10:00:00Z", note: null, statement: "Records a review. Not a decision." }, report_status: "signed_off", pending_conditions: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    const { rerunLmAgent, signOffLm } = await loadApi("false");
    await rerunLmAgent("c2", "writer");
    expect(call(fetchMock, 0)).toMatchObject({ url: "/api/proxy/cases/c2/lm-recommendation/latest/agents/writer/rerun", method: "POST" });
    await signOffLm("c2");
    expect(call(fetchMock, 1)).toMatchObject({ url: "/api/proxy/cases/c2/lm-recommendation/latest/sign-off", method: "POST", body: {} });
  });
});

describe("both screens on demo data", () => {
  it("never call fetch, and a run starts, shows progress, and ends with a report", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const api = await loadApi("true");
    const { DANIEL_CASE_ID, ANGELA_CASE_ID } = await import("@/mocks/data");
    await expect(api.getLatestUnderwritingReport(DANIEL_CASE_ID)).rejects.toMatchObject({ status: 404 });
    await api.runUnderwritingReport(DANIEL_CASE_ID);
    const early = await api.getLatestUnderwritingReport(DANIEL_CASE_ID);
    expect(early.run_status).toBe("running");
    expect(early.report).toBeNull();
    await api.runLmRecommendation(ANGELA_CASE_ID);
    expect((await api.getLatestLmRecommendation(ANGELA_CASE_ID)).lender_view?.advantage).toBe("2417.00");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuse a case the agents cannot read (422)", async () => {
    const api = await loadApi("true");
    const { ANGELA_CASE_ID } = await import("@/mocks/data");
    await expect(api.runUnderwritingReport(ANGELA_CASE_ID)).rejects.toMatchObject({ status: 422 });
  });
});
