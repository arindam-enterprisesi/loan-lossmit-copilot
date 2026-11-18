import { FlagChip, type ChipTone } from "./flag-chip";
import { DOC_STATUS_LABEL } from "@/lib/format";
import type { DocumentStatus } from "@/lib/types";

const TONE: Record<DocumentStatus, ChipTone> = {
  uploaded: "neutral",
  processing: "info",
  type_needed: "warning",
  needs_review: "danger",
  reviewed: "success",
  failed: "danger",
};

export function DocStatusChip({ status }: { status: DocumentStatus }) {
  return <FlagChip tone={TONE[status]}>{DOC_STATUS_LABEL[status]}</FlagChip>;
}
