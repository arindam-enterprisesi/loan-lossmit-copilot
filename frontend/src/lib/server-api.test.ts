import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "@/mocks/data";

const nav = vi.hoisted(() => ({
  redirect: vi.fn((to: string) => {
    throw new Error(`REDIRECT:${to}`);
  }),
}));
const headers = vi.hoisted(() => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => nav);
vi.mock("next/headers", () => headers);

import { loadCases, loadDocuments } from "./server-api";

const withToken = (token: string | undefined) =>
  headers.cookies.mockResolvedValue({ get: (name: string) => (name === "copilot_token" && token ? { value: token } : undefined) });

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  nav.redirect.mockClear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("server data with the demo data on", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "true"));

  it("returns the mock cases of one pillar and never calls the network or asks for a token", async () => {
    const cases = await loadCases("loss_mitigation");
    expect(cases.map((c) => c.id)).toEqual([ANGELA_CASE_ID]);
    expect((await loadCases("underwriting")).map((c) => c.id)).toEqual([DANIEL_CASE_ID]);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(headers.cookies).not.toHaveBeenCalled();
  });

  it("returns the mock documents of a case", async () => {
    const docs = await loadDocuments(DANIEL_CASE_ID);
    expect(docs.length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("server data in real mode", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "false");
    vi.stubEnv("API_URL", "http://backend.test/api/v1");
    withToken("tok-123");
  });

  it("asks the backend for a pillar's cases with the token from the cookie", async () => {
    fetchMock.mockResolvedValue(json({ items: [{ id: "c1", title: "Daniel Reyes", pillar: "underwriting" }] }));
    const cases = await loadCases("underwriting");
    expect(cases).toEqual([{ id: "c1", title: "Daniel Reyes", pillar: "underwriting" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/v1/cases?pillar=underwriting");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-123");
  });

  it("asks for a case's documents", async () => {
    fetchMock.mockResolvedValue(json({ items: [{ id: "d1" }] }));
    expect(await loadDocuments("c1")).toEqual([{ id: "d1" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/v1/cases/c1/documents");
  });

  it("sends a person with no token to the sign-in page, without calling the backend", async () => {
    withToken(undefined);
    await expect(loadCases("underwriting")).rejects.toThrow("REDIRECT:/login");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends a person whose token was refused to the sign-in page, saying the session ended", async () => {
    fetchMock.mockResolvedValue(json({ message: "expired" }, 401));
    await expect(loadCases("underwriting")).rejects.toThrow("REDIRECT:/login?expired=1");
  });

  it("raises the backend's own message for another error, so the page can show it", async () => {
    fetchMock.mockResolvedValue(json({ code: "boom", message: "The database is down" }, 503));
    await expect(loadCases("underwriting")).rejects.toMatchObject({ status: 503, message: "The database is down" });
  });

  it("raises a plain message when the error has no message, and when the backend is not running", async () => {
    fetchMock.mockResolvedValue(new Response("oops", { status: 500 }));
    await expect(loadCases("underwriting")).rejects.toMatchObject({ status: 500, message: expect.stringContaining("500") });
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    await expect(loadCases("underwriting")).rejects.toMatchObject({ status: 502, message: expect.stringContaining("Is the backend running") });
  });
});
