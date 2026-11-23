import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { config, middleware } from "./middleware";

const at = (path: string, signedIn = false) =>
  new NextRequest(`http://localhost:3000${path}`, {
    headers: signedIn ? { cookie: "copilot_token=tok" } : {},
  });

const passes = (res: Response) => res.headers.get("x-middleware-next") === "1";

beforeEach(() => vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "false"));
afterEach(() => vi.unstubAllEnvs());

describe("middleware: demo data", () => {
  it("lets everything through, with no sign-in", () => {
    vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "true");
    expect(passes(middleware(at("/underwriting")))).toBe(true);
    expect(passes(middleware(at("/api/proxy/cases")))).toBe(true);
  });
});

describe("middleware: real mode, signed out", () => {
  it("sends a page to the sign-in page, remembering where it was going", () => {
    const res = middleware(at("/underwriting/income-analysis"));
    expect(res.status).toBe(307);
    const url = new URL(res.headers.get("location")!);
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("next")).toBe("/underwriting/income-analysis");
  });

  it("keeps the query string of the page it was going to", () => {
    const url = new URL(middleware(at("/loss-mitigation/cases?x=1")).headers.get("location")!);
    expect(url.searchParams.get("next")).toBe("/loss-mitigation/cases?x=1");
  });

  it("does not remember the home page, and sends it to a clean sign-in address", () => {
    const url = new URL(middleware(at("/")).headers.get("location")!);
    expect(url.pathname).toBe("/login");
    expect(url.search).toBe("");
  });

  it("answers an API call with 401 instead of a page redirect", async () => {
    const res = middleware(at("/api/proxy/cases"));
    expect(res.status).toBe(401);
    expect((await res.json()).message).toBe("Sign in to continue.");
  });

  it("always lets the sign-in page and the sign-in and sign-out calls through", () => {
    expect(passes(middleware(at("/login")))).toBe(true);
    expect(passes(middleware(at("/login?expired=1")))).toBe(true);
    expect(passes(middleware(at("/api/session/login")))).toBe(true);
    expect(passes(middleware(at("/api/session/logout")))).toBe(true);
  });
});

describe("middleware: real mode, signed in", () => {
  it("lets pages and API calls through", () => {
    expect(passes(middleware(at("/underwriting", true)))).toBe(true);
    expect(passes(middleware(at("/api/proxy/cases", true)))).toBe(true);
  });
});

describe("middleware: which addresses it runs on", () => {
  const pattern = new RegExp(`^${config.matcher[0]}$`);
  it("runs on pages and API calls, and skips the framework's files, the icon and the mock pictures", () => {
    for (const yes of ["/", "/underwriting", "/api/proxy/cases", "/login"]) expect(pattern.test(yes)).toBe(true);
    for (const no of ["/_next/static/chunk.js", "/_next/image", "/favicon.ico", "/mock/paystub-p1.svg"]) {
      expect(pattern.test(no)).toBe(false);
    }
  });
});
