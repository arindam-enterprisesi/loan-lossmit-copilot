// In-memory stand-in for the backend document endpoints while NEXT_PUBLIC_USE_MOCKS=true.
// It mirrors the contract rules the screens depend on (409 on a stale version, 422 on a missing
// reason, corrections keep original_value) so the UI is built against real behaviour. A page reload
// resets it. It is replaced by the real API, never extended with business logic.
import { ApiError } from "@/lib/api-error";
import type { ChecklistResult } from "@/lib/completeness";
import { DOCUMENT_TYPES, TYPE_REASON_MAX } from "@/lib/documents";
import type {
  DocumentSummary,
  DocumentType,
  Extraction,
  Field,
  FieldReview,
  Flag,
  Job,
} from "@/lib/types";
import type {
  BudgetAdjustmentRequest,
  HardshipAssessment,
  ProfileConfirmation,
} from "@/lib/hardship-types";
import type { IncomeAnalysis, IncomeDecision } from "@/lib/income-types";
import { applyOverride, buildCompleteness } from "./completeness";
import { mockDocuments } from "./data";
import { applyBudgetAdjustment, applyConfirmation, buildAngelaHardship, hasHardshipSeed } from "./hardship";
import { MOCK_PAGE_IMAGES, PAYSTUB_DOC_ID, seedExtractions } from "./extraction";
import { applyIncomeDecision, buildDanielIncome, hasIncomeSeed } from "./income";

/** Job timing: waits in the queue, then runs. Exported so tests can step through it. */
export const JOB_QUEUE_MS = 600;
export const JOB_RUN_MS = 3000;

type JobKind = "document_processing" | "income_analysis" | "hardship_assessment";

interface MockJob {
  id: string;
  kind: JobKind;
  createdAtMs: number;
  /** Documents being read (document jobs). Empty for an income or hardship run. */
  documentIds: string[];
  /** The case an income or hardship run belongs to. */
  caseId?: string;
  finalized: boolean;
}

/** One recorded change of document type. The real backend keeps this in its audit store. */
export interface TypeChange {
  documentId: string;
  from: DocumentType | null;
  to: DocumentType;
  reason: string | null;
  at: string;
}

interface StoreState {
  documents: DocumentSummary[];
  extractions: Map<string, Extraction>;
  jobs: Map<string, MockJob>;
  typeChanges: TypeChange[];
  /** Latest income analysis per case, set when a run's job finishes. */
  incomes: Map<string, IncomeAnalysis>;
  /** Latest completeness result per case, set when the checklist is run. */
  completeness: Map<string, ChecklistResult>;
  /** Latest hardship assessment per case, set when a run's job finishes. */
  hardship: Map<string, HardshipAssessment>;
  counter: number;
}

function createState(): StoreState {
  return {
    documents: structuredClone(mockDocuments),
    extractions: new Map(structuredClone(seedExtractions).map((e) => [e.document_id, e])),
    jobs: new Map(),
    typeChanges: [],
    incomes: new Map(),
    completeness: new Map(),
    hardship: new Map(),
    counter: 0,
  };
}

let state = createState();

/** Back to the seed data. Used by tests. */
export function resetMockStore(): void {
  state = createState();
}

const newId = (prefix: string): string =>
  `${prefix}0000000-0000-4000-8000-${String(++state.counter).padStart(12, "0")}`;

const find = (caseId: string, documentId: string): DocumentSummary => {
  const doc = state.documents.find((d) => d.id === documentId && d.case_id === caseId);
  if (!doc) throw new ApiError(404, "Document not found");
  return doc;
};

const iso = (ms: number): string => new Date(ms).toISOString();

export function listDocumentsMock(caseId: string, needsReview?: boolean): DocumentSummary[] {
  return structuredClone(
    state.documents.filter((d) => d.case_id === caseId && (!needsReview || d.flags.length > 0)),
  );
}

/** Rough file-name guess so an uploaded "paystub.pdf" lands as a pay stub. The real classifier is the backend's. */
export function guessType(fileName: string): DocumentType | null {
  const n = fileName.toLowerCase();
  if (/mortgage/.test(n)) return "mortgage_statement";
  if (/pay.?stub|payslip/.test(n)) return "pay_stub";
  if (/bank|statement/.test(n)) return "bank_statement";
  if (/w-?2/.test(n)) return "w2";
  if (/1040|tax/.test(n)) return "tax_return_1040";
  if (/credit/.test(n)) return "credit_report";
  if (/hardship/.test(n)) return "hardship_letter";
  if (/benefit/.test(n)) return "benefits_letter";
  if (/bill|utility/.test(n)) return "expense_bill";
  return null;
}

