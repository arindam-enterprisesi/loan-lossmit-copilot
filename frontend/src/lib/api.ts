// Thin API layer. Screens call these functions and never fetch directly, so the swap from mocks
// to the real FastAPI backend (contracts/openapi.yaml) is a flag, not a rewrite.
import { mockCases } from "@/mocks/data";
import {
  getExtractionMock,
  getJobMock,
  listDocumentsMock,
  pageImageUrlMock,
  reviewFieldMock,
  setDocumentTypeMock,
  uploadMock,
} from "@/mocks/store";
import { ApiError } from "./api-error";
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
  if (USE_MOCKS) return setDocumentTypeMock(caseId, documentId, docType);
  const res = await rawRequest(`/cases/${caseId}/documents/${documentId}/type`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_type: docType, ...(reason ? { reason } : {}) }),
  });
  const data = (await res.json()) as DocumentSummary | { document: DocumentSummary; job: Job };
  return "document" in data ? data : { document: data };
}

/**
 * Page image link for the evidence panel. The contract has no page-image endpoint yet (TODO D3+),
 * so only the mock pay stub has one. Returns undefined and the panel shows a blank page.
 */
export function getPageImageUrl(documentId: string, page: number): string | undefined {
  return USE_MOCKS ? pageImageUrlMock(documentId, page) : undefined;
}
