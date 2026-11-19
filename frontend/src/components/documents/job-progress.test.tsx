import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Job } from "@/lib/types";
import { JobProgress, jobLabel } from "./job-progress";

const job = (over: Partial<Job>): Job => ({ id: "j", status: "queued", progress: 0, ...over });

describe("jobLabel", () => {
  it("describes each state in plain language", () => {
    expect(jobLabel({ status: "queued" })).toBe("Waiting to start");
    expect(jobLabel({ status: "running", stage: "extract" })).toBe("Extracting the fields");
    expect(jobLabel({ status: "running", stage: "something_new" })).toBe("Processing");
    expect(jobLabel({ status: "succeeded" })).toBe("Done");
    expect(jobLabel({ status: "failed", error: "OCR timed out" })).toBe("Failed: OCR timed out");
    expect(jobLabel({ status: "failed" })).toBe("Failed");
  });
});

describe("JobProgress", () => {
  it("shows the server progress as a percentage", () => {
    render(<JobProgress job={job({ status: "running", progress: 0.42, stage: "ocr" })} subject="2 files" />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByText("2 files: Reading the text")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("shows a finished job at 100%", () => {
    render(<JobProgress job={job({ status: "succeeded", progress: 1 })} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("Done")).toBeInTheDocument();
  });
});
