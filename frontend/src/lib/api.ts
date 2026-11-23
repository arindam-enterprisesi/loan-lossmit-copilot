// Thin API layer. Screens call these functions and never fetch directly, so the swap from mocks
// to the real FastAPI backend (contracts/openapi.yaml) is a flag, not a rewrite.
import { mockCases } from "@/mocks/data";
import {
  adjustBudgetItemMock,
  confirmProfileItemMock,
  getExtractionMock,
  getJobMock,
  getLatestCompletenessMock,
  getLatestHardshipMock,
  getLatestIncomeMock,
  listDocumentsMock,
  overrideCompletenessItemMock,
  pageImageUrlMock,
  reviewFieldMock,
  runCompletenessMock,
  runHardshipMock,
  runIncomeMock,
  setDocumentTypeMock,
  setIncomeComponentMock,
  uploadMock,
} from "@/mocks/store";
import { ApiError } from "./api-error";
import type { ChecklistResult } from "./completeness";
import { cleanReason } from "./documents";
import type { BudgetAdjustmentRequest, HardshipAssessment, ProfileConfirmation } from "./hardship-types";
import {
  adjustmentRequest,
  confirmationRequest,
  type RealHardshipAssessment,
  toHardshipAssessment,
} from "./hardship-real";
import type { IncomeAnalysis, IncomeDecision } from "./income-types";
import type {
  Case,
  DocumentSummary,
  DocumentType,
  Extraction,
  Field,
  FieldReview,
  Job,
  Pillar,
} from "./types";

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function rawRequest(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let message = `API ${res.status} on ${path}`;
    try {
      const body = (await res.json()) as { message?: string };
      if (body.message) message = body.message;
    } catch {
      // keep the default message
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await rawRequest(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  return (await res.json()) as T;
}

export async function listCases(pillar?: Pillar): Promise<Case[]> {
  if (USE_MOCKS) {
    return mockCases.filter((c) => !pillar || c.pillar === pillar);
  }
  const qs = pillar ? `?pillar=${pillar}` : "";
  const data = await request<{ items: Case[] }>(`/cases${qs}`);
  return data.items;
}

export async function listDocuments(
  caseId: string,
  options: { needsReview?: boolean } = {},
): Promise<DocumentSummary[]> {
  if (USE_MOCKS) {
    return listDocumentsMock(caseId, options.needsReview);
  }
  const qs = options.needsReview ? "?needs_review=true" : "";
  const data = await request<{ items: DocumentSummary[] }>(`/cases/${caseId}/documents${qs}`);
  return data.items;
}

/** POST /cases/{id}/documents (multipart). Returns the new documents and the processing job. */
export async function uploadDocuments(
  caseId: string,
  files: File[],
  declaredType: DocumentType | "auto" = "auto",
): Promise<{ documents: DocumentSummary[]; job: Job }> {
  if (USE_MOCKS) {
    return uploadMock(
      caseId,
      files.map((f) => f.name),
      declaredType,
    );
  }
  const body = new FormData();
  for (const f of files) body.append("files", f);
  body.append("declared_type", declaredType);
  // No Content-Type header: the browser sets the multipart boundary itself.
  const res = await rawRequest(`/cases/${caseId}/documents`, { method: "POST", body });
  return (await res.json()) as { documents: DocumentSummary[]; job: Job };
}

/** GET /jobs/{id}. Poll until status is "succeeded" or "failed". */
export async function getJob(jobId: string): Promise<Job> {
  if (USE_MOCKS) return getJobMock(jobId);
  return request<Job>(`/jobs/${jobId}`);
}

/** GET .../extraction: fields (flagged first), document flags and summary. */
export async function getExtraction(caseId: string, documentId: string): Promise<Extraction> {
  if (USE_MOCKS) return getExtractionMock(caseId, documentId);
  return request<Extraction>(`/cases/${caseId}/documents/${documentId}/extraction`);
}

/**
 * PATCH .../fields/{name}: confirm, correct or reject. The original value is always kept by the
 * server. Throws ApiError 409 when `expected_version` is stale and 422 when a reason is missing.
 */
export async function reviewField(
  caseId: string,
  documentId: string,
  fieldName: string,
  review: FieldReview,
): Promise<Field> {
  if (USE_MOCKS) return reviewFieldMock(caseId, documentId, fieldName, review);
  return request<Field>(`/cases/${caseId}/documents/${documentId}/fields/${fieldName}`, {
    method: "PATCH",
    body: JSON.stringify(review),
  });
}

/** PUT .../type: 200 when the type was only confirmed, 202 with a job when extraction is re-queued. */
export async function setDocumentType(
  caseId: string,
  documentId: string,
  docType: DocumentType,
  reason?: string,
): Promise<{ document: DocumentSummary; job?: Job }> {
  const cleaned = cleanReason(reason);
  if (USE_MOCKS) return setDocumentTypeMock(caseId, documentId, docType, cleaned);
  const res = await rawRequest(`/cases/${caseId}/documents/${documentId}/type`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_type: docType, ...(cleaned ? { reason: cleaned } : {}) }),
  });
  const data = (await res.json()) as DocumentSummary | { document: DocumentSummary; job: Job };
  return "document" in data ? data : { document: data };
}

