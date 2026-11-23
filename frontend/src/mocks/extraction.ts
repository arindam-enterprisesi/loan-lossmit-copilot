// Mock extractions shaped like GET /cases/{id}/documents/{id}/extraction. Synthetic demo data.
// Values are strings exactly as the backend would normalise them. No arithmetic is done here: the
// pay stub mismatch (DI-CHK-02) is the flag text the backend returns in the Feature Design story.
import type { BoundingBox, Evidence, Extraction, Field, Flag } from "@/lib/types";

export const PAYSTUB_DOC_ID = "d1000000-0000-4000-8000-000000000001";
export const BANK_DOC_DANIEL_ID = "d1000000-0000-4000-8000-000000000002";
export const BANK_DOC_ANGELA_ID = "d2000000-0000-4000-8000-000000000004";

const RUN_ID = "aaaaaaaa-0000-4000-8000-000000000001";

const ev = (documentId: string, page: number, lineIds: string[], bbox?: BoundingBox): Evidence => ({
  document_id: documentId,
  page,
  line_ids: lineIds,
  ...(bbox ? { bbox } : {}),
});

const field = (
  name: string,
  value: string,
  certainty: Field["certainty"],
  evidence: Evidence | null,
  flags: Flag[] = [],
): Field => ({
  name,
  value,
  original_value: value,
  certainty,
  flags,
  evidence,
  review_status: "unreviewed",
  reviewed_by: null,
  reviewed_at: null,
  review_reason: null,
  version: 1,
});

// Boxes match the mock page image in public/mock/paystub-p1.svg (fractions of the page).
const box = (x0: number, y0: number, x1: number, y1: number): BoundingBox => ({ x0, y0, x1, y1 });

const payStub: Extraction = {
  document_id: PAYSTUB_DOC_ID,
  run_id: RUN_ID,
  doc_type: "pay_stub",
  prompt_id: "extract@1",
  provider: "mock",
  model: "mock",
  summary: "Pay stub for 14 to 27 September 2026.",
  flags: [],
  fields: [
    field("net_pay_current", "2083.61", "low", ev(PAYSTUB_DOC_ID, 1, ["p1-L31"], box(0.242, 0.4, 0.311, 0.41)), [
      {
        code: "DI-CHK-02",
        severity: "error",
        message: "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61",
        evidence: ev(PAYSTUB_DOC_ID, 1, ["p1-L31"], box(0.242, 0.4, 0.311, 0.41)),
      },
    ]),
    field("employer_name", "Northwind Logistics Inc.", "high", ev(PAYSTUB_DOC_ID, 1, ["p1-L02"], box(0.1, 0.07, 0.46, 0.09))),
    field("pay_period_start", "2026-09-14", "high", ev(PAYSTUB_DOC_ID, 1, ["p1-L25"], box(0.242, 0.3, 0.318, 0.31))),
    field("pay_period_end", "2026-09-27", "high", ev(PAYSTUB_DOC_ID, 1, ["p1-L26"], box(0.242, 0.32, 0.318, 0.33))),
    field("gross_pay_current", "3070.50", "high", ev(PAYSTUB_DOC_ID, 1, ["p1-L29"], box(0.242, 0.36, 0.311, 0.37))),
    field("total_deductions_current", "1036.89", "high", ev(PAYSTUB_DOC_ID, 1, ["p1-L30"], box(0.242, 0.38, 0.311, 0.39))),
  ],
};

const confirmed = (f: Field): Field => ({
  ...f,
  review_status: "confirmed",
  reviewed_by: "demo.reviewer",
  reviewed_at: "2026-11-02T11:00:00Z",
  version: 2,
});

const bankDaniel: Extraction = {
  document_id: BANK_DOC_DANIEL_ID,
  run_id: RUN_ID,
  doc_type: "bank_statement",
  prompt_id: "extract@1",
  provider: "mock",
  model: "mock",
  summary: "Bank statement for September 2026.",
  flags: [],
  fields: [
    // Boxes match public/mock/bank-p1.svg and bank-p3.svg.
    confirmed(
      field("account_holder", "Daniel Reyes", "high", ev(BANK_DOC_DANIEL_ID, 1, ["p1-L04"], box(0.242, 0.146, 0.329, 0.157))),
    ),
    confirmed(
      field("statement_period_end", "2026-09-30", "high", ev(BANK_DOC_DANIEL_ID, 1, ["p1-L07"], box(0.242, 0.185, 0.318, 0.196))),
    ),
    confirmed(
      field("ending_balance", "4210.35", "high", ev(BANK_DOC_DANIEL_ID, 3, ["p3-L18"], box(0.242, 0.574, 0.301, 0.585))),
    ),
  ],
};

const bankAngela: Extraction = {
  document_id: BANK_DOC_ANGELA_ID,
  run_id: RUN_ID,
  doc_type: "bank_statement",
  prompt_id: "extract@1",
  provider: "mock",
  model: "mock",
  summary: "Bank statement for October 2026.",
  flags: [
    {
      code: "DI-W601",
      severity: "warning",
      message: "Printed page count does not match the pages uploaded",
    },
  ],
  fields: [
    field("account_holder", "Angela Whitfield", "high", ev(BANK_DOC_ANGELA_ID, 1, ["p1-L04"])),
    field("statement_period_start", "2026-10-01", "high", ev(BANK_DOC_ANGELA_ID, 1, ["p1-L06"])),
    field("statement_period_end", "2026-10-31", "high", ev(BANK_DOC_ANGELA_ID, 1, ["p1-L07"])),
    field("ending_balance", "1893.20", "medium", ev(BANK_DOC_ANGELA_ID, 3, ["p3-L18"])),
  ],
};

/** Hand-written extractions keyed by document ID. Other documents get a basic one (see store.ts). */
export const seedExtractions: Extraction[] = [payStub, bankDaniel, bankAngela];

/** Which mock documents have a page image to show beside the fields. */
export const MOCK_PAGE_IMAGES: Record<string, Record<number, string>> = {
  [PAYSTUB_DOC_ID]: { 1: "/mock/paystub-p1.svg" },
  [BANK_DOC_DANIEL_ID]: { 1: "/mock/bank-p1.svg", 2: "/mock/bank-p2.svg", 3: "/mock/bank-p3.svg" },
};
