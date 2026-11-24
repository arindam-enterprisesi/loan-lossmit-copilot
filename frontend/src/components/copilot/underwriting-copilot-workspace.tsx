"use client";

import { useState } from "react";
import { PassagePanel } from "@/components/guidelines/passage-panel";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { CardsSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import {
  addUnderwritingCondition,
  decideUnderwritingCondition,
  getLatestUnderwritingReport,
  rerunUnderwritingAgent,
  runUnderwritingReport,
  signOffUnderwriting,
} from "@/lib/api";
import type { ConditionAddRequest, ConditionDecisionRequest, SignOffResult } from "@/lib/copilot-types";
import { snapshotLabel, snapshotValue, undecidedCount } from "@/lib/copilot";
import { formatDate } from "@/lib/format";
import type { Case } from "@/lib/types";
import { useAgentRun } from "@/lib/use-agent-run";
import { AgentSteps } from "./agent-steps";
import { ConditionsPanel } from "./conditions-panel";
import { ConflictCallout } from "./conflict-callout";
import { EvidenceLinks } from "./evidence-links";
import { FindingsList } from "./findings-list";
import { ReportNotices } from "./report-notices";
import { SignOffBar } from "./sign-off-bar";

interface UnderwritingCopilotWorkspaceProps {
  cases: Case[];
  pillarSlug: string;
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
 * The Underwriting copilot for one case: press Run, watch the Researcher, Writer and Critic, then read the report
 * (findings by priority, any conflict between them, missing information, guideline references), accept, edit or
 * reject each suggested condition, and sign off. The report is a draft for the underwriter. It decides nothing.
 */
export function UnderwritingCopilotWorkspace({ cases, pillarSlug }: UnderwritingCopilotWorkspaceProps) {
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [passageId, setPassageId] = useState<string | null>(null);
  const run = useAgentRun({
    caseId,
    fetchLatest: getLatestUnderwritingReport,
    start: runUnderwritingReport,
    rerun: rerunUnderwritingAgent,
  });
  const { data, setData } = run;
  const selectedCase = cases.find((c) => c.id === caseId);
  const report = data?.report ?? null;

  // The backend answers with the report as it now stands, so showing it replaces what was there.
  const onDecide = async (id: string, req: ConditionDecisionRequest) => {
    if (!caseId) return;
    setData(await decideUnderwritingCondition(caseId, id, req));
  };
  const onAdd = async (req: ConditionAddRequest) => {
    if (!caseId) return;
    setData(await addUnderwritingCondition(caseId, req));
  };
  const onSignOff = async (note: string): Promise<SignOffResult> => {
    if (!caseId) throw new Error("No case is selected.");
    const result = await signOffUnderwriting(caseId, note);
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
          {run.working ? "Running…" : data ? "Run again" : "Run copilot"}
        </Button>
        {data?.report ? <span className="pb-2 text-xs text-muted-foreground">Report version {data.report.version} · {formatDate(data.report.created_at)}</span> : null}
      </div>

      {run.error ? <ErrorNotice message={run.error.message} onRetry={run.error.retry} /> : null}

      {!run.loaded ? (
        <CardsSkeleton count={3} label="Loading the underwriting report" />
      ) : !data && !run.working ? (
        <EmptyState title="Not run yet">
          {`No underwriting report yet${selectedCase ? ` for ${selectedCase.title}` : ""}. Press Run copilot: three agents research, write and check a draft report from the results of the earlier screens.`}
        </EmptyState>
      ) : (
        <>
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
              <ReportNotices notice={report.notice} criticMissing={report.critic_missing} />

              <section aria-labelledby="snapshot-heading" className="space-y-3">
                <h2 id="snapshot-heading" className="text-lg">
                  Case snapshot
                </h2>
                <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {report.sections.snapshot.map((item) => (
                    <div key={item.key} className="rounded-xl border bg-card px-4 py-3">
                      <dt className="text-xs font-semibold text-muted-foreground">{snapshotLabel(item.key)}</dt>
                      <dd className="text-sm font-semibold tabular-nums text-navy">{snapshotValue(item.key, item.value)}</dd>
                    </div>
                  ))}
                </dl>
              </section>

              <ConflictCallout conflicts={report.sections.conflicts} caseId={caseId ?? ""} pillarSlug={pillarSlug} />

              <section aria-labelledby="findings-heading" className="space-y-3">
                <h2 id="findings-heading" className="text-lg">
                  Findings
                </h2>
                <FindingsList findings={data.findings} caseId={caseId ?? ""} pillarSlug={pillarSlug} onOpenPassage={setPassageId} />
              </section>

              <section aria-labelledby="gaps-heading" className="space-y-4">
                <h2 id="gaps-heading" className="text-lg">
                  Risks, missing information and guidance
                </h2>
                <BulletSection id="risks-heading" title="Potential risks" items={report.sections.potential_risks} />
                <BulletSection id="missing-heading" title="Missing information" items={report.sections.missing_information} />
                {report.sections.guideline_references.length > 0 ? (
                  <section aria-labelledby="guidelines-heading" className="space-y-2">
                    <h3 id="guidelines-heading" className="text-base text-navy">
                      Guideline references
                    </h3>
                    <ul className="space-y-2">
                      {report.sections.guideline_references.map((g) => (
                        <li key={g.passage_id} className="rounded-xl border bg-card px-4 py-3 text-sm text-navy">
                          {g.summary ? <p>{g.summary}</p> : null}
                          <EvidenceLinks
                            refs={[{ kind: "passage", id: g.passage_id }]}
                            caseId={caseId ?? ""}
                            pillarSlug={pillarSlug}
                            onOpenPassage={setPassageId}
                          />
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
                {report.sections.note ? <p className="text-xs text-muted-foreground">{report.sections.note}</p> : null}
              </section>

              <ConditionsPanel conditions={data.conditions} onDecide={onDecide} onAdd={onAdd} />

              <SignOffBar signOffs={data.sign_offs} reportStatus={report.status} undecided={undecidedCount(data.conditions)} onSignOff={onSignOff} />
            </>
          )}
        </>
      )}

      <PassagePanel open={passageId !== null} onOpenChange={(open) => !open && setPassageId(null)} passageId={passageId} />
    </div>
  );
}
