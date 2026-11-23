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
  askGuidelineMock,
  getGuidelinePassageMock,
  getLatestAssetsMock,
  getLatestIncomeMock,
  getLoanScenarioMock,
  listDocumentsMock,
  listGuidelineSourcesMock,
  overrideCompletenessItemMock,
  pageImageUrlMock,
  putLoanScenarioMock,
  reviewFieldMock,
  reviewObligationMock,
  reviewTransactionMock,
  runAssetsMock,
  runCompletenessMock,
  runHardshipMock,
  runIncomeMock,
  sendGuidelineFeedbackMock,
  setDocumentTypeMock,
  setIncomeComponentMock,
  uploadMock,
} from "@/mocks/store";
import { ApiError } from "./api-error";
import {
  obligationRequest,
  scenarioRequest,
  toAssetAnalysis,
  toLoanScenario,
  transactionRequest,
  type RealAssetAnalysis,
  type RealLoanScenario,
} from "./assets-real";
import type {
  AssetAnalysis,
  LoanScenario,
  LoanScenarioInput,
  ObligationReview,
  TransactionReview,
} from "./assets-types";
import type { ChecklistResult } from "./completeness";
import { cleanReason } from "./documents";
import { toGuidelinePassage, toGuidelineSource, type RealPassage, type RealSource } from "./guidelines-real";
import type { FeedbackRating, GuidelineAnswer, GuidelinePassage, GuidelineSource, SourceSet } from "./guidelines-types";
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

/**
 * Where a call goes. In the browser it goes to this app's own `/api/proxy`, which adds the access token
 * from an httpOnly cookie and forwards it to the backend (see lib/proxy.ts), so no token is ever in a
 * script and no cross-site call is made. On the Next server it goes straight to the backend.
 */
const baseUrl = () => (typeof window === "undefined" ? API_URL : "/api/proxy");

/** What happens when the backend refuses the token. A separate object so a test can replace it. */
export const sessionEnded = {
  redirect: () => window.location.assign("/login?expired=1"),
};