const typeNeededFlag: Flag = {
  code: "DI-W501",
  severity: "warning",
  message: "The type could not be told with certainty. Choose a type to continue.",
};

function basicExtraction(doc: DocumentSummary): Extraction {
  const f = (name: string, value: string): Field => ({
    name,
    value,
    original_value: value,
    certainty: "medium",
    flags: [],
    evidence: { document_id: doc.id, page: 1, line_ids: [] },
    review_status: "unreviewed",
    reviewed_by: null,
    reviewed_at: null,
    review_reason: null,
    version: 1,
  });
  const fields: Field[] = [];
  if (doc.owner) fields.push(f("owner_name", doc.owner));
  if (doc.period_start) fields.push(f("period_start", doc.period_start));
  if (doc.period_end) fields.push(f("period_end", doc.period_end));
  return {
    document_id: doc.id,
    doc_type: doc.doc_type ?? "unrecognized",
    fields,
    flags: [],
    summary: doc.summary ?? null,
    prompt_id: "extract@1",
    provider: "mock",
    model: "mock",
  };
}

/**
 * What a finished job leaves behind for one document. An uploaded pay stub gets a copy of the demo
 * story's pay stub reading (net pay flagged), so the whole upload, review and correct flow can be
 * tried. Anything else gets a basic reading. The real reading is the backend's.
 */
function extractionFor(doc: DocumentSummary): Extraction {
  const seed = doc.doc_type === "pay_stub" ? seedExtractions.find((e) => e.document_id === PAYSTUB_DOC_ID) : undefined;
  if (!seed) return basicExtraction(doc);
  const copy = structuredClone(seed);
  copy.document_id = doc.id;
  for (const f of copy.fields) {
    if (f.evidence) f.evidence.document_id = doc.id;
    for (const flag of f.flags) if (flag.evidence) flag.evidence.document_id = doc.id;
  }
  return copy;
}

/** Open field flags plus the document-level flags decide what the document list shows. */
function refreshDocument(doc: DocumentSummary, extraction: Extraction): void {
  const open = extraction.fields.filter((f) => f.flags.length > 0 && f.review_status === "unreviewed");
  doc.flags = [...extraction.flags, ...open.flatMap((f) => f.flags)];
  doc.status = doc.flags.length > 0 ? "needs_review" : "reviewed";
}

/** What the worker does when a job finishes: settle each document in the job, or store the income run. */
function finalizeJob(job: MockJob): void {
  if (job.kind === "income_analysis" && job.caseId) {
    state.incomes.set(job.caseId, buildDanielIncome(iso(job.createdAtMs + JOB_QUEUE_MS + JOB_RUN_MS)));
    job.finalized = true;
    return;
  }
  if (job.kind === "hardship_assessment" && job.caseId) {
    state.hardship.set(job.caseId, buildAngelaHardship(iso(job.createdAtMs + JOB_QUEUE_MS + JOB_RUN_MS)));
    job.finalized = true;
    return;
  }
  for (const id of job.documentIds) {
    const doc = state.documents.find((d) => d.id === id);
    if (!doc) continue;
    if (!doc.doc_type) {
      doc.status = "type_needed";
      doc.type_certainty = "low";
      doc.flags = [typeNeededFlag];
      continue;
    }
    doc.type_certainty = doc.declared_type ? "high" : "medium";
    doc.page_count = doc.page_count ?? 1;
    const extraction = extractionFor(doc);
    state.extractions.set(doc.id, extraction);
    doc.status = "needs_review"; // fresh extraction: waits for a person to look at it
    doc.flags = [...extraction.flags, ...extraction.fields.flatMap((f) => f.flags)];
  }
  job.finalized = true;
}

function createJob(documentIds: string[], now: number, kind: JobKind = "document_processing", caseId?: string): Job {
  const job: MockJob = { id: newId("b"), kind, createdAtMs: now, documentIds, caseId, finalized: false };
  state.jobs.set(job.id, job);
  return jobView(job, now);
}

const STAGES: Record<JobKind, readonly string[]> = {
  document_processing: ["ocr", "classify", "extract", "checks"],
  income_analysis: ["gather", "calculate", "explain", "checks"],
  hardship_assessment: ["read", "compare", "budget", "checks"],
};

function jobView(job: MockJob, now: number): Job {
  const elapsed = now - job.createdAtMs;
  let status: Job["status"] = "queued";
  let progress = 0;
  let stage: string | null = null;
  if (elapsed >= JOB_QUEUE_MS + JOB_RUN_MS) {
    status = "succeeded";
    progress = 1;
  } else if (elapsed >= JOB_QUEUE_MS) {
    status = "running";
    progress = Math.round(((elapsed - JOB_QUEUE_MS) / JOB_RUN_MS) * 100) / 100;
    const stages = STAGES[job.kind];
    stage = stages[Math.min(stages.length - 1, Math.floor(progress * stages.length))];
  }
  return {
    id: job.id,
    kind: job.kind,
    status,
    progress,
    stage,
    error: null,
    created_at: iso(job.createdAtMs),
    updated_at: iso(Math.min(now, job.createdAtMs + JOB_QUEUE_MS + JOB_RUN_MS)),
  };
}

