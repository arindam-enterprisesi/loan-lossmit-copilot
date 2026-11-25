"use client";

import { useCallback, useEffect, useState } from "react";
import { JobProgress } from "@/components/documents/job-progress";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip } from "@/components/shared/flag-chip";
import { CardsSkeleton, TableSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import {
  getLatestAssetAnalysis,
  getLoanScenario,
  putLoanScenario,
  reviewObligation,
  reviewTransaction,
  runAssetAnalysis,
} from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import type { AssetAnalysis, LoanScenario, LoanScenarioInput, TransactionCategory } from "@/lib/assets-types";
import { formatDate } from "@/lib/format";
import type { Case } from "@/lib/types";
import { useJobPoll } from "@/lib/use-job";
import { AssetFlags } from "./asset-flags";
import { AssetSummary } from "./asset-summary";
import { LoanScenarioForm } from "./loan-scenario-form";
import { ObligationsTable } from "./obligations-table";
import { TransactionsTable } from "./transactions-table";

interface AssetsWorkspaceProps {
  cases: Case[];
  pillarSlug: string;
}

const messageOf = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);
const isNotFound = (e: unknown): boolean => e instanceof ApiError && e.status === 404;

/**
 * Assets and liabilities for one case: enter the sample loan, press Run, then read the summary strip, the
 * flags, every bank line, and the debts. Every figure is shown exactly as the backend returned it, with
 * its working, as a candidate for the underwriter to review. A person reclassifies lines, marks deposits
 * as sourced, and decides which debts count; the ratios follow at once.
 */
export function AssetsWorkspace({ cases, pillarSlug }: AssetsWorkspaceProps) {
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [scenario, setScenario] = useState<LoanScenario | null>(null);
  const [analysis, setAnalysis] = useState<AssetAnalysis | null>(null);
  const [loaded, setLoaded] = useState(false); // the check for a saved scenario and an earlier result has finished
  // What went wrong and which step "Try again" repeats.
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  // The scenario was saved after the figures were worked out, so the figures use the earlier one.
  const [scenarioNewer, setScenarioNewer] = useState(false);

  // Loads the saved scenario and the latest result. "None yet" (404) is a normal state, not an error.
  const load = useCallback(async () => {
    if (!caseId) return;
    const [s, a] = await Promise.allSettled([getLoanScenario(caseId), getLatestAssetAnalysis(caseId)]);
    setScenario(s.status === "fulfilled" ? s.value : null);
    setAnalysis(a.status === "fulfilled" ? a.value : null);
    setScenarioNewer(false);
    const failure = [s, a].find((r) => r.status === "rejected" && !isNotFound(r.reason)) as PromiseRejectedResult | undefined;
    setError(failure ? { message: messageOf(failure.reason, "Could not load the asset analysis."), retry: () => void load() } : null);
    setLoaded(true);
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
    setRunning(true);
    try {
      setJobId((await runAssetAnalysis(caseId)).id);
    } catch (e) {
      setRunning(false);
      setError({ message: messageOf(e, "Could not start the analysis."), retry: () => void onRun() });
    }
  };

  // Failures are thrown on purpose: the form and the windows show the message and keep what was typed.
  const onSaveScenario = async (input: LoanScenarioInput) => {
    if (!caseId) return;
    setScenario(await putLoanScenario(caseId, input));
    if (analysis) setScenarioNewer(true);
  };
  const onReclassify = async (transactionId: string, category: TransactionCategory, reason: string) => {
    if (!caseId) return;
    setAnalysis(await reviewTransaction(caseId, transactionId, { category, reason }));
  };
  const onSource = async (transactionId: string, sourced: boolean, reason: string) => {
    if (!caseId) return;
    setAnalysis(await reviewTransaction(caseId, transactionId, { sourced, reason }));
  };
  // The backend answers with the recalculated analysis; showing it replaces every figure at once.
  const onDecide = async (obligationId: string, counts: boolean, reason: string) => {
    if (!caseId) return;
    setAnalysis(await reviewObligation(caseId, obligationId, { counts_toward_dti: counts, reason }));
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
              setScenario(null);
              setAnalysis(null);
              setLoaded(false);
              setError(null);
              setJobId(null);
              setRunning(false);
              setScenarioNewer(false);
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
        <Button onClick={onRun} disabled={!caseId || running || !scenario}>
          {analysis ? "Run again" : "Run analysis"}
        </Button>
        {loaded && !scenario ? <span className="pb-2 text-xs text-muted-foreground">Save the loan scenario first.</span> : null}
      </div>

      {running && job ? <JobProgress job={job} subject="Asset and liability analysis" /> : null}
      {error ? <ErrorNotice message={error.message} onRetry={error.retry} /> : null}

      {!loaded ? (
        <div className="space-y-4">
          <CardsSkeleton count={1} label="Loading the loan scenario" />
          <TableSkeleton rows={4} columns={5} label="Loading the asset analysis" />
        </div>
      ) : !caseId ? null : (
        <>
          <LoanScenarioForm key={`${caseId}-${scenario?.updated_at ?? "new"}`} scenario={scenario} onSave={onSaveScenario} />

          {!analysis ? (
            <EmptyState title={running ? "Calculating" : "Not run yet"}>
              {running
                ? "The figures appear here when the analysis is done."
                : `No asset analysis yet${selectedCase ? ` for ${selectedCase.title}` : ""}. ${
                    scenario ? "Press Run analysis to work out the figures from the statements." : "Save the loan scenario, then press Run analysis."
                  }`}
            </EmptyState>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <FlagChip tone={analysis.settings_label === "illustrative" ? "warning" : "success"}>
                  {analysis.settings_label === "illustrative" ? "Illustrative settings" : "Authoritative settings"}
                </FlagChip>
                <span>Run {formatDate(analysis.run_at)}</span>
                <span>· {analysis.note}</span>
              </div>
              {scenarioNewer ? (
                <p role="status" className="rounded-xl border border-gold/50 bg-gold/10 px-4 py-3 text-sm text-navy">
                  The loan scenario was saved after these figures were worked out. Press Run again to use it.
                </p>
              ) : null}

              <section aria-labelledby="summary-heading" className="space-y-3">
                <h2 id="summary-heading" className="text-lg">
                  Summary
                </h2>
                <AssetSummary analysis={analysis} pillarSlug={pillarSlug} />
              </section>

              <section aria-labelledby="flags-heading" className="space-y-3">
                <h2 id="flags-heading" className="text-lg">
                  Flags
                </h2>
                <AssetFlags flags={analysis.flags} caseId={analysis.case_id} pillarSlug={pillarSlug} />
              </section>

              <section aria-labelledby="obligations-heading" className="space-y-3">
                <h2 id="obligations-heading" className="text-lg">
                  Obligations
                </h2>
                <ObligationsTable
                  obligations={analysis.obligations}
                  total={analysis.monthly_obligations}
                  caseId={analysis.case_id}
                  pillarSlug={pillarSlug}
                  onDecide={onDecide}
                />
              </section>

              <section aria-labelledby="transactions-heading" className="space-y-3">
                <h2 id="transactions-heading" className="text-lg">
                  Transactions
                </h2>
                <TransactionsTable
                  transactions={analysis.transactions}
                  caseId={analysis.case_id}
                  pillarSlug={pillarSlug}
                  onReclassify={onReclassify}
                  onSource={onSource}
                />
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
