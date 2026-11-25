"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip } from "@/components/shared/flag-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { getGuidelinePassage } from "@/lib/api";
import { LABEL_TEXT } from "@/lib/guidelines";
import type { GuidelinePassage } from "@/lib/guidelines-types";

interface PassagePanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The passage ID the citation names. */
  passageId: string | null;
  /** The passage, when the answer already carried it. Otherwise it is read from the backend by its ID. */
  passage?: GuidelinePassage;
}

function Detail({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-xs font-semibold text-muted-foreground">{label}</dt>
      <dd className="text-sm text-navy">{value ?? "Not given"}</dd>
    </div>
  );
}

function PassageBody({ passage }: { passage: GuidelinePassage }) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-6">
      <div className="flex flex-wrap items-center gap-2">
        <FlagChip tone={passage.label === "authoritative" ? "success" : "warning"}>{LABEL_TEXT[passage.label]}</FlagChip>
        {passage.version ? <span className="text-xs text-muted-foreground">Version {passage.version}</span> : null}
      </div>
      <blockquote className="border-l-2 border-gold pl-3 text-sm leading-relaxed text-navy">{passage.text}</blockquote>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Detail label="Document" value={passage.source_title} />
        <Detail label="Section" value={passage.heading} />
        <Detail label="Page" value={passage.page !== null ? String(passage.page) : null} />
        <Detail label="Version" value={passage.version} />
      </dl>
      {passage.notice ? (
        <p role="note" className="rounded-lg border border-gold/40 bg-gold/10 px-3 py-2 text-xs text-navy">
          {passage.notice}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The side panel a citation opens: the passage itself with its document, section, page, version and an
 * Authoritative or Illustrative label. An answer normally carries its passages; if one is missing the
 * panel reads it from the backend by its ID, and says so if that fails.
 */
export function PassagePanel({ open, onOpenChange, passageId, passage }: PassagePanelProps) {
  const [loaded, setLoaded] = useState<{ id: string; passage: GuidelinePassage } | null>(null);
  const [error, setError] = useState<{ id: string; message: string } | null>(null);

  const load = useCallback(async () => {
    if (!passageId) return;
    setError(null);
    try {
      setLoaded({ id: passageId, passage: await getGuidelinePassage(passageId) });
    } catch (e) {
      setError({ id: passageId, message: e instanceof Error ? e.message : "The passage could not be loaded." });
    }
  }, [passageId]);

  useEffect(() => {
    if (open && passageId && !passage) void load();
  }, [open, passageId, passage, load]);

  const shown = passage ?? (loaded && loaded.id === passageId ? loaded.passage : null);
  const failure = !passage && error && error.id === passageId ? error.message : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>{shown?.heading ?? "Passage"}</SheetTitle>
          <SheetDescription>{shown ? shown.source_title : "The passage a citation points at."}</SheetDescription>
        </SheetHeader>
        {shown ? (
          <PassageBody passage={shown} />
        ) : failure ? (
          <div className="px-4">
            <ErrorNotice message={failure} onRetry={() => void load()} />
          </div>
        ) : (
          <div role="status" aria-label="Loading the passage" className="space-y-3 px-4">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
