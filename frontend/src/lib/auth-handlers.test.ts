import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loginHandler, logoutHandler } from "./auth-handlers";

const login = (body: unknown, url = "http://localhost:3000/api/session/login") =>
  new NextRequest(url, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) });

const upstreamOk = (overrides: Record<string, unknown> = {}) =>
  new Response(
    JSON.stringify({
      access_token: "tok-123",
      token_type: "bearer",
      expires_in: 1800,
      user: { id: "u1", name: "Una Underwriter", role: "underwriter" },
      ...overrides,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );

const cookiesOf = (res: Response) => res.headers.getSetCookie();
const cookie = (res: Response, name: string) => cookiesOf(res).find((c) => c.startsWith(`${name}=`)) ?? "";

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "false");
  vi.stubEnv("API_URL", "http://backend.test/api/v1");
  fetchMock = vi.fn().mockResolvedValue(upstreamOk());
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("signing in", () => {
  it("signs in against the backend and answers with the user, never the token", async () => {
    const res = await loginHandler(login({ username: " underwriter ", password: "pw" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ user: { id: "u1", name: "Una Underwriter", role: "underwriter" } });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/v1/auth/login");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ username: "underwriter", password: "pw" }); // name trimmed
  });

  it("keeps the token in an httpOnly cookie that lasts as long as the token", async () => {
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    const token = cookie(res, "copilot_token");
    expect(token).toContain("copilot_token=tok-123");
    expect(token).toMatch(/HttpOnly/i);
    expect(token).toMatch(/Max-Age=1800/i);
    expect(token).toMatch(/SameSite=lax/i);
    expect(token).toMatch(/Path=\//i);
    expect(token).not.toMatch(/Secure/i); // plain http on localhost
  });

  it("puts only the name and role in the readable cookie, which scripts may read but which grants nothing", async () => {
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    const readable = cookie(res, "copilot_user");
    expect(readable).not.toMatch(/HttpOnly/i);
    expect(decodeURIComponent(readable)).toContain('"role":"underwriter"');
    expect(readable).not.toContain("tok-123");
  });

  it("marks the cookies Secure when the app is served over https", async () => {
    const res = await loginHandler(login({ username: "u", password: "pw" }, "https://copilot.example/api/session/login"));
    expect(cookie(res, "copilot_token")).toMatch(/Secure/i);
  });

  it("never puts the password in the answer or the cookies", async () => {
    const res = await loginHandler(login({ username: "u", password: "very-secret-pw" }));
    const everything = JSON.stringify(await res.json()) + cookiesOf(res).join(";");
    expect(everything).not.toContain("very-secret-pw");
  });

  it("falls back to an hour when the backend does not say how long the token lasts", async () => {
    fetchMock.mockResolvedValue(upstreamOk({ expires_in: undefined }));
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    expect(cookie(res, "copilot_token")).toMatch(/Max-Age=3600/i);
  });
});

describe("signing in goes wrong", () => {
  it("a wrong username or password is a 401 with one plain message, and no cookies", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "invalid_credentials", message: "Incorrect" }), { status: 401 }));
    const res = await loginHandler(login({ username: "u", password: "bad" }));
    expect(res.status).toBe(401);
    expect((await res.json()).message).toBe("Incorrect username or password.");
    expect(cookiesOf(res)).toEqual([]);
  });

  it("a backend that is down is a 502 that says so", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    expect(res.status).toBe(502);
    expect((await res.json()).message).toMatch(/Is the backend running/);
  });

  it("an unexpected backend error is a 502 naming the status", async () => {
    fetchMock.mockResolvedValue(new Response("boom", { status: 500 }));
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    expect(res.status).toBe(502);
    expect((await res.json()).message).toContain("500");
    expect(cookiesOf(res)).toEqual([]);
  });

  it("an answer without a token, or with an unknown role, signs nobody in", async () => {
    fetchMock.mockResolvedValue(upstreamOk({ access_token: "" }));
    expect((await loginHandler(login({ username: "u", password: "pw" }))).status).toBe(502);
    fetchMock.mockResolvedValue(upstreamOk({ user: { id: "u1", name: "A", role: "superuser" } }));
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    expect(res.status).toBe(502);
    expect(cookiesOf(res)).toEqual([]);
  });

  it("an answer that is not JSON is a 502", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 200 }));
    expect((await loginHandler(login({ username: "u", password: "pw" }))).status).toBe(502);
  });

  it.each([
    ["not JSON", "{oops"],
    ["no fields", {}],
    ["a blank username", { username: "   ", password: "pw" }],
    ["no password", { username: "u", password: "" }],
    ["a number as the username", { username: 5, password: "pw" }],
    ["a username that is too long", { username: "x".repeat(65), password: "pw" }],
    ["a password that is too long", { username: "u", password: "x".repeat(257) }],
  ])("asks for a username and a password when given %s, without calling the backend", async (_name, body) => {
    const res = await loginHandler(login(body));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does nothing while the demo data is on", async () => {
    vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "true");
    const res = await loginHandler(login({ username: "u", password: "pw" }));
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("signing out", () => {
  it("empties and expires both cookies", async () => {
    const res = await logoutHandler(new NextRequest("http://localhost:3000/api/session/logout", { method: "POST" }));
    expect(res.status).toBe(200);
    for (const name of ["copilot_token", "copilot_user"]) {
      const c = cookie(res, name);
      expect(c).toMatch(new RegExp(`^${name}=;`));
      expect(c).toMatch(/Max-Age=0/i);
    }
    expect(cookie(res, "copilot_token")).toMatch(/HttpOnly/i);
  });

  it("works in demo mode too, harmlessly", async () => {
    vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "true");
    const res = await logoutHandler(new NextRequest("http://localhost:3000/api/session/logout", { method: "POST" }));
    expect(res.status).toBe(200);
  });
});
