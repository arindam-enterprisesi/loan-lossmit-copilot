"use client";

import { useState } from "react";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { AgentSteps } from "@/components/copilot/agent-steps";
import { ReportNotices } from "@/components/copilot/report-notices";
import { SignOffBar } from "@/components/copilot/sign-off-bar";
import { PassagePanel } from "@/components/guidelines/passage-panel";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { CardsSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { getLatestLmRecommendation, overrideLmCondition, rerunLmAgent, runLmRecommendation, signOffLm } from "@/lib/api";
import type { OverrideRequest, SignOffResult } from "@/lib/copilot-types";
import { formatDate } from "@/lib/format";
import type { Case } from "@/lib/types";
import { useAgentRun } from "@/lib/use-agent-run";
import { LenderView } from "./lender-view";
import { RuleSetBanner } from "./rule-set-banner";
import { Waterfall } from "./waterfall";

interface RecommendationWorkspaceProps {
  cases: Case[];
}

function BulletSection({ id, title, items }: { id: string; title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={id} className="space-y-2">
      <h3 id={id} className="text-base text-navy">
        {title}
      </h3>
      <ul className="list-disc space-y-1 pl-5 text-sm text-navy">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The Loss Mitigation recommendation for one case. The rules decide every condition and work out the lender view in
 * code, so the lender view and the waterfall are there as soon as it runs; then three agents research, write and
 * check the report. It is a draft for the specialist and an authorized decision-maker. It decides nothing, and
 * "Met" says only that an option's conditions are met.
 */
export function RecommendationWorkspace({ cases }: RecommendationWorkspaceProps) {
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [passageId, setPassageId] = useState<string | null>(null);
  const run = useAgentRun({
    caseId,
    fetchLatest: getLatestLmRecommendation,
    start: runLmRecommendation,
    rerun: rerunLmAgent,
  });
  const { data, setData } = run;
  const selectedCase = cases.find((c) => c.id === caseId);
  const report = data?.report ?? null;
  const anyOverride = data?.waterfall.some((o) => o.overridden) ?? false;

  // The backend recomputes every option's status and answers with the recommendation as it now stands.
  const onOverride = async (conditionId: string, req: OverrideRequest) => {
    if (!caseId) return;
    setData(await overrideLmCondition(caseId, conditionId, req));
  };
  const onSignOff = async (note: string): Promise<SignOffResult> => {
    if (!caseId) throw new Error("No case is selected.");
    const result = await signOffLm(caseId, note);
    await run.reload();
    return result;
  };

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
        <Button onClick={run.start} disabled={!caseId || run.working}>
          {data ? "Run again" : "Run recommendation"}
        </Button>
        {report ? <span className="pb-2 text-xs text-muted-foreground">Report version {report.version} · {formatDate(report.created_at)}</span> : null}
      </div>

      {run.error ? <ErrorNotice message={run.error.message} onRetry={run.error.retry} /> : null}

      {!run.loaded ? (
        <CardsSkeleton count={3} label="Loading the recommendation" />
      ) : !data && !run.working ? (
        <EmptyState title="Not run yet">
          {`No recommendation yet${selectedCase ? ` for ${selectedCase.title}` : ""}. Press Run recommendation: the rules are applied to the case at once, then three agents write and check the report.`}
        </EmptyState>
      ) : (
        <>
          {data?.rule_set ? <RuleSetBanner ruleSet={data.rule_set} /> : null}

          {data?.lender_view ? <LenderView view={data.lender_view} /> : null}

          {data && data.waterfall.length > 0 ? (
            <Waterfall options={data.waterfall} onOverride={onOverride} onOpenPassage={setPassageId} />
          ) : null}

          <section aria-labelledby="agents-heading" className="space-y-3">
            <h2 id="agents-heading" className="text-lg">
              Agents
            </h2>
            <AgentSteps runs={data?.agent_runs ?? []} onRerun={run.rerun} />
          </section>

          {!report || !data ? (
            <EmptyState title="Writing the report">The report appears here when the agents are done.</EmptyState>
          ) : (
            <>
              <section aria-labelledby="report-heading" className="space-y-4">
                <h2 id="report-heading" className="text-lg">
                  Report
                </h2>
                <ReportNotices
                  notice={report.notice ?? data.notice}
                  criticMissing={report.critic_missing}
                  extra={anyOverride ? ["Overrides are shown on the cards above. The report text below was written before them."] : []}
                />
                <section aria-labelledby="lender-text-heading" className="space-y-1">
                  <h3 id="lender-text-heading" className="text-base text-navy">
                    Lender view
                  </h3>
                  <p className="text-sm text-navy">{report.sections.lender_view}</p>
                </section>
                {report.sections.borrower_situation ? (
                  <section aria-labelledby="situation-heading" className="space-y-1">
                    <h3 id="situation-heading" className="text-base text-navy">
                      The borrower&apos;s situation
                    </h3>
                    <p className="text-sm text-navy">{report.sections.borrower_situation}</p>
                  </section>
                ) : null}
                <BulletSection id="missing-heading" title="Missing information" items={report.sections.missing_information} />
                <BulletSection id="compliance-heading" title="Compliance points" items={report.sections.compliance_points} />
                <BulletSection id="review-heading" title="Items for human review" items={report.sections.items_for_human_review} />
                {report.sections.note ? <p className="text-xs text-muted-foreground">{report.sections.note}</p> : null}
              </section>

              <SignOffBar signOffs={data.sign_offs} reportStatus={report.status} onSignOff={onSignOff} />
            </>
          )}
        </>
      )}

      <PassagePanel open={passageId !== null} onOpenChange={(open) => !open && setPassageId(null)} passageId={passageId} />
    </div>
  );
}