export function getJobMock(jobId: string, now: number = Date.now()): Job {
  const job = state.jobs.get(jobId);
  if (!job) throw new ApiError(404, "Job not found");
  const view = jobView(job, now);
  if (view.status === "succeeded" && !job.finalized) finalizeJob(job);
  return view;
}

export function uploadMock(
  caseId: string,
  fileNames: string[],
  declaredType: DocumentType | "auto",
  now: number = Date.now(),
): { documents: DocumentSummary[]; job: Job } {
  const declared = declaredType === "auto" ? null : declaredType;
  const created: DocumentSummary[] = fileNames.map((file_name) => ({
    id: newId("e"),
    case_id: caseId,
    file_name,
    declared_type: declared,
    doc_type: declared ?? guessType(file_name),
    type_certainty: null,
    status: "processing",
    page_count: null,
    owner: null,
    summary: null,
    flags: [],
    uploaded_at: iso(now),
  }));
  state.documents.push(...created);
  const job = createJob(
    created.map((d) => d.id),
    now,
  );
  return { documents: structuredClone(created), job };
}

export function setDocumentTypeMock(
  caseId: string,
  documentId: string,
  docType: DocumentType,
  reason?: string,
  now: number = Date.now(),
): { document: DocumentSummary; job?: Job } {
  const doc = find(caseId, documentId);
  if (!DOCUMENT_TYPES.includes(docType)) throw new ApiError(422, "Unknown document type");
  if (reason && reason.length > TYPE_REASON_MAX) {
    throw new ApiError(422, `The reason can be at most ${TYPE_REASON_MAX} characters`);
  }
  if (doc.doc_type === docType && doc.status !== "type_needed") {
    return { document: structuredClone(doc) };
  }
  state.typeChanges.push({
    documentId: doc.id,
    from: doc.doc_type ?? null,
    to: docType,
    reason: reason ?? null,
    at: iso(now),
  });
  doc.doc_type = docType;
  doc.type_certainty = "high";
  doc.status = "processing";
  doc.flags = [];
  state.extractions.delete(doc.id);
  const job = createJob([doc.id], now);
  return { document: structuredClone(doc), job };
}

/** The recorded type changes, oldest first. Used by tests; the screens never read it. */
export function typeChangesMock(): TypeChange[] {
  return structuredClone(state.typeChanges);
}

export function getExtractionMock(caseId: string, documentId: string): Extraction {
  const doc = find(caseId, documentId);
  const existing = state.extractions.get(doc.id);
  if (existing) return structuredClone(existing);
  if (doc.status === "reviewed") {
    const basic = basicExtraction(doc);
    state.extractions.set(doc.id, basic);
    return structuredClone(basic);
  }
  throw new ApiError(404, "No extraction yet for this document");
}

export function reviewFieldMock(
  caseId: string,
  documentId: string,
  fieldName: string,
  review: FieldReview,
  now: number = Date.now(),
): Field {
  const doc = find(caseId, documentId);
  const extraction = state.extractions.get(doc.id);
  const target = extraction?.fields.find((f) => f.name === fieldName);
  if (!extraction || !target) throw new ApiError(404, "Field not found");

  if (review.expected_version !== target.version) {
    throw new ApiError(409, "This value changed since it was loaded");
  }
  if (review.action === "correct" && !review.value?.trim()) throw new ApiError(422, "A corrected value is required");
  if (review.action !== "confirm" && !review.reason?.trim()) throw new ApiError(422, "A reason is required");

  if (review.action === "correct") {
    target.value = review.value!.trim(); // original_value is never touched
    target.flags = []; // stands in for the backend re-running its checks, with no AI call
  }
  target.review_status =
    review.action === "confirm" ? "confirmed" : review.action === "correct" ? "corrected" : "rejected";
  target.review_reason = review.reason?.trim() ?? null;
  target.reviewed_by = "demo.reviewer";
  target.reviewed_at = iso(now);
  target.version += 1;

  refreshDocument(doc, extraction);
  return structuredClone(target);
}

/** POST .../income/analysis: queues a run. Only a case with income documents can be run (422 otherwise). */
export function runIncomeMock(caseId: string, now: number = Date.now()): Job {
  if (!hasIncomeSeed(caseId)) throw new ApiError(422, "This case has no income documents to analyse");
  return createJob([], now, "income_analysis", caseId);
}

