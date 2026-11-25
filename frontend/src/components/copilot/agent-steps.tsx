"use client";

import { Check, CircleAlert, Clock, Loader2 } from "lucide-react";
import { useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { useToast } from "@/components/shared/toast";
import { Button } from "@/components/ui/button";
import type { AgentName, AgentRun } from "@/lib/copilot-types";
import { AGENT_JOB, AGENT_LABEL, AGENT_STATUS_LABEL, AGENT_STATUS_TONE, agentSteps } from "@/lib/copilot";
import { formatDate } from "@/lib/format";

const ICON = {
  waiting: Clock,
  running: Loader2,
  done: Check,
  failed: CircleAlert,
} as const;

interface AgentStepsProps {
  runs: AgentRun[];
  /** Runs one agent again, alone. A failure is thrown and shown as a message. */
  onRerun: (agent: AgentName) => Promise<void>;
}

/**
 * The three agents in order, each with its job and where it stands: waiting, running, done or failed. A
 * failed agent can be run again on its own, without starting the others over. If one fails the report
 * still completes and says that section is not available (Feature Design 6.5).
 */
export function AgentSteps({ runs, onRerun }: AgentStepsProps) {
  const toast = useToast();
  const [rerunning, setRerunning] = useState<AgentName | null>(null);

  const rerun = async (agent: AgentName) => {
    setRerunning(agent);
    try {
      await onRerun(agent);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : `Could not re-run the ${AGENT_LABEL[agent]}.`, { retry: () => rerun(agent) });
    } finally {
      setRerunning(null);
    }
  };

  return (
    <ol aria-label="Agent progress" className="grid gap-3 md:grid-cols-3">
      {agentSteps(runs).map((run, i) => {
        const Icon = ICON[run.status];
        return (
          <li
            key={run.agent}
            data-testid={`agent-${run.agent}`}
            data-status={run.status}
            className="flex flex-col gap-2 rounded-xl border bg-card p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-base text-navy">
                <span className="flex size-6 items-center justify-center rounded-full bg-panel text-xs font-semibold text-muted-foreground" aria-hidden>
                  {i + 1}
                </span>
                {AGENT_LABEL[run.agent]}
              </h3>
              <FlagChip tone={AGENT_STATUS_TONE[run.status]}>
                <Icon className={run.status === "running" ? "mr-1 size-3 animate-spin" : "mr-1 size-3"} aria-hidden />
                {AGENT_STATUS_LABEL[run.status]}
              </FlagChip>
            </div>
            <p className="text-xs text-muted-foreground">{AGENT_JOB[run.agent]}</p>
            {run.attempt > 1 ? <p className="text-xs text-muted-foreground">Attempt {run.attempt}</p> : null}
            {run.status === "done" && run.summary ? <p className="text-sm text-navy">{run.summary}</p> : null}
            {run.status === "done" && run.finished_at ? <p className="text-xs text-muted-foreground">Finished {formatDate(run.finished_at)}</p> : null}
            {run.status === "failed" ? (
              <>
                <p role="alert" className="text-sm text-danger">
                  {run.error ?? `The ${AGENT_LABEL[run.agent]} did not finish.`}
                </p>
                <div>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={`Re-run the ${AGENT_LABEL[run.agent]}`}
                    disabled={rerunning !== null}
                    onClick={() => rerun(run.agent)}
                  >
                    Re-run
                  </Button>
                </div>
              </>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
