// Mock data shaped exactly like contracts/openapi.yaml responses. Synthetic, for demonstration only.
// Used while NEXT_PUBLIC_USE_MOCKS=true or until an endpoint is merged. Figures follow the Feature
// Design demo stories (Daniel Reyes, Angela Whitfield) but no arithmetic is done here.
import type { Case, DocumentSummary } from "@/lib/types";

export const DANIEL_CASE_ID = "11111111-1111-4111-8111-111111111111";
export const ANGELA_CASE_ID = "22222222-2222-4222-8222-222222222222";

/** Display references from the PRD screens. Mock only: the real API has no such field yet. */
export const MOCK_CASE_REFS: Record<string, string> = {
  [DANIEL_CASE_ID]: "LP-0001",
  [ANGELA_CASE_ID]: "LM-0001",
};

export const mockCases: Case[] = [
  {
    id: DANIEL_CASE_ID,
    title: "Daniel Reyes — purchase",
    pillar: "underwriting",
    profile: {
      borrower_names: ["Daniel Reyes"],
      employment_type: "wage_earner",
      reference_date: "2026-11-02",
    },
    document_count: 4,
    created_at: "2026-11-02T09:00:00Z",
  },
  {
    id: ANGELA_CASE_ID,
    title: "Angela Whitfield — hardship",
    pillar: "loss_mitigation",
    profile: {
      borrower_names: ["Angela Whitfield"],
      employment_type: "wage_earner",
      reference_date: "2026-11-02",
    },
    document_count: 5,
    created_at: "2026-11-02T09:30:00Z",
  },
];

const doc = (
  id: string,
  caseId: string,
  over: Partial<DocumentSummary> & Pick<DocumentSummary, "file_name" | "status">,
): DocumentSummary => ({
  id,
  case_id: caseId,
  flags: [],
  uploaded_at: "2026-11-02T10:00:00Z",
  ...over,
});

export const mockDocuments: DocumentSummary[] = [
  doc("d1000000-0000-4000-8000-000000000001", DANIEL_CASE_ID, {
    file_name: "reyes_paystub_2026-09.pdf",
    status: "needs_review",
    doc_type: "pay_stub",
    type_certainty: "high",
    page_count: 1,
    owner: "Daniel Reyes",
    period_start: "2026-09-14",
    period_end: "2026-09-27",
    summary: "Pay stub for 14 to 27 September 2026.",
    flags: [
      {
        code: "DI-CHK-02",
        severity: "error",
        message: "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61",
        evidence: { document_id: "d1000000-0000-4000-8000-000000000001", page: 1, line_ids: ["p1-L31"] },
      },
    ],
  }),
  doc("d1000000-0000-4000-8000-000000000002", DANIEL_CASE_ID, {
    file_name: "reyes_bank_statement_2026-09.pdf",
    status: "reviewed",
    doc_type: "bank_statement",
    type_certainty: "high",
    page_count: 3,
    owner: "Daniel Reyes",
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    summary: "Bank statement for September 2026.",
  }),
  doc("d1000000-0000-4000-8000-000000000003", DANIEL_CASE_ID, {
    file_name: "reyes_w2_2025.pdf",
    status: "reviewed",
    doc_type: "w2",
    type_certainty: "high",
    page_count: 1,
    owner: "Daniel Reyes",
    summary: "W-2 for tax year 2025.",
  }),
  doc("d1000000-0000-4000-8000-000000000004", DANIEL_CASE_ID, {
    file_name: "scan_0042.jpg",
    status: "type_needed",
    doc_type: null,
    type_certainty: "low",
    page_count: 1,
    owner: null,
    summary: null,
    flags: [
      {
        code: "DI-W501",
        severity: "warning",
        message: "The type could not be told with certainty. Choose a type to continue.",
      },
    ],
  }),
  doc("d2000000-0000-4000-8000-000000000001", ANGELA_CASE_ID, {
    file_name: "whitfield_assistance_application.pdf",
    status: "reviewed",
    doc_type: "mortgage_assistance_application",
    type_certainty: "high",
    page_count: 4,
    owner: "Angela Whitfield",
    summary: "Mortgage assistance application.",
  }),
  doc("d2000000-0000-4000-8000-000000000002", ANGELA_CASE_ID, {
    file_name: "whitfield_hardship_letter.pdf",
    status: "reviewed",
    doc_type: "hardship_letter",
    type_certainty: "high",
    page_count: 1,
    owner: "Angela Whitfield",
    summary: "Hardship letter.",
  }),
  doc("d2000000-0000-4000-8000-000000000003", ANGELA_CASE_ID, {
    file_name: "whitfield_mortgage_statement.pdf",
    status: "reviewed",
    doc_type: "mortgage_statement",
    type_certainty: "high",
    page_count: 2,
    owner: "Angela Whitfield",
    summary: "Servicer mortgage statement.",
  }),
  doc("d2000000-0000-4000-8000-000000000004", ANGELA_CASE_ID, {
    file_name: "whitfield_bank_statement_2026-10.pdf",
    status: "needs_review",
    doc_type: "bank_statement",
    type_certainty: "high",
    page_count: 3,
    owner: "Angela Whitfield",
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    summary: "Bank statement for October 2026.",
    flags: [
      {
        code: "DI-W601",
        severity: "warning",
        message: "Printed page count does not match the pages uploaded",
      },
    ],
  }),
  doc("d2000000-0000-4000-8000-000000000005", ANGELA_CASE_ID, {
    file_name: "whitfield_paystub_2026-10.pdf",
    status: "processing",
    doc_type: "pay_stub",
    type_certainty: "medium",
    page_count: 1,
    owner: "Angela Whitfield",
    summary: null,
  }),
];
