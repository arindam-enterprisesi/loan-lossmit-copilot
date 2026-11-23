"use client";

import Link from "next/link";
import { FlagChip } from "@/components/shared/flag-chip";
import { Button } from "@/components/ui/button";
import { canOverride, ITEM_STATUS_LABEL, ITEM_STATUS_TONE, type ChecklistItem } from "@/lib/completeness";
import { formatDate } from "@/lib/format";

interface CompletenessListProps {
  items: ChecklistItem[];
  /** Where a document's review screen is: `${documentBase}/${documentId}`. */
  documentBase: string;
  /** File names by document ID, to label the links. A document not in the map is just called "Document". */
  documentNames: Record<string, string>;
  /** Opens the override window for an item. Without it the list is read-only (no buttons). */
  onOverride?: (item: ChecklistItem) => void;
}

/** One row per checklist item: status chip, the reason, the documents used, and any override. */
export function CompletenessList({ items, documentBase, documentNames, onOverride }: CompletenessListProps) {
  return (
    <ul className="divide-y rounded-xl border bg-card">
      {items.map((item) => (
        <li key={item.item_id} data-testid={`item-${item.item_id}`} className="space-y-1 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <FlagChip tone={ITEM_STATUS_TONE[item.status]}>{ITEM_STATUS_LABEL[item.status]}</FlagChip>
            <span className="font-semibold text-navy">{item.label}</span>
            {onOverride && canOverride(item) ? (
              <Button
                variant="outline"
                size="sm"
                className="ml-auto"
                onClick={() => onOverride(item)}
                aria-label={`Override ${item.label}`}
              >
                Override
              </Button>
            ) : null}
          </div>
          <p className="text-sm text-muted-foreground">{item.reason}</p>

          {item.document_ids && item.document_ids.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              Documents used:{" "}
              {item.document_ids.map((id, i) => (
                <span key={id}>
                  {i > 0 ? ", " : ""}
                  <Link href={`${documentBase}/${id}`} className="underline underline-offset-2 hover:text-navy">
                    {documentNames[id] ?? "Document"}
                  </Link>
                </span>
              ))}
            </p>
          ) : null}

          {item.status === "overridden" ? (
            <div className="space-y-0.5 rounded-lg bg-panel px-3 py-2 text-xs text-muted-foreground">
              <div>
                Overridden{item.overridden_by ? ` by ${item.overridden_by}` : ""}
                {item.overridden_at ? `, ${formatDate(item.overridden_at)}` : ""}
              </div>
              <div>Reason: {item.override_reason}</div>
              {item.original_status ? (
                <div>The checklist found: {ITEM_STATUS_LABEL[item.original_status].toLowerCase()}</div>
              ) : null}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
