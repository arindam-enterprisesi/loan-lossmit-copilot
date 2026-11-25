import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ACTION_FILTER_OPTIONS,
  ACTION_LABEL,
  actionLabel,
  actorLabel,
  changedValues,
  entityLabel,
  isReviewAction,
  mergePages,
  roleLabel,
  valueText,
} from "./audit";
import { auditQueryString, toAuditPage, type RealAuditPage } from "./audit-real";
import type { AuditEvent } from "./audit-types";
import { formatDateTime } from "./format";

const event = (id: number, over: Partial<AuditEvent> = {}): AuditEvent => ({
  id,
  at: "2026-11-24T10:00:00Z",
  actor_name: "demo.reviewer",
  role: "underwriter",
  action: "field.corrected",
  entity_type: "field",
  entity_id: null,
  before: null,
  after: null,
  reason: null,
  ...over,
});

describe("action and entity names", () => {
  it("say what the action was in plain words", () => {
    expect(actionLabel("report.signed_off")).toBe("Review signed off");
    expect(actionLabel("lm.condition_overridden")).toBe("Waterfall condition overridden");
    expect(entityLabel("waterfall_condition")).toBe("Waterfall condition");
  });

  it("show an action or entity the screen has not heard of in readable form, not blank", () => {
    expect(actionLabel("future.thing_happened")).toBe("Future thing happened");
    expect(entityLabel("brand_new_kind")).toBe("Brand new kind");
  });

  it("never use the words a person alone may decide with", () => {
    const words = [...Object.values(ACTION_LABEL), ...ACTION_FILTER_OPTIONS.map(actionLabel)].join(" ");
    expect(words).not.toMatch(/approv|deny|denied|eligib|qualif|\boffer/i);
  });

  it("name who did it, and a system step as the system", () => {
    expect(actorLabel(event(1))).toBe("demo.reviewer");
    expect(actorLabel(event(2, { actor_name: null, role: "system" }))).toBe("System");
    expect(roleLabel("lm_specialist")).toBe("Loss mitigation specialist");
    expect(roleLabel("system")).toBe("System");
    expect(roleLabel("auditor")).toBe("Auditor");
  });
});

describe("review actions and automatic steps", () => {
  it("counts what a person did as a review action, and a run or a reading as automatic", () => {
    for (const a of ["field.corrected", "income.component_excluded", "underwriting.condition_rejected", "lm.condition_overridden", "report.signed_off", "case.created", "document.uploaded"]) {
      expect(isReviewAction(a)).toBe(true);
    }
    for (const a of ["document.classified", "document.extracted", "income.analysed", "assets.run_requested", "hardship.profile_stored", "completeness.run"]) {
      expect(isReviewAction(a)).toBe(false);
    }
  });

  it("treats an action it does not know as one to show, so nothing is hidden by accident", () => {
    expect(isReviewAction("future.thing_happened")).toBe(true);
  });
});

describe("what changed", () => {
  it("lists only the keys that differ, with before and after as plain text, in the order sent", () => {
    expect(changedValues({ value: "2083.61", review_status: "unreviewed", field: "net_pay" }, { value: "2033.61", review_status: "corrected", field: "net_pay" })).toEqual([
      { key: "Value", before: "2083.61", after: "2033.61" },
      { key: "Review status", before: "unreviewed", after: "corrected" },
    ]);
  });

  it("shows a value that was only added, or only removed, against a dash", () => {
    expect(changedValues(null, { file_name: "a.pdf" })).toEqual([{ key: "File name", before: "—", after: "a.pdf" }]);
    expect(changedValues({ note: "x" }, null)).toEqual([{ key: "Note", before: "x", after: "—" }]);
    expect(changedValues(null, null)).toEqual([]);
  });

  it("writes numbers, booleans and nested values as text without parsing or rounding them", () => {
    expect(valueText(12.5)).toBe("12.5");
    expect(valueText(false)).toBe("false");
    expect(valueText("5160.00")).toBe("5160.00");
    expect(valueText({ a: 1 })).toBe('{"a":1}');
    expect(valueText(null)).toBe("—");
    expect(valueText("")).toBe("—");
    expect(valueText({ long: "x".repeat(300) })).toHaveLength(120);
  });
});

describe("putting pages together", () => {
  it("keeps newest first and drops an event already shown", () => {
    const merged = mergePages([event(9), event(8)], [event(8), event(7), event(6)]);
    expect(merged.map((e) => e.id)).toEqual([9, 8, 7, 6]);
  });
});

describe("the date and time of an action", () => {
  it("is written in UTC so the server and the browser agree", () => {
    expect(formatDateTime("2026-11-02T11:00:00Z")).toBe("2 Nov 2026, 11:00 UTC");
    expect(formatDateTime(null)).toBe("—");
  });
});

describe("the backend's audit answer", () => {
  const real: RealAuditPage = {
    items: [
      {
        id: 12,
        at: "2026-11-24T10:00:00Z",
        actor_id: "u-1",
        actor_name: "A. Reviewer",
        role: "underwriter",
        action: "report.signed_off",
        entity_type: "report",
        entity_id: "r-1",
        before: { report_status: "in_review" },
        after: { report_status: "signed_off" },
        reason: "Looks complete",
      },
    ],
    next_before: 12,
  };

  it("is renamed to the screen's shape and nothing in it is changed, only the user id dropped", () => {
    const page = toAuditPage(real);
    expect(page.next_before).toBe(12);
    expect(page.items[0]).toEqual({
      id: 12,
      at: "2026-11-24T10:00:00Z",
      actor_name: "A. Reviewer",
      role: "underwriter",
      action: "report.signed_off",
      entity_type: "report",
      entity_id: "r-1",
      before: { report_status: "in_review" },
      after: { report_status: "signed_off" },
      reason: "Looks complete",
    });
    expect(page.items[0]).not.toHaveProperty("actor_id");
  });

  it("asks only for what was filtered", () => {
    expect(auditQueryString({})).toBe("");
    expect(auditQueryString({ action: "field.corrected", limit: 50 })).toBe("?action=field.corrected&limit=50");
    expect(auditQueryString({ entity_type: "report", before: 40 })).toBe("?entity_type=report&before=40");
  });
});

// api.ts reads NEXT_PUBLIC_USE_MOCKS once when it loads, so each test loads a fresh copy.
const loadApi = async (useMocks: "true" | "false") => {
  vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", useMocks);
  vi.resetModules();
  return import("./api");
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("listCaseAudit", () => {
  it("in real mode GETs the case's audit with the filters and translates the answer", async () => {
    const body: RealAuditPage = { items: [], next_before: null };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const { listCaseAudit } = await loadApi("false");
    const page = await listCaseAudit("c1", { action: "report.signed_off", limit: 20, before: 9 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/cases/c1/audit?action=report.signed_off&limit=20&before=9");
    expect(page).toEqual({ items: [], next_before: null });
  });

  it("with demo data answers from the mock trail", async () => {
    const { listCaseAudit } = await loadApi("true");
    const page = await listCaseAudit("11111111-1111-4111-8111-111111111111");
    expect(page.items.length).toBeGreaterThan(0);
  });
});
