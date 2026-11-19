"use client";

import { useEffect, useRef, useState } from "react";
import { getJob } from "./api";
import type { Job } from "./types";

export const isJobDone = (job: Pick<Job, "status">): boolean =>
  job.status === "succeeded" || job.status === "failed";

/**
 * Polls GET /jobs/{id} until the job succeeds or fails, then calls `onDone` once.
 * Returns the latest job for the given ID (null before the first answer).
 */
export function useJobPoll(
  jobId: string | null,
  onDone?: (job: Job) => void,
  intervalMs = 700,
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
