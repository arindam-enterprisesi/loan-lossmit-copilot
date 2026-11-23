"use client";

import { useCallback, useEffect, useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getLatestCompleteness, overrideCompletenessItem, runCompleteness } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import {
  CHECKLIST_BY_PILLAR,
  OVERRIDE_REASON_MAX,
  outstandingText,
  overallLabel,
  type ChecklistItem,
  type ChecklistResult,
} from "@/lib/completeness";
import { formatDate } from "@/lib/format";
import type { DocumentSummary } from "@/lib/types";
import { CompletenessList } from "./completeness-list";

interface CompletenessPanelProps {
  caseId: string;
  caseTitle?: string;
  /** "underwriting" or "loss-mitigation": decides which checklist is run. */
  pillarSlug: string;
  /** The menu section the documents live under, for the document links. */
  section: string;
  /** Used only to put file names on the document links. */
  documents?: DocumentSummary[] | null;
}

const messageOf = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);

/**
 * Completeness for one case: run the checklist, then read each item's status and reason, override an
 * item with a written reason, or copy the outstanding items. Code decides every status; this panel
 * only shows it. It is never a loan decision. Mount it with `key={caseId}` so a new case starts fresh.
 */
export function CompletenessPanel({ caseId, caseTitle, pillarSlug, section, documents }: CompletenessPanelProps) {
  const checklistId = CHECKLIST_BY_PILLAR[pillarSlug];
  const [result, setResult] = useState<ChecklistResult | null>(null);
  const [loaded, setLoaded] = useState(false); // the check for an existing result has finished
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [overriding, setOverriding] = useState<ChecklistItem | null>(null);
  const [copyNote, setCopyNote] = useState<string | null>(null);

  // "Not run yet" (404) is a normal state, not an error.
  const load = useCallback(async () => {
    try {
      setResult(await getLatestCompleteness(caseId));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setResult(null);
      else setError(messageOf(e, "Could not load the completeness result."));
    } finally {
      setLoaded(true);
    }
  }, [caseId]);

  useEffect(() => {
    load();
  }, [load]);

  const onRun = async () => {
    if (!checklistId) return;
    setError(null);
    setCopyNote(null);
    setRunning(true);
    try {
      setResult(await runCompleteness(caseId, checklistId));
    } catch (e) {
      setError(messageOf(e, "Could not run the checklist."));
    } finally {
      setRunning(false);
    }
  };

  // The backend answers with the recalculated result, so the overall status and the list update together.
  const onOverride = async (reason: string) => {
    if (!overriding) return;
    setResult(await overrideCompletenessItem(caseId, overriding.item_id, reason));
  };

  const onCopy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(outstandingText(result.outstanding));
      setCopyNote("Copied to the clipboard.");
    } catch {
      setCopyNote("Could not copy. Select the list above and copy it yourself.");
    }
  };

  const documentNames = Object.fromEntries((documents ?? []).map((d) => [d.id, d.file_name]));

  return (
    <section aria-labelledby="completeness-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="completeness-heading" className="text-lg">
            {caseTitle ? `Completeness for ${caseTitle}` : "Completeness"}
          </h2>
          <p className="text-sm text-muted-foreground">
            Compares the documents with the checklist. Code decides every status, and it is never a loan decision.
          </p>
        </div>
        <Button onClick={onRun} disabled={!checklistId || running}>
          {running ? "Checking…" : result ? "Run again" : "Run checklist"}
        </Button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      {!loaded ? (
        <Skeleton className="h-32 w-full" />
      ) : !result ? (
        <div className="rounded-xl border border-dashed bg-panel p-8 text-center text-sm text-muted-foreground">
          No completeness result yet. Press Run checklist to compare the documents with it.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <FlagChip tone={result.overall_status === "complete" ? "success" : "warning"}>
              {overallLabel(result.overall_status)}
            </FlagChip>
            <FlagChip tone={result.checklist_label === "illustrative" ? "warning" : "success"}>
              {result.checklist_label === "illustrative" ? "Illustrative checklist" : "Authoritative checklist"}
            </FlagChip>
            <span>
              {result.checklist_id}@{result.checklist_version}
              {result.run_at ? ` · run ${formatDate(result.run_at)}` : ""}
            </span>
          </div>

          <CompletenessList
            items={result.items}
            documentBase={`/${pillarSlug}/${section}/${caseId}`}
            documentNames={documentNames}
            onOverride={setOverriding}
          />

          <div className="space-y-2">
            <h3 className="text-base">Outstanding items</h3>
            {result.outstanding.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing outstanding.</p>
            ) : (
              <>
                <ul className="list-disc pl-5 text-sm text-navy">
                  {result.outstanding.map((o) => (
                    <li key={o}>{o}</li>
                  ))}
                </ul>
                <div className="flex items-center gap-3">
                  <Button variant="outline" size="sm" onClick={onCopy}>
                    Copy outstanding items
                  </Button>
                  {copyNote ? (
                    <span role="status" className="text-xs text-muted-foreground">
                      {copyNote}
                    </span>
                  ) : null}
                </div>
              </>
            )}
          </div>
        </>
      )}

      <ReasonDialog
        open={overriding !== null}
        onOpenChange={(open) => {
          if (!open) setOverriding(null);
        }}
        title={overriding ? `Override ${overriding.label}` : ""}
        description="The item will count as satisfied. Your reason is kept in the audit record, next to what the checklist found."
        note={overriding ? `The checklist found: ${overriding.reason}` : undefined}
        confirmLabel="Override item"
        maxLength={OVERRIDE_REASON_MAX}
        onConfirm={onOverride}
      />
    </section>
  );
}