async function rawRequest(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${baseUrl()}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    // The token ended or was refused: go to the sign-in page, which says the session ended.
    if (res.status === 401 && typeof window !== "undefined") sessionEnded.redirect();
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
 * each month, with a required reason (ApiError 422 without one), or clears an earlier adjustment when the
 * amount is null. Never calls the AI. Returns the whole
 * recalculated assessment, so every measure updates at once. The mock keeps the earlier proposed path
 * (`budget-items`); the real backend's path and body (`adjusted_amount`) are used in real mode.
 */
export async function adjustBudgetItem(
  caseId: string,
  itemId: string,
  adjustment: BudgetAdjustmentRequest,
): Promise<HardshipAssessment> {
  const clean = { amount: adjustment.amount === null ? null : adjustment.amount.trim(), reason: adjustment.reason.trim() };
  if (USE_MOCKS) return adjustBudgetItemMock(caseId, itemId, clean);
  return toHardshipAssessment(
    await request<RealHardshipAssessment>(`/cases/${caseId}/hardship-assessment/latest/budget/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(adjustmentRequest(clean)),
    }),
    caseId,
  );
}

/**
 * GET /cases/{id}/loan-scenario: the sample loan entered for a case. Throws ApiError 404 when none has
 * been entered. Not in contracts/openapi.yaml yet (Feature Design 3.7); the real answer is translated.
 */
export async function getLoanScenario(caseId: string): Promise<LoanScenario> {
  if (USE_MOCKS) return getLoanScenarioMock(caseId);
  return toLoanScenario(await request<RealLoanScenario>(`/cases/${caseId}/loan-scenario`));
}

/**
 * PUT /cases/{id}/loan-scenario: enter the sample loan by hand, or replace it. Amounts are text. Throws
 * ApiError 422 when a value is not acceptable (a property value of zero, an amount with three decimals).
 */
export async function putLoanScenario(caseId: string, input: LoanScenarioInput): Promise<LoanScenario> {
  const clean = scenarioRequest({
    purpose: input.purpose.trim(),
    occupancy: input.occupancy.trim(),
    property_value: input.property_value.trim(),
    loan_amount: input.loan_amount.trim(),
    proposed_housing_payment: input.proposed_housing_payment.trim(),
    funds_to_close: input.funds_to_close.trim(),
  });
  if (USE_MOCKS) return putLoanScenarioMock(caseId, clean);
  return toLoanScenario(
    await request<RealLoanScenario>(`/cases/${caseId}/loan-scenario`, { method: "PUT", body: JSON.stringify(clean) }),
  );
}

/**
 * POST /cases/{id}/asset-liability: queues a run and returns its job to poll with getJob. The real
 * backend answers `{ job, analysis_id }`, so the job is taken out of it. Needs the loan scenario first.
 */
export async function runAssetAnalysis(caseId: string): Promise<Job> {
  if (USE_MOCKS) return runAssetsMock(caseId);
  return (await request<{ job: Job }>(`/cases/${caseId}/asset-liability`, { method: "POST" })).job;
}

/** GET /cases/{id}/asset-liability/latest. Throws ApiError 404 before the first run. */
export async function getLatestAssetAnalysis(caseId: string): Promise<AssetAnalysis> {
  if (USE_MOCKS) return getLatestAssetsMock(caseId);
  return toAssetAnalysis(await request<RealAssetAnalysis>(`/cases/${caseId}/asset-liability/latest`), caseId);
}

/**
 * PATCH /cases/{id}/asset-liability/latest/transactions/{id}: give a line another category, or mark a
 * deposit as sourced, with a required reason (ApiError 422 without one). Returns the whole recalculated
 * analysis, so every figure updates at once. What the system chose is kept beside the change.
 */
export async function reviewTransaction(
  caseId: string,
  transactionId: string,
  review: TransactionReview,
): Promise<AssetAnalysis> {
  const clean: TransactionReview = { ...review, reason: review.reason.trim() };
  if (USE_MOCKS) return reviewTransactionMock(caseId, transactionId, clean);
  return toAssetAnalysis(
    await request<RealAssetAnalysis>(`/cases/${caseId}/asset-liability/latest/transactions/${transactionId}`, {
      method: "PATCH",
      body: JSON.stringify(transactionRequest(clean)),
    }),
    caseId,
  );
}

/**
 * PATCH /cases/{id}/asset-liability/latest/obligations/{id}: count a debt toward the DTI or leave it
 * out, with a required reason. Returns the whole recalculated analysis; the ratios update at once.
 */
export async function reviewObligation(
  caseId: string,
  obligationId: string,
  review: ObligationReview,
): Promise<AssetAnalysis> {
  const clean = obligationRequest({ counts_toward_dti: review.counts_toward_dti, reason: review.reason.trim() });
  if (USE_MOCKS) return reviewObligationMock(caseId, obligationId, clean);
  return toAssetAnalysis(
    await request<RealAssetAnalysis>(`/cases/${caseId}/asset-liability/latest/obligations/${obligationId}`, {
      method: "PATCH",
      body: JSON.stringify(clean),
    }),
    caseId,
  );
}

/** GET /guidelines/sources: the loaded sources with their labels. On `main` (read only). */
export async function listGuidelineSources(): Promise<GuidelineSource[]> {
  if (USE_MOCKS) return listGuidelineSourcesMock();
  return (await request<{ items: RealSource[] }>("/guidelines/sources")).items.map(toGuidelineSource);
}

/** GET /guidelines/passages/{id}: one passage by the ID an answer or a finding cites. Throws ApiError 404 for an unknown ID. */
export async function getGuidelinePassage(passageId: string): Promise<GuidelinePassage> {
  if (USE_MOCKS) return getGuidelinePassageMock(passageId);
  return toGuidelinePassage(await request<RealPassage>(`/guidelines/passages/${encodeURIComponent(passageId)}`));
}

/**
 * POST /guidelines/ask: a question, the source set and, optionally, a case whose facts are attached.
 * Answers with the cited answer at once (no job). The endpoint is Arindam's and is not on `main` yet,
 * so the answer's shape is our proposal (see guidelines-types.ts), and a real backend without it
 * answers 404 or 405, which is turned into a plain message.
 */
export async function askGuideline(question: string, sourceSet: SourceSet, caseId: string | null): Promise<GuidelineAnswer> {
  const clean = { question: question.trim(), source_set: sourceSet, case_id: caseId };
  if (USE_MOCKS) return askGuidelineMock(clean);
  try {
    return await request<GuidelineAnswer>("/guidelines/ask", { method: "POST", body: JSON.stringify(clean) });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
      throw new ApiError(e.status, "The guideline assistant is not available on this backend yet: the question endpoint is still to come.");
    }
    throw e;
  }
}

/**
 * POST /guidelines/answers/{id}/feedback: helpful, not helpful or wrongly cited, with an optional note.
 * Proposal, not on `main`. Throws ApiError 404 for an unknown answer.
 */
export async function sendGuidelineFeedback(answerId: string, rating: FeedbackRating, note?: string): Promise<void> {
  const body = { rating, ...(note?.trim() ? { note: note.trim() } : {}) };
  if (USE_MOCKS) {
    sendGuidelineFeedbackMock(answerId, body);
    return;
  }
  await request<unknown>(`/guidelines/answers/${encodeURIComponent(answerId)}/feedback`, { method: "POST", body: JSON.stringify(body) });
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
