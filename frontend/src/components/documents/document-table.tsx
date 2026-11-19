"use client";

import Link from "next/link";
import { DocStatusChip } from "@/components/shared/doc-status-chip";
import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import { buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { docTypeLabel } from "@/lib/documents";
import { formatDate } from "@/lib/format";
import type { DocumentSummary, DocumentType } from "@/lib/types";
import { cn } from "@/lib/utils";
import { TypePicker } from "./type-picker";

interface DocumentTableProps {
  documents: DocumentSummary[];
  /** URL pieces for the review link: /{pillarSlug}/{section}/{caseId}/{documentId}. */
  pillarSlug: string;
  section: string;
  onSetType: (documentId: string, type: DocumentType) => void | Promise<void>;
}

function period(doc: DocumentSummary): string {
  if (!doc.period_start && !doc.period_end) return "—";
  return `${formatDate(doc.period_start)} to ${formatDate(doc.period_end)}`;
}

export function DocumentTable({ documents, pillarSlug, section, onSetType }: DocumentTableProps) {
  if (documents.length === 0) {
    return (
      <div className="rounded-xl border border-dashed bg-panel p-8 text-center text-sm text-muted-foreground">
        No documents to show.
      </div>
    );
  }

  return (
    <div className="rounded-xl border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Document</TableHead>
            <TableHead>Owner</TableHead>
            <TableHead>Period</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Flags</TableHead>
            <TableHead className="text-right">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents.map((d) => (
            <TableRow key={d.id}>
              <TableCell>
                <div className="font-semibold text-navy">{d.file_name}</div>
                <div className="text-xs text-muted-foreground">{docTypeLabel(d.doc_type)}</div>
              </TableCell>
              <TableCell>{d.owner ?? "—"}</TableCell>
              <TableCell>{period(d)}</TableCell>
              <TableCell>
                <DocStatusChip status={d.status} />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {d.flags.length === 0 ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    d.flags.map((f) => (
                      <FlagChip key={f.code} tone={severityTone(f.severity)}>
                        {f.code}
                      </FlagChip>
                    ))
                  )}
                </div>
              </TableCell>
              <TableCell className="text-right">
                {d.status === "type_needed" ? (
                  <div className="flex justify-end">
                    <TypePicker onConfirm={(type) => onSetType(d.id, type)} />
                  </div>
                ) : d.status === "processing" || d.status === "uploaded" ? (
                  <span className="text-xs text-muted-foreground">Processing…</span>
                ) : d.status === "failed" ? (
                  <span className="text-xs text-danger">Failed</span>
                ) : (
                  <Link
                    href={`/${pillarSlug}/${section}/${d.case_id}/${d.id}`}
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                  >
                    {d.status === "needs_review" ? "Review" : "View"}
                  </Link>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