/**
 * POST /cases/{id}/income/analysis: queues a run and returns its job to poll with getJob.
 * Not in contracts/openapi.yaml yet (TODO F2 Income, D4), so the path and the answer (a Job) are our
 * proposal to Arindam. Throws ApiError 422 when the case has no income documents.
 */
export async function runIncomeAnalysis(caseId: string): Promise<Job> {
  if (USE_MOCKS) return runIncomeMock(caseId);
  return request<Job>(`/cases/${caseId}/income/analysis`, { method: "POST" });
}

/** GET /cases/{id}/income/analysis/latest. Throws ApiError 404 before the first run. Same proposal as above. */
export async function getLatestIncome(caseId: string): Promise<IncomeAnalysis> {
  if (USE_MOCKS) return getLatestIncomeMock(caseId);
  return request<IncomeAnalysis>(`/cases/${caseId}/income/analysis/latest`);
}

/**
 * PATCH /cases/{id}/income/analysis/components/{component_id}: include or exclude one component.
 * Returns the whole recalculated analysis, so the screen replaces what it shows. The reason is
 * required (ApiError 422 without it). Same proposal to Arindam as the two calls above.
 */
export async function setIncomeComponent(
  caseId: string,
  componentId: string,
  decision: IncomeDecision,
): Promise<IncomeAnalysis> {
  const clean = { included: decision.included, reason: decision.reason.trim() };
  if (USE_MOCKS) return setIncomeComponentMock(caseId, componentId, clean);
  return request<IncomeAnalysis>(`/cases/${caseId}/income/analysis/components/${componentId}`, {
    method: "PATCH",
    body: JSON.stringify(clean),
  });
}

/**
 * POST /cases/{id}/completeness: runs the checklist and returns the result at once (no job). In the
 * contract. Throws ApiError 422 for an unknown checklist.
 */
export async function runCompleteness(caseId: string, checklistId: string): Promise<ChecklistResult> {
  if (USE_MOCKS) return runCompletenessMock(caseId, checklistId);
  return request<ChecklistResult>(`/cases/${caseId}/completeness`, {
    method: "POST",
    body: JSON.stringify({ checklist_id: checklistId }),
  });
}

/** GET /cases/{id}/completeness/latest. In the contract. Throws ApiError 404 before the first run. */
export async function getLatestCompleteness(caseId: string): Promise<ChecklistResult> {
  if (USE_MOCKS) return getLatestCompletenessMock(caseId);
  return request<ChecklistResult>(`/cases/${caseId}/completeness/latest`);
}

/**
 * PATCH /cases/{id}/completeness/items/{item_id}: override one item with a written reason, which
 * counts it as satisfied. Returns the whole recalculated result. NOT in the contract yet, so the
 * path, the body and the extra item fields (see ChecklistItem) are our proposal to Arindam. The
 * reason is required (ApiError 422 without it).
 */
