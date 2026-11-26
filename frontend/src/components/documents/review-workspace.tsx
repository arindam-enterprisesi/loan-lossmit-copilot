"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { DocStatusChip } from "@/components/shared/doc-status-chip";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import { Button, buttonVariants } from "@/components/ui/button";
import { SplitSkeleton } from "@/components/shared/skeletons";
import { useToast } from "@/components/shared/toast";
import { getExtraction, listDocuments, reviewField, setDocumentType } from "@/lib/api";
import { ApiError, isEditConflict } from "@/lib/api-error";
import { docTypeLabel, hasOpenFlags, sortFlaggedFirst } from "@/lib/documents";
import type { DocumentSummary, DocumentType, Extraction, FieldReview } from "@/lib/types";
import { useJobPoll } from "@/lib/use-job";
import { usePageImage } from "@/lib/use-page-image";
import { cn } from "@/lib/utils";
import { boxesFromFields, clampPage, pageCountFor } from "@/lib/viewer";
import { FieldList } from "./field-list";
import { JobProgress } from "./job-progress";
import { PageViewer } from "./page-viewer";
import { TypeDialog } from "./type-dialog";

interface ReviewWorkspaceProps {
  caseId: string;
  documentId: string;
  /** Link back to the document list: /{pillarSlug}/{section}. */
  backHref: string;
}

/** A field was changed by someone else since it was opened. Other failures are toasts. */
type Notice = { kind: "conflict" };

