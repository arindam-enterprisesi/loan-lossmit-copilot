// Types for the HITL actions screen: the audit trail of one case (Feature Design: Audit Store).
//
// `GET /cases/{id}/audit` is on `main` (backend/app/api/routers/audit.py, schema in schemas/audit.py) but not
// in contracts/openapi.yaml (proposal in docs/contract-proposal-d4.md). The trail is append-only: nothing on
// this screen changes an event, and there is no call that writes one.

export interface AuditEvent {
  /** Rises with time, so "before this id" pages back through older events. */
  id: number;
  at: string;
  /** Null for something the system did on its own. */
  actor_name: string | null;
  role: string;
  /** For example "field.corrected" or "report.signed_off". */
  action: string;
  /** What was acted on: "field", "condition", "report", ... */
  entity_type: string;
  entity_id: string | null;
  /** What it was before the change, when the action changed something. The shape differs by action. */
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  /** The reason the person gave, when the action needs one. */
  reason: string | null;
}

export interface AuditPage {
  /** Newest first. */
  items: AuditEvent[];
  /** Pass as `before` to read the next, older page. Null at the end. */
  next_before: number | null;
}

export interface AuditQuery {
  /** An exact action name, such as "income.component_excluded". */
  action?: string;
  entity_type?: string;
  limit?: number;
  before?: number;
}