export async function overrideCompletenessItem(
  caseId: string,
  itemId: string,
  reason: string,
): Promise<ChecklistResult> {
  const cleaned = reason.trim();
  if (USE_MOCKS) return overrideCompletenessItemMock(caseId, itemId, cleaned);
  return request<ChecklistResult>(`/cases/${caseId}/completeness/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify({ reason: cleaned }),
  });
}

/**
 * POST /cases/{id}/hardship-assessment: queues a run (the letter is read by one AI call) and returns
 * its job to poll with getJob. Path from Feature Design 7.8; not in contracts/openapi.yaml yet. The real
 * backend answers `{ job }` (backend/app/api/routers/hardship.py), so the job is taken out of it.
 * Throws ApiError 409 when the case has no hardship letter.
 */
export async function runHardshipAssessment(caseId: string): Promise<Job> {
  if (USE_MOCKS) return runHardshipMock(caseId);
  return (await request<{ job: Job }>(`/cases/${caseId}/hardship-assessment`, { method: "POST" })).job;
}

/**
 * GET /cases/{id}/hardship-assessment/latest: profile, checks, budget and measures. 404 before the
 * first run. The real answer has its own shape (see hardship-real.ts), which is translated here so the
 * screen sees one shape in both modes.
 */
export async function getLatestHardship(caseId: string): Promise<HardshipAssessment> {
  if (USE_MOCKS) return getLatestHardshipMock(caseId);
  return toHardshipAssessment(
    await request<RealHardshipAssessment>(`/cases/${caseId}/hardship-assessment/latest`),
    caseId,
  );
}

/**
 * PUT /cases/{id}/hardship-assessment/latest/confirmations: confirm what the letter reading said for
 * one profile item, or correct it (a correction needs a value and a reason, ApiError 422 without
 * them). The original reading is kept. Returns the whole updated assessment. Same proposal as above.
 */
export async function confirmProfileItem(
  caseId: string,
  confirmation: ProfileConfirmation,
): Promise<HardshipAssessment> {
  const clean: ProfileConfirmation = {
    key: confirmation.key,
    action: confirmation.action,
    ...(confirmation.value?.trim() ? { value: confirmation.value.trim() } : {}),
    ...(confirmation.reason?.trim() ? { reason: confirmation.reason.trim() } : {}),
  };
  if (USE_MOCKS) return confirmProfileItemMock(caseId, clean);
  // The real body names the item: { duration: { value, reason } }, or { duration: {} } to confirm it.
  return toHardshipAssessment(
    await request<RealHardshipAssessment>(`/cases/${caseId}/hardship-assessment/latest/confirmations`, {
      method: "PUT",
      body: JSON.stringify(confirmationRequest(clean)),
    }),
    caseId,
  );
}

/**
 * PATCH /cases/{id}/hardship-assessment/latest/budget/{line_id}: set how much of an expense counts
 * each month, with a required reason (ApiError 422 without one). Never calls the AI. Returns the whole
 * recalculated assessment, so every measure updates at once. The mock keeps the earlier proposed path
 * (`budget-items`); the real backend's path and body (`adjusted_amount`) are used in real mode.
 */
export async function adjustBudgetItem(
  caseId: string,
  itemId: string,
  adjustment: BudgetAdjustmentRequest,
): Promise<HardshipAssessment> {
  const clean = { amount: adjustment.amount.trim(), reason: adjustment.reason.trim() };
  if (USE_MOCKS) return adjustBudgetItemMock(caseId, itemId, clean);
  return toHardshipAssessment(
    await request<RealHardshipAssessment>(`/cases/${caseId}/hardship-assessment/latest/budget/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(adjustmentRequest(clean)),
    }),
    caseId,
  );
}

/** A page picture link. Real links are presigned and expire after a few minutes. */
export interface PageImage {
  url: string;
  /** When the link stops working, if the backend says. */
  expiresAt?: string;
}

/**
 * Asks for the link to one page's image. The contract has no page-image endpoint yet (TODO D3+), so
 * in real mode this answers "none" and the viewer draws a blank page. When the endpoint lands, only
 * this function changes. Always ask again for a fresh link: an old one may have expired.
 */
export async function getPageImage(
  _caseId: string,
  documentId: string,
  page: number,
): Promise<PageImage | undefined> {
  if (USE_MOCKS) {
    const url = pageImageUrlMock(documentId, page);
    return url ? { url } : undefined;
  }
  return undefined;
}
