"use client";

import { Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { useToast } from "@/components/shared/toast";
import { Button } from "@/components/ui/button";
import { uploadDocuments } from "@/lib/api";
import { checkFiles, DOCUMENT_TYPES, docTypeLabel } from "@/lib/documents";
import type { DocumentType } from "@/lib/types";
import { useJobPoll } from "@/lib/use-job";
import { cn } from "@/lib/utils";
import { JobProgress } from "./job-progress";
import { SELECT_CLASS } from "./select-class";

interface UploadPanelProps {
  caseId: string | null;
  /** Called right after the upload is accepted, so the list can show the new rows. */
  onUploaded?: () => void;
  /** Called once the processing job succeeds or fails, so the list can refresh. */
  onJobFinished?: () => void;
}

/** Drop zone, document type and upload button for one case. Shows progress while the job runs. */
export function UploadPanel({ caseId, onUploaded, onJobFinished }: UploadPanelProps) {
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [declaredType, setDeclaredType] = useState<DocumentType | "auto">("auto");
  const [problems, setProblems] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<{ id: string; subject: string } | null>(null);

  const { job: liveJob, error: pollError } = useJobPoll(job?.id ?? null, () => onJobFinished?.());

  const addFiles = (incoming: File[]) => {
    const { accepted, rejected } = checkFiles(incoming);
    setProblems(rejected.map((r) => `${r.name}: ${r.reason}`));
    setFiles((current) => [...current, ...accepted]);
  };

  const submit = async () => {
    if (!caseId || files.length === 0) return;
    setUploading(true);
    setProblems([]);
    try {
      const result = await uploadDocuments(caseId, files, declaredType);
      setJob({ id: result.job.id, subject: `${files.length} ${files.length === 1 ? "file" : "files"}` });
      setFiles([]);
      onUploaded?.();
    } catch (e) {
      // The files stay in the list, so "Try again" sends the same ones.
      toast.error(e instanceof Error ? e.message : "The upload did not finish.", { retry: () => submit() });
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="rounded-xl border bg-card p-5">
      <h2 className="text-lg">Upload documents</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        PDF, PNG or JPEG. Each file is read, typed and checked, then waits for a person to review it.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(Array.from(e.dataTransfer.files));
        }}
        className={cn(
          "mt-4 flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors",
          dragging ? "border-teal bg-teal/5" : "border-border bg-panel",
        )}
      >
        <Upload className="size-6 text-teal" aria-hidden />
        <p className="text-sm text-navy">Drag files here, or</p>
        <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()} disabled={!caseId}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="application/pdf,image/png,image/jpeg,.pdf,.png,.jpg,.jpeg"
          aria-label="Choose files"
          className="sr-only"
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []));
            e.target.value = ""; // allow choosing the same file again
          }}
        />
      </div>

      {problems.length > 0 ? (
        <ul role="alert" className="mt-3 space-y-1 text-sm text-danger">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}

      {files.length > 0 ? (
        <ul className="mt-4 divide-y rounded-lg border">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="truncate text-navy">{f.name}</span>
              <button
                type="button"
                aria-label={`Remove ${f.name}`}
                className="text-muted-foreground hover:text-danger"
                onClick={() => setFiles((current) => current.filter((_, idx) => idx !== i))}
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Document type
          <select
            className={SELECT_CLASS}
            value={declaredType}
            onChange={(e) => setDeclaredType(e.target.value as DocumentType | "auto")}
          >
            <option value="auto">Auto-detect</option>
            {DOCUMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {docTypeLabel(t)}
              </option>
            ))}
          </select>
        </label>
        <Button onClick={submit} disabled={!caseId || files.length === 0 || uploading}>
          {uploading ? "Uploading…" : `Upload${files.length > 0 ? ` ${files.length}` : ""}`}
        </Button>
      </div>

      {job ? (
        <div className="mt-4">
          {liveJob ? (
            <JobProgress job={liveJob} subject={job.subject} />
          ) : (
            <p className="text-sm text-muted-foreground">Starting…</p>
          )}
          {pollError ? <p className="mt-2 text-xs text-danger">{pollError}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
