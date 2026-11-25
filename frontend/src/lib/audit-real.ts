// Translation of the backend's audit answer into the screen's shape. Renames and reshapes only: it never
// works anything out (CLAUDE.md rule 1), and it never changes what an event says.
import type { AuditEvent, AuditPage, AuditQuery } from "./audit-types";

/** `AuditEventOut` in backend/app/api/schemas/audit.py. */
export interface RealAuditEvent {
  id: number;
  at: string;
  actor_id: string | null;
  actor_name: string | null;
  role: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
}

/** `AuditPage` in the same file. */
export interface RealAuditPage {
  items: RealAuditEvent[];
  next_before: number | null;
}

export const toAuditEvent = (e: RealAuditEvent): AuditEvent => ({
  id: e.id,
  at: e.at,
  actor_name: e.actor_name,
  role: e.role,
  action: e.action,
  entity_type: e.entity_type,
  entity_id: e.entity_id,
  before: e.before,
  after: e.after,
  reason: e.reason,
});

export const toAuditPage = (p: RealAuditPage): AuditPage => ({ items: p.items.map(toAuditEvent), next_before: p.next_before });

/** The query string for `GET /cases/{id}/audit`: only what was asked for. */
export function auditQueryString(q: AuditQuery): string {
  const params = new URLSearchParams();
  if (q.action) params.set("action", q.action);
  if (q.entity_type) params.set("entity_type", q.entity_type);
  if (q.limit) params.set("limit", String(q.limit));
  if (q.before) params.set("before", String(q.before));
  const text = params.toString();
  return text ? `?${text}` : "";
}
