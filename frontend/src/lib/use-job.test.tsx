import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "./types";
import { isJobDone, MOCK_POLL_MS, pollIntervalFor, REAL_POLL_MS, useJobPoll } from "./use-job";

// Pretend we are talking to the real backend, so the default interval is the real one.
vi.mock("./api", () => ({ getJob: vi.fn(), USE_MOCKS: false }));
import { getJob } from "./api";

const job = (status: Job["status"]): Job =>
  ({ id: "j1", status, progress: status === "succeeded" ? 1 : 0.4, stage: "extract" }) as Job;

describe("poll interval", () => {
  it("is 2 seconds against the real backend and faster for the mock", () => {
    expect(REAL_POLL_MS).toBe(2000);
    expect(pollIntervalFor(false)).toBe(2000);
    expect(pollIntervalFor(true)).toBe(MOCK_POLL_MS);
    expect(MOCK_POLL_MS).toBeLessThan(REAL_POLL_MS);
  });
});

describe("isJobDone", () => {
  it("is true only for succeeded and failed", () => {
    expect(isJobDone({ status: "succeeded" })).toBe(true);
    expect(isJobDone({ status: "failed" })).toBe(true);
    expect(isJobDone({ status: "queued" })).toBe(false);
    expect(isJobDone({ status: "running" })).toBe(false);
  });
});

describe("useJobPoll", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getJob).mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("asks straight away, then once every 2 seconds, not sooner", async () => {
    vi.mocked(getJob).mockResolvedValue(job("running"));
    renderHook(() => useJobPoll("j1"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(getJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(getJob).toHaveBeenCalledTimes(2);
  });

  it("stops asking and calls onDone once when the job succeeds", async () => {
    vi.mocked(getJob).mockResolvedValueOnce(job("running")).mockResolvedValue(job("succeeded"));
    const onDone = vi.fn();
    const { result } = renderHook(() => useJobPoll("j1", onDone));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(result.current.job?.status).toBe("succeeded");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(getJob).toHaveBeenCalledTimes(2);
  });

  it("does nothing without a job ID", async () => {
    renderHook(() => useJobPoll(null));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(getJob).not.toHaveBeenCalled();
  });
});
