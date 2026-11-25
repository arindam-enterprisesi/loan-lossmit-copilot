"use client";

import { useCallback, useEffect, useState } from "react";
import { JobProgress } from "@/components/documents/job-progress";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip } from "@/components/shared/flag-chip";
import { CardsSkeleton, TableSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-error";
import { getLatestIncome, runIncomeAnalysis, setIncomeComponent } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { requestsText } from "@/lib/income";
import type { IncomeAnalysis } from "@/lib/income-types";
import type { Case } from "@/lib/types";
import { useJobPoll } from "@/lib/use-job";
import { IncomeChecks } from "./income-checks";
import { IncomeFlagCard } from "./income-flag-card";
import { IncomeTable } from "./income-table";

interface IncomeWorkspaceProps {
  cases: Case[];
  pillarSlug: string;
}

const messageOf = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);

/**
 * Income analysis for one case: press Run, watch the job, then read the components, the flags and
 * the cross-checks. Every figure is shown exactly as the backend returned it, with its working.
 */
export function IncomeWorkspace({ cases, pillarSlug }: IncomeWorkspaceProps) {
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [analysis, setAnalysis] = useState<IncomeAnalysis | null>(null);
  const [loaded, setLoaded] = useState(false); // the check for an existing result has finished
  // What went wrong and which step "Try again" repeats.
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [copyNote, setCopyNote] = useState<string | null>(null);

  // Loads the latest result. "Not run yet" (404) is a normal state, not an error.
  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      setAnalysis(await getLatestIncome(caseId));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setAnalysis(null);
      else setError({ message: messageOf(e, "Could not load the income analysis."), retry: () => void load() });
    } finally {
      setLoaded(true);
    }
  }, [caseId]);

  useEffect(() => {
    load();
  }, [load]);

  const { job } = useJobPoll(jobId, async (done) => {
    setRunning(false);
    if (done.status === "succeeded") await load();
    else
      setError({
        message: done.error ? `The analysis failed: ${done.error}` : "The analysis failed.",
        retry: () => void onRun(),
      });
  });

  const onRun = async () => {
    if (!caseId) return;
    setError(null);
    setCopyNote(null);
    setRunning(true);
    try {
      setJobId((await runIncomeAnalysis(caseId)).id);
    } catch (e) {
      setRunning(false);
      setError({ message: messageOf(e, "Could not start the analysis."), retry: () => void onRun() });
    }
  };

  // The backend answers with the recalculated analysis; showing it replaces every figure at once.
  const onDecide = async (componentId: string, included: boolean, reason: string) => {
    if (!caseId) return;
    setAnalysis(await setIncomeComponent(caseId, componentId, { included, reason }));
  };

  const onCopy = async () => {
    if (!analysis) return;
    try {
      await navigator.clipboard.writeText(requestsText(analysis.document_requests));
      setCopyNote("Copied to the clipboard.");
    } catch {
      setCopyNote("Could not copy. Select the list below and copy it yourself.");
    }
  };

  const selectedCase = cases.find((c) => c.id === caseId);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Case
          <select
            className={SELECT_CLASS}
            value={caseId ?? ""}
            onChange={(e) => {
              setAnalysis(null);
              setLoaded(false);
              setError(null);
              setJobId(null);
              setRunning(false);
              setCopyNote(null);
              setCaseId(e.target.value);
            }}
          >
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
        <Button onClick={onRun} disabled={!caseId || running}>
          {analysis ? "Run again" : "Run analysis"}
        </Button>
      </div>

      {running && job ? <JobProgress job={job} subject="Income analysis" /> : null}
      {error ? <ErrorNotice message={error.message} onRetry={error.retry} /> : null}

      {!loaded ? (
        <div className="space-y-4">
          <TableSkeleton rows={3} columns={5} label="Loading the income analysis" />
          <CardsSkeleton count={1} label="Loading flags" />
        </div>
      ) : !analysis ? (
        <EmptyState title={running ? "Calculating" : "Not run yet"}>
          {running
            ? "The result appears here when it is done."
            : `No income analysis yet${selectedCase ? ` for ${selectedCase.title}` : ""}. Press Run analysis to calculate it from the documents.`}
        </EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <FlagChip tone={analysis.method_label === "illustrative" ? "warning" : "success"}>
              {analysis.method_label === "illustrative" ? "Illustrative method" : "Authoritative method"}
            </FlagChip>
            <span>
              {analysis.method_version} · run {formatDate(analysis.run_at)}
            </span>
          </div>

          <section aria-labelledby="components-heading">
            <h2 id="components-heading" className="mb-3 text-lg">
              Income components
            </h2>
            <IncomeTable analysis={analysis} pillarSlug={pillarSlug} onDecide={onDecide} />
          </section>

          <section aria-labelledby="flags-heading" className="space-y-3">
            <h2 id="flags-heading" className="text-lg">
              Flags
            </h2>
            {analysis.flags.length === 0 ? (
              <p className="rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground">
                Nothing flagged.
              </p>
            ) : (
              analysis.flags.map((f) => (
                <IncomeFlagCard key={f.code} flag={f} caseId={analysis.case_id} pillarSlug={pillarSlug} />
              ))
            )}
            {analysis.explanations && analysis.explanations.length > 0 ? (
              <section aria-label="Possible explanations" className="rounded-xl border border-dashed px-4 py-3">
                <div className="flex items-center gap-2">
                  <FlagChip tone="info">possible — to be confirmed</FlagChip>
                  <h3 className="text-base text-navy">Possible explanations</h3>
                </div>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-navy">
                  {analysis.explanations.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </section>
            ) : analysis.explanations_note && analysis.flags.length > 0 ? (
              <p className="text-xs text-muted-foreground" data-testid="explanations-note">
                {analysis.explanations_note === "explanations not generated"
                  ? "Possible explanations have not been generated for these flags yet."
                  : analysis.explanations_note}
              </p>
            ) : null}
          </section>

          {analysis.document_requests.length > 0 ? (
            <section aria-labelledby="requests-heading" className="space-y-2">
              <h2 id="requests-heading" className="text-lg">
                Suggested document requests
              </h2>
              <ul className="list-disc pl-5 text-sm text-navy">
                {analysis.document_requests.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" onClick={onCopy}>
                  Copy document requests
                </Button>
                {copyNote ? (
                  <span role="status" className="text-xs text-muted-foreground">
                    {copyNote}
                  </span>
                ) : null}
              </div>
            </section>
          ) : null}

          <section aria-labelledby="checks-heading" className="space-y-3">
            <h2 id="checks-heading" className="text-lg">
              Cross-document checks
            </h2>
            <IncomeChecks checks={analysis.checks} trend={analysis.trend} />
          </section>
        </>
      )}
    </div>
  );
}
