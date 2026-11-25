"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { USE_MOCKS } from "./api";
import { ApiError } from "./api-error";
import type { AgentName, AgentRun, RunStatus } from "./copilot-types";
import { agentsBusy } from "./copilot";
import { pollIntervalFor } from "./use-job";

/** What both agent screens need from an answer: where the run stands and how each agent is doing. */
interface Run {
  run_status: RunStatus;
  agent_runs: AgentRun[];
}

interface Options<T extends Run> {
  caseId: string | null;
  fetchLatest: (caseId: string) => Promise<T>;
  start: (caseId: string) => Promise<void>;
  rerun: (caseId: string, agent: AgentName) => Promise<void>;
}

/** How many times to ask about a run that has produced nothing yet, before saying it is taking too long. */
const MAX_EMPTY_POLLS = 150;

const messageOf = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);
const isNotFound = (e: unknown): boolean => e instanceof ApiError && e.status === 404;
const isBusy = (d: Run): boolean => d.run_status === "running" || agentsBusy(d.agent_runs);

/**
 * The run behind an agent screen: loads the latest answer for a case, starts the agents, re-runs one, and
 * asks again every few seconds while any agent is waiting or running. "None yet" (404) before the first run
 * is a normal state, not an error. After a start, a 404 is also expected for a moment and is waited out.
 * Failures that stop the screen are returned as `error` with the step "Try again" repeats.
 */
export function useAgentRun<T extends Run>({ caseId, fetchLatest, start, rerun }: Options<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [polling, setPolling] = useState(false);
  /** A run was started and nothing has come back yet. */
  const [waitingForFirst, setWaitingForFirst] = useState(false);
  const fetchRef = useRef(fetchLatest);
  useEffect(() => {
    fetchRef.current = fetchLatest;
  });

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const latest = await fetchRef.current(caseId);
      setData(latest);
      setError(null);
      setPolling(isBusy(latest));
    } catch (e) {
      setData(null);
      setPolling(false);
      setError(isNotFound(e) ? null : { message: messageOf(e, "Could not load the result."), retry: () => void load() });
    } finally {
      setLoaded(true);
    }
  }, [caseId]);

  // A different case starts from scratch.
  useEffect(() => {
    setData(null);
    setLoaded(false);
    setError(null);
    setPolling(false);
    setWaitingForFirst(false);
    void load();
  }, [load]);

  // While the agents work, ask again.
  useEffect(() => {
    if (!caseId || !polling) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let empty = 0;
    const interval = pollIntervalFor(USE_MOCKS);

    const tick = async () => {
      try {
        const latest = await fetchRef.current(caseId);
        if (cancelled) return;
        setData(latest);
        setWaitingForFirst(false);
        if (!isBusy(latest)) {
          setPolling(false);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        if (isNotFound(e) && ++empty <= MAX_EMPTY_POLLS) {
          // Nothing to show yet: the agents have not written anything.
        } else {
          setPolling(false);
          setWaitingForFirst(false);
          setError({
            message: isNotFound(e) ? "The agents are taking longer than expected." : messageOf(e, "Could not check the agents' progress."),
            retry: () => void load(),
          });
          return;
        }
      }
      timer = setTimeout(tick, interval);
    };
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [caseId, polling, load]);

  const onStart = useCallback(async () => {
    if (!caseId) return;
    setError(null);
    try {
      await start(caseId);
      setWaitingForFirst(true);
      setPolling(true);
    } catch (e) {
      setError({ message: messageOf(e, "Could not start the agents."), retry: () => void onStart() });
    }
  }, [caseId, start]);

  /** Re-runs one agent. A failure is thrown, so the caller can show it where the person is looking. */
  const onRerun = useCallback(
    async (agent: AgentName) => {
      if (!caseId) return;
      await rerun(caseId, agent);
      setPolling(true);
    },
    [caseId, rerun],
  );

  return {
    data,
    setData,
    loaded,
    error,
    setError,
    working: waitingForFirst || polling,
    start: onStart,
    rerun: onRerun,
    reload: load,
  };
}
