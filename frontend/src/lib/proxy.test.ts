import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forwardToBackend, isSafePath } from "./proxy";

const TOKEN = "tok-123";

const call = (
  path: string,
  init: { method?: string; body?: BodyInit; headers?: Record<string, string>; token?: string | null } = {},
) => {
  const { token = TOKEN, headers = {}, ...rest } = init;
  return new NextRequest(`http://localhost:3000/api/proxy/${path}`, {
    ...rest,
    headers: { ...(token ? { cookie: `copilot_token=${token}; other=1` } : {}), ...headers },
  });
};
const segments = (path: string) => path.split("?")[0].split("/");

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "false");
  vi.stubEnv("API_URL", "http://backend.test/api/v1");
  fetchMock = vi.fn().mockImplementation(async () => json({ items: [] }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("isSafePath", () => {
  it("accepts ordinary pieces, ids and the words the API uses", () => {
    expect(isSafePath(["cases", "11111111-1111-4111-8111-111111111111", "hardship-assessment", "latest"])).toBe(true);
    expect(isSafePath(["documents", "d1", "pages", "1"])).toBe(true);
    expect(isSafePath(["cases", "c1", "documents", "d1", "fields", "net_pay_current"])).toBe(true);
  });

  it("refuses nothing, dots, slashes, backslashes, spaces and odd characters", () => {
    for (const bad of [[], [".."], ["cases", "."], ["a/b"], ["a\\b"], ["a b"], ["a?b"], ["a#b"], ["%2e%2e"], [""], ["a;b"]]) {
      expect(isSafePath(bad)).toBe(false);
    }
  });
});

describe("forwarding a call to the backend", () => {
  it("sends it to the configured backend with the token, keeping the method and the query string", async () => {
    const res = await forwardToBackend(call("cases?pillar=underwriting"), segments("cases?pillar=underwriting"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ items: [] });
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/v1/cases?pillar=underwriting");
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
  });

  it("forwards only the token and the content headers, never the browser's cookies", async () => {
    await forwardToBackend(
      call("cases", { headers: { accept: "application/json", "x-other": "no", referer: "http://localhost:3000/" } }),
      ["cases"],
    );
    const sent = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(Object.keys(sent).sort()).toEqual(["Authorization", "accept"]);
    expect(JSON.stringify(sent)).not.toContain("copilot_token");
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"])("passes a %s with its body and content type", async (method) => {
    const body = JSON.stringify({ reason: "One-off", amount: "200.00" });
    await forwardToBackend(call("cases/c1/x", { method, body, headers: { "content-type": "application/json" } }), ["cases", "c1", "x"]);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe(method);
    expect(init.headers["content-type"]).toBe("application/json");
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe(body);
  });

  it("passes an upload's bytes through unchanged", async () => {
    const bytes = new Uint8Array([0, 1, 2, 250, 251, 252, 255]);
    await forwardToBackend(
      call("cases/c1/documents", { method: "POST", body: bytes, headers: { "content-type": "multipart/form-data; boundary=xyz" } }),
      ["cases", "c1", "documents"],
    );
    const sent = new Uint8Array(fetchMock.mock.calls[0][1].body as ArrayBuffer);
    expect(Array.from(sent)).toEqual(Array.from(bytes));
    expect(fetchMock.mock.calls[0][1].headers["content-type"]).toBe("multipart/form-data; boundary=xyz");
  });

  it("sends no body for a POST that has none, such as starting a run", async () => {
    await forwardToBackend(call("cases/c1/income-analysis", { method: "POST" }), ["cases", "c1", "income-analysis"]);
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
  });

  it("returns the backend's status, content type and body, errors included", async () => {
    fetchMock.mockResolvedValue(json({ code: "not_found", message: "No income analysis has been run for this case" }, 404));
    const res = await forwardToBackend(call("cases/c1/income-analysis/latest"), ["cases", "c1", "income-analysis", "latest"]);
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect((await res.json()).message).toContain("No income analysis");
  });

  it("answers a 204 with no body", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const res = await forwardToBackend(call("x", { method: "DELETE" }), ["x"]);
    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
  });
});

describe("what the proxy refuses", () => {
  it("answers 401 when there is no token, without calling the backend", async () => {
    const res = await forwardToBackend(call("cases", { token: null }), ["cases"]);
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a path that is not plain pieces, without calling the backend", async () => {
    for (const bad of [["..", "admin"], ["cases", "..%2F..", "x"], ["a/b"]]) {
      expect((await forwardToBackend(call("x"), bad)).status).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a change that comes from another site", async () => {
    const res = await forwardToBackend(
      call("cases/c1/income-analysis", { method: "POST", headers: { origin: "https://evil.example" } }),
      ["cases", "c1", "income-analysis"],
    );
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lets a change from this app's own address through, and a read from anywhere", async () => {
    expect((await forwardToBackend(call("a", { method: "POST", headers: { origin: "http://localhost:3000" } }), ["a"])).status).toBe(200);
    expect((await forwardToBackend(call("a", { headers: { origin: "https://other.example" } }), ["a"])).status).toBe(200);
  });

  it("does nothing while the demo data is on", async () => {
    vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "true");
    const res = await forwardToBackend(call("cases"), ["cases"]);
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("when the backend has a problem", () => {
  it("says so plainly when it cannot be reached", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await forwardToBackend(call("cases"), ["cases"]);
    expect(res.status).toBe(502);
    expect((await res.json()).message).toMatch(/Is the backend running/);
  });

  it("a refused token ends the session: 401 and both cookies cleared", async () => {
    fetchMock.mockResolvedValue(json({ code: "unauthorized", message: "Token expired" }, 401));
    const res = await forwardToBackend(call("cases"), ["cases"]);
    expect(res.status).toBe(401);
    const cookies = res.headers.getSetCookie();
    expect(cookies.some((c) => c.startsWith("copilot_token=;") && /Max-Age=0/i.test(c))).toBe(true);
    expect(cookies.some((c) => c.startsWith("copilot_user=;") && /Max-Age=0/i.test(c))).toBe(true);
  });

  it("a 403 (the wrong role) passes through and keeps the session", async () => {
    fetchMock.mockResolvedValue(json({ code: "forbidden", message: "Not allowed" }, 403));
    const res = await forwardToBackend(call("cases"), ["cases"]);
    expect(res.status).toBe(403);
    expect(res.headers.getSetCookie()).toEqual([]);
  });
});
