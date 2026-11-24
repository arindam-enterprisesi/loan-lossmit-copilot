// Stand-in for the backend's audit trail while NEXT_PUBLIC_USE_MOCKS=true (GET /cases/{id}/audit). It does what
// the backend does: events are only ever added, listed newest first, filtered by action and entity type, and paged
// with `before`. The seed is the history the demo cases already have (uploads, readings, one corrected value);
// the screens' own review actions are added to it as they happen (see mocks/store.ts). A reload resets it.
import type { AuditEvent, AuditPage, AuditQuery } from "@/lib/audit-types";
import { ApiError } from "@/lib/api-error";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import { PAYSTUB_DOC_ID } from "./extraction";

/** The person the mock backend treats as signed in. */
export const MOCK_ACTOR = "demo.reviewer";

/** An event together with the case it belongs to. The case is not part of what the API sends. */
export type MockAuditEvent = AuditEvent & { case_id: string };

export const AUDIT_PAGE_DEFAULT = 50;
export const AUDIT_PAGE_MAX = 200;

type Seed = Omit<MockAuditEvent, "id">;

const person = (caseId: string, role: string, at: string, rest: Pick<Seed, "action" | "entity_type"> & Partial<Seed>): Seed => ({
  case_id: caseId,
  at,
  actor_name: MOCK_ACTOR,
  role,
  entity_id: null,
  before: null,
  after: null,
  reason: null,
  ...rest,
});

const system = (caseId: string, at: string, rest: Pick<Seed, "action" | "entity_type"> & Partial<Seed>): Seed => ({
  case_id: caseId,
  at,
  actor_name: null,
  role: "system",
  entity_id: null,
  before: null,
  after: null,
  reason: null,
  ...rest,
});

const DANIEL_SEED: Seed[] = [
  person(DANIEL_CASE_ID, "underwriter", "2026-11-02T09:00:00Z", { action: "case.created", entity_type: "case", entity_id: DANIEL_CASE_ID }),
  person(DANIEL_CASE_ID, "underwriter", "2026-11-02T09:05:00Z", { action: "document.uploaded", entity_type: "document", entity_id: PAYSTUB_DOC_ID, after: { file_name: "paystub-2026-09-27.pdf" } }),
  system(DANIEL_CASE_ID, "2026-11-02T09:06:00Z", { action: "document.classified", entity_type: "document", entity_id: PAYSTUB_DOC_ID, after: { doc_type: "pay_stub" } }),
  system(DANIEL_CASE_ID, "2026-11-02T09:07:00Z", { action: "document.extracted", entity_type: "document", entity_id: PAYSTUB_DOC_ID }),
  system(DANIEL_CASE_ID, "2026-11-02T09:07:30Z", { action: "document.validated", entity_type: "document", entity_id: PAYSTUB_DOC_ID, after: { flags: 1 } }),
  person(DANIEL_CASE_ID, "underwriter", "2026-11-02T11:00:00Z", {
    action: "field.corrected",
    entity_type: "field",
    entity_id: PAYSTUB_DOC_ID,
    before: { field: "net_pay_current", value: "2083.61", review_status: "unreviewed" },
    after: { field: "net_pay_current", value: "2033.61", review_status: "corrected" },
    reason: "The printed net pay does not equal gross minus deductions (3,070.50 less 1,036.89).",
  }),
];

const ANGELA_SEED: Seed[] = [
  person(ANGELA_CASE_ID, "lm_specialist", "2026-11-09T09:00:00Z", { action: "case.created", entity_type: "case", entity_id: ANGELA_CASE_ID }),
  person(ANGELA_CASE_ID, "lm_specialist", "2026-11-09T09:10:00Z", { action: "document.uploaded", entity_type: "document", entity_id: "d2000000-0000-4000-8000-000000000004", after: { file_name: "hardship-letter.pdf" } }),
  system(ANGELA_CASE_ID, "2026-11-09T09:11:00Z", { action: "document.classified", entity_type: "document", entity_id: "d2000000-0000-4000-8000-000000000004", after: { doc_type: "hardship_letter" } }),
  person(ANGELA_CASE_ID, "lm_specialist", "2026-11-09T09:20:00Z", { action: "hardship.reading_requested", entity_type: "analysis_run" }),
  system(ANGELA_CASE_ID, "2026-11-09T09:21:00Z", { action: "hardship.profile_stored", entity_type: "hardship_profile" }),
];

/** The events the demo cases start with, oldest first, numbered from 1. */
export function seedAudit(): MockAuditEvent[] {
  return [...DANIEL_SEED, ...ANGELA_SEED].map((e, i) => ({ ...e, id: i + 1 }));
}

/** The event as the API sends it, without the case it is filed under. */
function toEvent(e: MockAuditEvent): AuditEvent {
  return {
    id: e.id,
    at: e.at,
    actor_name: e.actor_name,
    role: e.role,
    action: e.action,
    entity_type: e.entity_type,
    entity_id: e.entity_id,
    before: structuredClone(e.before),
    after: structuredClone(e.after),
    reason: e.reason,
  };
}

/**
 * GET /cases/{id}/audit: the case's events newest first. `action` and `entity_type` are exact matches, `limit` is
 * 1 to 200 (default 50), and `before` is the id of the last event already seen. `next_before` is null at the end.
 */
export function queryAudit(events: MockAuditEvent[], caseId: string, q: AuditQuery = {}): AuditPage {
  const limit = q.limit ?? AUDIT_PAGE_DEFAULT;
  if (!Number.isInteger(limit) || limit < 1 || limit > AUDIT_PAGE_MAX) {
    throw new ApiError(422, `The page size must be between 1 and ${AUDIT_PAGE_MAX}.`);
  }
  const rows = events
    .filter((e) => e.case_id === caseId)
    .filter((e) => !q.action || e.action === q.action)
    .filter((e) => !q.entity_type || e.entity_type === q.entity_type)
    .filter((e) => q.before === undefined || e.id < q.before)
    .sort((a, b) => b.id - a.id);
  const page = rows.slice(0, limit);
  return {
    items: page.map(toEvent),
    next_before: rows.length > limit ? page[page.length - 1].id : null,
  };
}
