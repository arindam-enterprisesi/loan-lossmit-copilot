"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip } from "@/components/shared/flag-chip";
import { NoCases } from "@/components/shared/no-cases";
import { TableSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listCaseAudit } from "@/lib/api";
import {
  ACTION_FILTER_OPTIONS,
  actionLabel,
  actorLabel,
  changedValues,
  ENTITY_FILTER_OPTIONS,
  entityLabel,
  isReviewAction,
  mergePages,
  roleLabel,
} from "@/lib/audit";
import type { AuditEvent } from "@/lib/audit-types";
import { formatDateTime } from "@/lib/format";
import type { Case } from "@/lib/types";

interface HitlWorkspaceProps {
  cases: Case[];
}

type Scope = "review" | "all";

const PAGE = 50;
/** How many pages are read in a row to find a review action, when a page holds only automatic steps. */
const SKIP_LIMIT = 10;

/**
 * Every review action on one case, newest first: who did what, when, why, and what it changed. It reads the audit
 * trail, which only ever grows. Nothing here changes an event, and nothing on this screen decides anything.
 */
export function HitlWorkspace({ cases }: HitlWorkspaceProps) {
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [scope, setScope] = useState<Scope>("review");
  const [action, setAction] = useState("");
  const [entity, setEntity] = useState("");
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  // A newer request replaces an older one still in flight.
  const ticket = useRef(0);

  // Only people's actions, unless a particular action was asked for or the person wants everything.
  const wanted = useCallback((e: AuditEvent) => scope === "all" || action !== "" || isReviewAction(e.action), [scope, action]);

  /** Reads from `before` until something to show turns up or the trail ends. Returns what it found and where it stopped. */
  const readPages = useCallback(
    async (id: string, before?: number) => {
      let found: AuditEvent[] = [];
      let cursor = before;
      let next: number | null = null;
      for (let i = 0; i < SKIP_LIMIT; i++) {
        const page = await listCaseAudit(id, { action: action || undefined, entity_type: entity || undefined, limit: PAGE, before: cursor });
        found = found.concat(page.items.filter(wanted));
        next = page.next_before;
        if (found.length > 0 || next === null) break;
        cursor = next;
      }
      return { found, next };
    },
    [action, entity, wanted],
  );

  const load = useCallback(async () => {
    if (!caseId) return;
    const mine = ++ticket.current;
    setEvents(null);
    setError(null);
    try {
      const { found, next } = await readPages(caseId);
      if (mine !== ticket.current) return;
      setEvents(found);
      setNextBefore(next);
    } catch (e) {
      if (mine !== ticket.current) return;
      setError({ message: e instanceof Error ? e.message : "The actions could not be loaded.", retry: () => void load() });
    }
  }, [caseId, readPages]);

  useEffect(() => {
    // Read again when the case or a filter changes.
    void load();
  }, [load]);

  const loadMore = async () => {
    if (!caseId || nextBefore === null) return;
    const mine = ticket.current;
    setLoadingMore(true);
    setError(null);
    try {
      const { found, next } = await readPages(caseId, nextBefore);
      if (mine !== ticket.current) return;
      setEvents((shown) => mergePages(shown ?? [], found));
      setNextBefore(next);
    } catch (e) {
      if (mine !== ticket.current) return;
      setError({ message: e instanceof Error ? e.message : "More actions could not be loaded.", retry: () => void loadMore() });
    } finally {
      setLoadingMore(false);
    }
  };

  if (cases.length === 0) return <NoCases />;

  const actionOptions = ACTION_FILTER_OPTIONS.filter((a) => scope === "all" || isReviewAction(a));
  const filtered = action !== "" || entity !== "";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Case
          <select className={SELECT_CLASS} value={caseId ?? ""} onChange={(e) => setCaseId(e.target.value)}>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Show
          <select
            className={SELECT_CLASS}
            value={scope}
            onChange={(e) => {
              const next = e.target.value as Scope;
              setScope(next);
              // An action that is not offered under the new scope cannot stay chosen.
              if (next === "review" && action && !isReviewAction(action)) setAction("");
            }}
          >
            <option value="review">Review actions</option>
            <option value="all">All activity, including automatic steps</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Action
          <select className={SELECT_CLASS} value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">Any action</option>
            {actionOptions.map((a) => (
              <option key={a} value={a}>
                {actionLabel(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          What it was done to
          <select className={SELECT_CLASS} value={entity} onChange={(e) => setEntity(e.target.value)}>
            <option value="">Anything</option>
            {ENTITY_FILTER_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {entityLabel(t)}
              </option>
            ))}
          </select>
        </label>
        {filtered ? (
          <Button
            variant="outline"
            onClick={() => {
              setAction("");
              setEntity("");
            }}
          >
            Clear filters
          </Button>
        ) : null}
      </div>

      {error ? <ErrorNotice message={error.message} onRetry={error.retry} /> : null}

      {events === null && !error ? (
        <TableSkeleton rows={5} columns={4} label="Loading the actions" />
      ) : events !== null && events.length === 0 ? (
        <EmptyState title={filtered ? "Nothing matches" : "No review actions yet"}>
          {filtered
            ? "No action on this case matches those filters. Clear them to see every action."
            : "Nothing has been confirmed, corrected, overridden, decided or signed off on this case yet. Each of those appears here as it happens."}
        </EmptyState>
      ) : events !== null ? (
        <div className="space-y-3">
          <div className="rounded-xl border bg-card">
            <Table>
              <TableCaption className="sr-only">Actions on this case, newest first</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">When</TableHead>
                  <TableHead scope="col">Who</TableHead>
                  <TableHead scope="col">Action</TableHead>
                  <TableHead scope="col">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {events.map((e) => (
                  <EventRow key={e.id} event={e} />
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted-foreground" role="status">
              {events.length === 1 ? "1 action shown" : `${events.length} actions shown`}
              {nextBefore === null ? ". That is all of them." : "."}
            </p>
            {nextBefore !== null ? (
              <Button variant="outline" size="sm" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load older actions"}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EventRow({ event: e }: { event: AuditEvent }) {
  const changes = changedValues(e.before, e.after);
  return (
    <TableRow className="align-top" data-testid={`audit-${e.id}`}>
      <TableCell className="tabular-nums text-muted-foreground">{formatDateTime(e.at)}</TableCell>
      <TableCell className="whitespace-normal">
        <div className="font-semibold text-navy">{actorLabel(e)}</div>
        <div className="text-xs text-muted-foreground">{roleLabel(e.role)}</div>
      </TableCell>
      <TableCell className="whitespace-normal">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-navy">{actionLabel(e.action)}</span>
          <FlagChip tone="neutral">{entityLabel(e.entity_type)}</FlagChip>
        </div>
        {changes.length > 0 ? (
          <details className="mt-1 text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none underline underline-offset-2">What changed</summary>
            <dl className="mt-1 space-y-0.5">
              {changes.map((c) => (
                <div key={c.key} className="flex flex-wrap gap-x-2">
                  <dt className="font-semibold">{c.key}</dt>
                  <dd>
                    <span className="line-through decoration-muted-foreground/50">{c.before}</span> → <span className="text-navy">{c.after}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}
      </TableCell>
      <TableCell className="whitespace-normal text-navy">{e.reason ?? <span className="text-muted-foreground">—</span>}</TableCell>
    </TableRow>
  );
}