/** GET .../income/analysis/latest: 404 until a run has finished. */
export function getLatestIncomeMock(caseId: string): IncomeAnalysis {
  const latest = state.incomes.get(caseId);
  if (!latest) throw new ApiError(404, "No income analysis yet. Run it first.");
  return structuredClone(latest);
}

/**
 * PATCH .../income/analysis/components/{id}: include or exclude one component, reason required (422).
 * The latest analysis is replaced by the recalculated one and returned, so the screen updates at once.
 */
export function setIncomeComponentMock(
  caseId: string,
  componentId: string,
  decision: IncomeDecision,
  now: number = Date.now(),
): IncomeAnalysis {
  const latest = state.incomes.get(caseId);
  if (!latest) throw new ApiError(404, "No income analysis yet. Run it first.");
  const updated = applyIncomeDecision(latest, componentId, decision, "demo.reviewer", iso(now));
  state.incomes.set(caseId, updated);
  return structuredClone(updated);
}

/** POST .../hardship-assessment: queues a run. Only a case with a hardship letter can be run (422 otherwise). */
export function runHardshipMock(caseId: string, now: number = Date.now()): Job {
  if (!hasHardshipSeed(caseId)) throw new ApiError(422, "This case has no hardship letter to read");
  return createJob([], now, "hardship_assessment", caseId);
}

/** GET .../hardship-assessment/latest: 404 until a run has finished. */
export function getLatestHardshipMock(caseId: string): HardshipAssessment {
  const latest = state.hardship.get(caseId);
  if (!latest) throw new ApiError(404, "No hardship assessment yet. Run it first.");
  return structuredClone(latest);
}

/** PUT .../confirmations: confirm or correct one profile item. Returns the whole updated assessment. */
export function confirmProfileItemMock(
  caseId: string,
  confirmation: ProfileConfirmation,
  now: number = Date.now(),
): HardshipAssessment {
  const latest = state.hardship.get(caseId);
  if (!latest) throw new ApiError(404, "No hardship assessment yet. Run it first.");
  const updated = applyConfirmation(latest, confirmation, "demo.reviewer", iso(now));
  state.hardship.set(caseId, updated);
  return structuredClone(updated);
}

/** PATCH .../budget-items/{item}: adjust one expense, reason required (422). Returns the recalculated assessment. */
export function adjustBudgetItemMock(
  caseId: string,
  itemId: string,
  request: BudgetAdjustmentRequest,
  now: number = Date.now(),
): HardshipAssessment {
  const latest = state.hardship.get(caseId);
  if (!latest) throw new ApiError(404, "No hardship assessment yet. Run it first.");
  const updated = applyBudgetAdjustment(latest, itemId, request, "demo.reviewer", iso(now));
  state.hardship.set(caseId, updated);
  return structuredClone(updated);
}

/** POST .../completeness: runs the checklist at once (the contract answers 200 with the result, no job). */
export function runCompletenessMock(caseId: string, checklistId: string, now: number = Date.now()): ChecklistResult {
  const result = buildCompleteness(caseId, checklistId, iso(now), newId("c"));
  state.completeness.set(caseId, result);
  return structuredClone(result);
}

/** GET .../completeness/latest: 404 until the checklist has been run for the case. */
export function getLatestCompletenessMock(caseId: string): ChecklistResult {
  const latest = state.completeness.get(caseId);
  if (!latest) throw new ApiError(404, "No completeness result yet. Run the checklist first.");
  return structuredClone(latest);
}

/**
 * PATCH .../completeness/items/{item_id}: a person overrides an item, reason required (422).
 * The latest result is replaced by the recalculated one and returned.
 */
export function overrideCompletenessItemMock(
  caseId: string,
  itemId: string,
  reason: string,
  now: number = Date.now(),
): ChecklistResult {
  const latest = state.completeness.get(caseId);
  if (!latest) throw new ApiError(404, "No completeness result yet. Run the checklist first.");
  const updated = applyOverride(latest, itemId, reason, "demo.reviewer", iso(now));
  state.completeness.set(caseId, updated);
  return structuredClone(updated);
}

export function pageImageUrlMock(documentId: string, page: number): string | undefined {
  const listed = MOCK_PAGE_IMAGES[documentId]?.[page];
  if (listed) return listed;
  // An uploaded pay stub shows the mock pay stub page, matching the reading it was given.
  const doc = state.documents.find((d) => d.id === documentId);
  return doc?.doc_type === "pay_stub" && page === 1 ? MOCK_PAGE_IMAGES[PAYSTUB_DOC_ID][1] : undefined;
}
