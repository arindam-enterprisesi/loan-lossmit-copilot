"use client";

import { useCallback, useEffect, useState } from "react";
import { JobProgress } from "@/components/documents/job-progress";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip } from "@/components/shared/flag-chip";
import { CardsSkeleton, TableSkeleton } from "@/components/shared/skeletons";
import { useToast } from "@/components/shared/toast";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { adjustBudgetItem, confirmProfileItem, getLatestHardship, runHardshipAssessment } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import { formatDate } from "@/lib/format";
import type { HardshipAssessment, ProfileKey } from "@/lib/hardship-types";
import type { Case } from "@/lib/types";
import { useJobPoll } from "@/lib/use-job";
import { BudgetTable } from "./budget-table";
import { ChecksTable } from "./checks-table";
import { LetterPanel } from "./letter-panel";
import { MeasuresStrip } from "./measures-strip";
import { ProfilePanel } from "./profile-panel";

interface HardshipWorkspaceProps {
  cases: Case[];
  pillarSlug: string;
}

const messageOf = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);

/**
 * Hardship and budget for one case. Press Run, watch the job, then work through two tabs: the
 * Hardship tab (the letter beside the profile, and the consistency checks) and the Budget tab (the
 * measures, and stated against observed spending). Every figure is shown exactly as the backend
 * returned it, with its working. A person confirms the judgements and adjusts budget items.
 */
export function HardshipWorkspace({ cases, pillarSlug }: HardshipWorkspaceProps) {
  const toast = useToast();
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [assessment, setAssessment] = useState<HardshipAssessment | null>(null);
  const [loaded, setLoaded] = useState(false); // the check for an existing result has finished
  // What went wrong and which step "Try again" repeats.
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [selectedKey, setSelectedKey] = useState<ProfileKey | null>(null);
  const [hoveredKey, setHoveredKey] = useState<ProfileKey | null>(null);

  // Loads the latest result. "Not run yet" (404) is a normal state, not an error.
  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      setAssessment(await getLatestHardship(caseId));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setAssessment(null);
      else setError({ message: messageOf(e, "Could not load the hardship assessment."), retry: () => void load() });
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
    setRunning(true);
    try {
      setJobId((await runHardshipAssessment(caseId)).id);
    } catch (e) {
      setRunning(false);
      setError({ message: messageOf(e, "Could not start the analysis."), retry: () => void onRun() });
    }
  };

  // Confirming has no window, so a failure is a toast. The screen is fine, so it gives another try.
  const onConfirmItem = async (key: ProfileKey) => {
    if (!caseId) return;
    try {
      setAssessment(await confirmProfileItem(caseId, { key, action: "confirm" }));
    } catch (e) {
      toast.error(messageOf(e, "Could not confirm the item."), { retry: () => onConfirmItem(key) });
    }
  };

  // A correction and a budget adjustment have windows, so a failure is thrown for the window to show.
  const onCorrectItem = async (key: ProfileKey, value: string, reason: string) => {
    if (!caseId) return;
    setAssessment(await confirmProfileItem(caseId, { key, action: "correct", value, reason }));
  };
  const onAdjust = async (itemId: string, amount: string | null, reason: string) => {
    if (!caseId) return;
    setAssessment(await adjustBudgetItem(caseId, itemId, { amount, reason }));
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
              setAssessment(null);
              setLoaded(false);
              setError(null);
              setJobId(null);
              setRunning(false);
              setSelectedKey(null);
              setHoveredKey(null);
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
          {assessment ? "Run again" : "Run analysis"}
        </Button>
      </div>

      {running && job ? <JobProgress job={job} subject="Hardship analysis" /> : null}
      {error ? <ErrorNotice message={error.message} onRetry={error.retry} /> : null}

      {!loaded ? (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <CardsSkeleton count={1} label="Loading the letter" />
            <CardsSkeleton count={4} label="Loading the profile" />
          </div>
          <TableSkeleton rows={3} columns={4} label="Loading the checks" />
        </div>
      ) : !assessment || !caseId ? (
        <EmptyState title={running ? "Reading the letter" : "Not run yet"}>
          {running
            ? "Reading the letter and building the budget. The result appears here when it is done."
            : `No hardship analysis yet${selectedCase ? ` for ${selectedCase.title}` : ""}. Press Run analysis to read the letter and build the budget.`}
        </EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <FlagChip tone={assessment.settings_label === "illustrative" ? "warning" : "success"}>
              {assessment.settings_label === "illustrative" ? "Illustrative settings" : "Authoritative settings"}
            </FlagChip>
            <span>Run {formatDate(assessment.run_at)}</span>
          </div>

          <Tabs defaultValue="hardship">
            <TabsList>
              <TabsTrigger value="hardship">Hardship</TabsTrigger>
              <TabsTrigger value="budget">Budget</TabsTrigger>
            </TabsList>

            <TabsContent value="hardship" className="space-y-6 pt-4">
              <div className="grid gap-4 lg:grid-cols-2">
                <LetterPanel
                  letter={assessment.letter}
                  profile={assessment.profile}
                  caseId={caseId}
                  pillarSlug={pillarSlug}
                  selectedKey={selectedKey}
                  hoveredKey={hoveredKey}
                />
                <ProfilePanel
                  items={assessment.profile}
                  selectedKey={selectedKey}
                  onSelect={setSelectedKey}
                  onHover={setHoveredKey}
                  onConfirm={onConfirmItem}
                  onCorrect={onCorrectItem}
                />
              </div>
              <section aria-labelledby="checks-heading" className="space-y-3">
                <h3 id="checks-heading" className="text-base text-navy">
                  Consistency checks
                </h3>
                <ChecksTable checks={assessment.checks} caseId={caseId} pillarSlug={pillarSlug} />
              </section>
            </TabsContent>

            <TabsContent value="budget" className="space-y-6 pt-4">
              {assessment.budget_note ? (
                <EmptyState title="Budget not worked out yet">{assessment.budget_note}</EmptyState>
              ) : null}
              <section aria-labelledby="measures-heading" className="space-y-3">
                <h3 id="measures-heading" className="text-base text-navy">
                  Measures
                </h3>
                <MeasuresStrip measures={assessment.measures} caseId={caseId} pillarSlug={pillarSlug} />
              </section>
              <section aria-labelledby="budget-heading" className="space-y-3">
                <h3 id="budget-heading" className="text-base text-navy">
                  Monthly budget: stated against observed
                </h3>
                <BudgetTable budget={assessment.budget} onAdjust={onAdjust} />
              </section>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
