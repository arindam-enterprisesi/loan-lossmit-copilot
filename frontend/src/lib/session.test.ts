import { describe, expect, it } from "vitest";
import { canSeePillar, homePathFor, parseSessionUser, pillarsFor, safeNextPath } from "./session";

const user = (role: string) => JSON.stringify({ id: "u1", name: "Una Underwriter", role });

describe("parseSessionUser", () => {
  it("reads a well-formed user", () => {
    expect(parseSessionUser(user("underwriter"))).toEqual({ id: "u1", name: "Una Underwriter", role: "underwriter" });
  });

  it("treats nothing, junk, a wrong shape and an unknown role as signed out", () => {
    expect(parseSessionUser(undefined)).toBeNull();
    expect(parseSessionUser(null)).toBeNull();
    expect(parseSessionUser("")).toBeNull();
    expect(parseSessionUser("not json")).toBeNull();
    expect(parseSessionUser("null")).toBeNull();
    expect(parseSessionUser(JSON.stringify({ id: "u1" }))).toBeNull();
    expect(parseSessionUser(JSON.stringify({ id: 1, name: "x", role: "admin" }))).toBeNull();
    expect(parseSessionUser(user("superuser"))).toBeNull();
  });

  it("keeps only the three known fields", () => {
    const raw = JSON.stringify({ id: "u1", name: "A", role: "admin", password: "secret", extra: 1 });
    expect(parseSessionUser(raw)).toEqual({ id: "u1", name: "A", role: "admin" });
  });
});

describe("what each role can see", () => {
  it("an underwriter sees Loan Processing only, a specialist Loss Mitigation only, an administrator both", () => {
    expect(pillarsFor("underwriter")).toEqual(["underwriting"]);
    expect(pillarsFor("lm_specialist")).toEqual(["loss_mitigation"]);
    expect(pillarsFor("admin")).toEqual(["underwriting", "loss_mitigation"]);
  });

  it("checks one pillar", () => {
    const u = { id: "1", name: "A", role: "underwriter" as const };
    expect(canSeePillar(u, "underwriting")).toBe(true);
    expect(canSeePillar(u, "loss_mitigation")).toBe(false);
  });

  it("lands each role in its own pillar after signing in", () => {
    expect(homePathFor("underwriter")).toBe("/underwriting");
    expect(homePathFor("lm_specialist")).toBe("/loss-mitigation");
    expect(homePathFor("admin")).toBe("/underwriting");
  });
});

describe("safeNextPath: only addresses inside this app", () => {
  it("accepts a path, with its query", () => {
    expect(safeNextPath("/underwriting/income-analysis")).toBe("/underwriting/income-analysis");
    expect(safeNextPath("/loss-mitigation/document-intake?x=1")).toBe("/loss-mitigation/document-intake?x=1");
  });

  it("drops another site, a protocol-relative address, a backslash trick, and nothing", () => {
    expect(safeNextPath("https://evil.example/path")).toBeNull();
    expect(safeNextPath("//evil.example")).toBeNull();
    expect(safeNextPath("/\\evil.example")).toBeNull();
    expect(safeNextPath("javascript:alert(1)")).toBeNull();
    expect(safeNextPath("relative/path")).toBeNull();
    expect(safeNextPath("")).toBeNull();
    expect(safeNextPath(null)).toBeNull();
    expect(safeNextPath(undefined)).toBeNull();
  });
});
