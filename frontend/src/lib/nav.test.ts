import { describe, expect, it } from "vitest";
import { PILLARS, PILLAR_SLUG, findNavItem, navHref, pillarFromSlug } from "./nav";
import type { Pillar } from "./types";

const pillars = Object.keys(PILLARS) as Pillar[];

describe("pillar slugs", () => {
  it("maps URL slugs to pillars and back", () => {
    expect(pillarFromSlug("underwriting")).toBe("underwriting");
    expect(pillarFromSlug("loss-mitigation")).toBe("loss_mitigation");
    for (const p of pillars) expect(pillarFromSlug(PILLAR_SLUG[p])).toBe(p);
  });

  it("rejects unknown slugs", () => {
    expect(pillarFromSlug("nope")).toBeNull();
    expect(pillarFromSlug("loss_mitigation")).toBeNull(); // the enum value is not the URL slug
  });
});

describe("navHref", () => {
  it("uses the pillar root for the dashboard and a sub-path otherwise", () => {
    expect(navHref("underwriting", "")).toBe("/underwriting");
    expect(navHref("loss_mitigation", "cases")).toBe("/loss-mitigation/cases");
  });
});

describe("nav config", () => {
  it.each(pillars)("%s starts with the dashboard and has unique slugs", (p) => {
    const { nav } = PILLARS[p];
    expect(nav[0].slug).toBe("");
    expect(nav[0].label).toBe("Dashboard");
    const slugs = nav.map((n) => n.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("follows the PRD menus for each pillar", () => {
    const labels = (p: Pillar) => PILLARS[p].nav.map((n) => n.label);
    expect(labels("underwriting")).toContain("Income analysis");
    expect(labels("underwriting")).toContain("Underwriting copilot");
    expect(labels("loss_mitigation")).toContain("Hardship and budget");
    expect(labels("loss_mitigation")).toContain("Recommendation");
    // screens that belong to the other pillar must not leak across
    expect(labels("underwriting")).not.toContain("Recommendation");
    expect(labels("loss_mitigation")).not.toContain("Income analysis");
  });

  it("finds items by slug within their own pillar only", () => {
    expect(findNavItem("loss_mitigation", "hardship-budget")?.label).toBe("Hardship and budget");
    expect(findNavItem("underwriting", "hardship-budget")).toBeUndefined();
  });

  it("never uses decision wording in menu labels (CLAUDE.md rule 3)", () => {
    const banned = /approv|deny|denied|offer|eligib|qualif/i;
    for (const p of pillars) {
      for (const item of PILLARS[p].nav) expect(item.label).not.toMatch(banned);
    }
  });
});
