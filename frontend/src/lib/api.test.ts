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
