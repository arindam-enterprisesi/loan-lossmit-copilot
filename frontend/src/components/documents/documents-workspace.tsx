"use client";

import { useCallback, useEffect, useState } from "react";
import { setDocumentType, listDocuments } from "@/lib/api";
import type { Case, DocumentSummary, DocumentType } from "@/lib/types";
import { useJobPoll } from "@/lib/use-job";
import { Skeleton } from "@/components/ui/skeleton";
import { SELECT_CLASS } from "./select-class";
import { DocumentTable } from "./document-table";
import { JobProgress } from "./job-progress";
import { UploadPanel } from "./upload-panel";

interface DocumentsWorkspaceProps {
  cases: Case[];
  pillarSlug: string;
  section: string;
}

/**
 * Upload screen plus the document list for one case. Loads on the client so the list reflects
 * uploads and type changes made in this session (the mock store lives in the browser).
 */
export function DocumentsWorkspace({ cases, pillarSlug, section }: DocumentsWorkspaceProps) {
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [typeJobId, setTypeJobId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      setDocuments(await listDocuments(caseId, { needsReview: needsReviewOnly }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the documents.");
    }
  }, [caseId, needsReviewOnly]);

  useEffect(() => {
    load();
  }, [load]);

  const { job: typeJob } = useJobPoll(typeJobId, () => {
    load();
  });

  // A failure is thrown on purpose: the type dialog shows the message and stays open for a retry.
  const onSetType = async (documentId: string, type: DocumentType, reason?: string) => {
    if (!caseId) return;
    const result = await setDocumentType(caseId, documentId, type, reason);
    if (result.job) setTypeJobId(result.job.id);
    await load();
  };

  const selectedCase = cases.find((c) => c.id === caseId);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Case
          <select
            className={SELECT_CLASS}
            value={caseId ?? ""}
            onChange={(e) => {
              setDocuments(null);
              setCaseId(e.target.value);
            }}
          >
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-1.5 text-sm text-navy">
          <input
            type="checkbox"
            checked={needsReviewOnly}
            onChange={(e) => setNeedsReviewOnly(e.target.checked)}
          />
          Only documents with flagged fields
        </label>
      </div>

      <UploadPanel caseId={caseId} onUploaded={load} onJobFinished={load} />

      {typeJob ? <JobProgress job={typeJob} subject="Re-reading with the chosen type" /> : null}

      <section aria-labelledby="docs-heading">
        <h2 id="docs-heading" className="mb-3 text-lg">
          {selectedCase ? `Documents for ${selectedCase.title}` : "Documents"}
        </h2>
        {error ? (
          <p role="alert" className="mb-3 text-sm text-danger">
            {error}
          </p>
        ) : null}
        {documents ? (
          <DocumentTable
            documents={documents}
            pillarSlug={pillarSlug}
            section={section}
            onSetType={onSetType}
          />
        ) : (
          <Skeleton className="h-40 w-full" />
        )}
      </section>
    </div>
  );
}
