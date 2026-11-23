"use client";

import { useEffect, useRef, useState } from "react";
import { getJob, USE_MOCKS } from "./api";
import type { Job } from "./types";

/** How often to ask the real backend about a job: every 2 seconds, as the Day 3 brief says. */
export const REAL_POLL_MS = 2000;
/** The mock finishes in a few seconds, so ask faster to keep the demo lively. */
export const MOCK_POLL_MS = 700;

export const pollIntervalFor = (useMocks: boolean): number => (useMocks ? MOCK_POLL_MS : REAL_POLL_MS);

export const isJobDone = (job: Pick<Job, "status">): boolean =>
  job.status === "succeeded" || job.status === "failed";

/**
 * Polls GET /jobs/{id} until the job succeeds or fails, then calls `onDone` once.
 * Returns the latest job for the given ID (null before the first answer).
 */
export function useJobPoll(
  jobId: string | null,
  onDone?: (job: Job) => void,
  intervalMs = pollIntervalFor(USE_MOCKS),
): { job: Job | null; error: string | null } {
  const [state, setState] = useState<{ jobId: string | null; job: Job | null; error: string | null }>({
    jobId: null,
    job: null,
    error: null,
  });
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  });

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const job = await getJob(jobId);
        if (cancelled) return;
        setState({ jobId, job, error: null });
        if (isJobDone(job)) {
          doneRef.current?.(job);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setState((s) => ({
          jobId,
          job: s.jobId === jobId ? s.job : null,
          error: e instanceof Error ? e.message : "Could not check progress",
        }));
      }
      timer = setTimeout(tick, intervalMs);
    };
    tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  // An answer stored for a different job ID is stale.
  return state.jobId === jobId ? { job: state.job, error: state.error } : { job: null, error: null };
}
