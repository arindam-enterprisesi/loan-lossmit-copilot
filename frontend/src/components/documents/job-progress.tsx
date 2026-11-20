import { cn } from "@/lib/utils";
import type { Job } from "@/lib/types";

const STAGE_LABEL: Record<string, string> = {
  ocr: "Reading the text",
  classify: "Identifying the document type",
  extract: "Extracting the fields",
  checks: "Running checks",
  // Income analysis stages
  gather: "Gathering figures from the documents",
  calculate: "Calculating income",
  explain: "Suggesting possible explanations",
  // Hardship and budget stages
  read: "Reading the hardship letter",
  compare: "Comparing the letter with the documents",
  budget: "Building the budget",
};

/** Plain-language status for a processing job. */
export function jobLabel(job: Pick<Job, "status" | "stage" | "error">): string {
  switch (job.status) {
    case "queued":
      return "Waiting to start";
    case "running":
      return (job.stage && STAGE_LABEL[job.stage]) || "Processing";
    case "succeeded":
      return "Done";
    case "failed":
      return job.error ? `Failed: ${job.error}` : "Failed";
  }
}

interface JobProgressProps {
  job: Job;
  /** What the job is working on, e.g. "2 files". */
  subject?: string;
  className?: string;
}

/** Progress bar for GET /jobs/{id}. Shows what the server reports and does no estimating. */
export function JobProgress({ job, subject, className }: JobProgressProps) {
  const percent = Math.round(job.progress * 100);
  const failed = job.status === "failed";
  return (
    <div className={cn("rounded-lg border bg-panel px-4 py-3", className)}>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-semibold text-navy">
          {subject ? `${subject}: ` : ""}
          {jobLabel(job)}
        </span>
        <span className="text-xs text-muted-foreground">{percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-label="Processing progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-border"
      >
        <div
          className={cn("h-full rounded-full transition-all", failed ? "bg-danger" : "bg-teal")}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