/** Review screen: page image with the cited box on the left, extracted fields on the right. */
export function ReviewWorkspace({ caseId, documentId, backHref }: ReviewWorkspaceProps) {
  const toast = useToast();
  const [doc, setDoc] = useState<DocumentSummary | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [hoveredName, setHoveredName] = useState<string | null>(null);
  // The page being looked at. Picking a field on another page jumps here; the arrows change it too.
  const [viewPage, setViewPage] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // The document exists but has nothing to review yet: an empty state, not an error.
  const [nothingYet, setNothingYet] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [typeOpen, setTypeOpen] = useState(false);
  // Set while the document is being read again after its type changed.
  const [rereadJobId, setRereadJobId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [docs, ext] = await Promise.all([listDocuments(caseId), getExtraction(caseId, documentId)]);
      setDoc(docs.find((d) => d.id === documentId) ?? null);
      setExtraction(ext);
      const first = sortFlaggedFirst(ext.fields)[0];
      setSelectedName((current) => current ?? first?.name ?? null);
      setViewPage((current) => current ?? first?.evidence?.page ?? 1);
      setLoadError(null);
      setNothingYet(false);
      setNotice(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setLoadError(null);
        setNothingYet(true);
      } else {
        setNothingYet(false);
        setLoadError(e instanceof Error ? e.message : "Could not load the document.");
      }
    }
  }, [caseId, documentId]);

  useEffect(() => {
    load();
  }, [load]);

  // When the re-read finishes, forget the old selection (the new type has different fields) and reload.
  const { job: rereadJob } = useJobPoll(rereadJobId, () => {
    setRereadJobId(null);
    setSelectedName(null);
    setViewPage(null);
    load();
  });

  // The picture of the page being looked at. It asks again for a fresh link if the old one expired.
  const pageImage = usePageImage(caseId, documentId, viewPage ?? 1);

  // Sends the new type. A 202 starts the re-read; a 200 only confirmed the type. Failures are thrown
  // so the dialog can show them.
  const onSetType = async (type: DocumentType, reason?: string) => {
    const result = await setDocumentType(caseId, documentId, type, reason);
    if (result.job) setRereadJobId(result.job.id);
    else await load();
  };

  const onReview = async (fieldName: string, review: FieldReview): Promise<boolean> => {
    try {
      const updated = await reviewField(caseId, documentId, fieldName, review);
      setExtraction((current) =>
        current
          ? { ...current, fields: current.fields.map((f) => (f.name === updated.name ? updated : f)) }
          : current,
      );
      setNotice(null);
      // The document's status and flags may have changed with this review.
      const docs = await listDocuments(caseId);
      setDoc(docs.find((d) => d.id === documentId) ?? null);
      return true;
    } catch (e) {
      if (isEditConflict(e)) {
        setNotice({ kind: "conflict" });
      } else {
        // The form keeps what was typed, so "Try again" sends the same review.
        toast.error(e instanceof Error ? e.message : "The change could not be saved.", {
          retry: () => {
            void onReview(fieldName, review);
          },
        });
      }
      return false;
    }
  };

  const selectField = (name: string) => {
    setSelectedName(name);
    const fieldPage = extraction?.fields.find((f) => f.name === name)?.evidence?.page;
    if (fieldPage) setViewPage(fieldPage);
  };

  const backLink = (
    <Link href={backHref} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
      <ArrowLeft className="size-3.5" />
      Back to documents
    </Link>
  );

  if (nothingYet) {
    return (
      <>
        <PageHeader title="Review document" actions={backLink} />
        <EmptyState title="Nothing to review yet" action={<Button variant="outline" size="sm" onClick={load}>Check again</Button>}>
          There is nothing to review for this document yet. It appears here once it has been read.
        </EmptyState>
      </>
    );
  }

  if (loadError) {
    return (
      <>
        <PageHeader title="Review document" actions={backLink} />
        <ErrorNotice message={loadError} onRetry={load} />
      </>
    );
  }

  if (!extraction) {
    return (
      <>
        <PageHeader title="Review document" actions={backLink} />
        <SplitSkeleton label="Loading the document" />
      </>
    );
  }

  const selected = extraction.fields.find((f) => f.name === selectedName) ?? null;
  const evidence = selected?.evidence ?? null;
  const pageCount = pageCountFor(doc?.page_count, extraction.fields);
  const page = clampPage(viewPage ?? 1, pageCount);
  const openCount = extraction.fields.filter(hasOpenFlags).length;
  const rereading = rereadJobId !== null;

  return (
    <>
      <PageHeader
        title={doc?.file_name ?? "Review document"}
        description={[docTypeLabel(extraction.doc_type), doc?.owner].filter(Boolean).join(" · ")}
        actions={
          <>
            {doc ? <DocStatusChip status={doc.status} /> : null}
            <Button size="sm" variant="outline" onClick={() => setTypeOpen(true)} disabled={rereading}>
              Change type
            </Button>
            {backLink}
          </>
        }
      />

      <TypeDialog
        open={typeOpen}
        onOpenChange={setTypeOpen}
        fileName={doc?.file_name ?? "This document"}
        currentType={doc?.doc_type ?? extraction.doc_type}
        onConfirm={onSetType}
      />

      {rereading ? (
        <div className="mb-5 space-y-2">
          {rereadJob ? <JobProgress job={rereadJob} subject="Re-reading with the chosen type" /> : null}
          <p className="text-sm text-muted-foreground">
            The values below are from the old type. Reviewing is paused until the new reading finishes.
          </p>
        </div>
      ) : null}

      {extraction.summary || extraction.flags.length > 0 ? (
        <section className="mb-5 rounded-xl border bg-card p-4">
          {extraction.summary ? <p className="text-sm text-navy">{extraction.summary}</p> : null}
          {extraction.flags.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {extraction.flags.map((f, i) => (
                <li key={`${f.code}-${i}`} className="flex items-start gap-2 text-sm">
                  <FlagChip tone={severityTone(f.severity)}>{f.code}</FlagChip>
                  <span className="text-navy">{f.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {notice ? (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-navy"
        >
          <span>
            This value changed since you opened it. Reload to see the latest before changing it.
          </span>
          <Button size="sm" variant="outline" onClick={load}>
            Reload
          </Button>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="lg:sticky lg:top-6 lg:self-start">
          <PageViewer
            title={selected ? `Source of ${selected.name.replace(/_/g, " ")}` : "Evidence"}
            page={page}
            pageCount={pageCount}
            onPageChange={setViewPage}
            imageUrl={pageImage.url}
            onImageError={pageImage.onImageError}
            onImageLoad={pageImage.onImageLoad}
            boxes={boxesFromFields(extraction.fields)}
            selectedName={selectedName}
            hoveredName={hoveredName}
            onSelect={selectField}
            onHover={setHoveredName}
            lineIds={evidence?.line_ids ?? []}
          />
        </div>
        <section aria-labelledby="fields-heading">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="fields-heading" className="text-lg">
              Extracted fields
            </h2>
            <span className="text-sm text-muted-foreground">
              {openCount > 0 ? `${openCount} to look at` : "Nothing flagged"}
            </span>
          </div>
          <FieldList
            fields={extraction.fields}
            selectedName={selectedName}
            hoveredName={hoveredName}
            onSelect={selectField}
            onHover={setHoveredName}
            onReview={onReview}
            disabled={rereading}
          />
        </section>
      </div>
    </>
  );
}
