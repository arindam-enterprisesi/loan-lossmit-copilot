import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-error";
import { DANIEL_CASE_ID } from "./data";
import { PAYSTUB_DOC_ID } from "./extraction";
import {
  getExtractionMock,
  getJobMock,
  guessType,
  JOB_QUEUE_MS,
  JOB_RUN_MS,
  listDocumentsMock,
  pageImageUrlMock,
  resetMockStore,
  reviewFieldMock,
  setDocumentTypeMock,
  typeChangesMock,
  uploadMock,
} from "./store";

beforeEach(() => resetMockStore());

const netPay = () =>
  getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID).fields.find((f) => f.name === "net_pay_current")!;

const statusOf = (fn: () => unknown): number | undefined => {
  try {
    fn();
  } catch (e) {
    return (e as ApiError).status;
  }
  return undefined;
};

describe("reviewing a field", () => {
  it("lists the flagged net pay first with its evidence box", () => {
    const first = getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID).fields[0];
    expect(first.name).toBe("net_pay_current");
    expect(first.flags[0].code).toBe("DI-CHK-02");
    expect(first.evidence?.bbox).toEqual({ x0: 0.242, y0: 0.4, x1: 0.311, y1: 0.41 });
  });

  it("a correction keeps the original value and records who, when and why", () => {
    const f = netPay();
    const updated = reviewFieldMock(
      DANIEL_CASE_ID,
      PAYSTUB_DOC_ID,
      "net_pay_current",
      { action: "correct", value: "2033.61", reason: "OCR misread", expected_version: f.version! },
      Date.parse("2026-11-17T10:00:00Z"),
    );
    expect(updated.value).toBe("2033.61");
    expect(updated.original_value).toBe("2083.61");
    expect(updated.review_status).toBe("corrected");
    expect(updated.review_reason).toBe("OCR misread");
    expect(updated.reviewed_by).toBeTruthy();
    expect(updated.reviewed_at).toBe("2026-11-17T10:00:00.000Z");
    expect(updated.version).toBe(f.version! + 1);
    expect(updated.flags).toEqual([]);
  });

  it("clears the document flag and marks it reviewed once the flagged field is corrected", () => {
    const f = netPay();
    reviewFieldMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "net_pay_current", {
      action: "correct",
      value: "2033.61",
      reason: "OCR misread",
      expected_version: f.version!,
    });
    const doc = listDocumentsMock(DANIEL_CASE_ID).find((d) => d.id === PAYSTUB_DOC_ID)!;
    expect(doc.flags).toEqual([]);
    expect(doc.status).toBe("reviewed");
  });

  it("refuses a stale version with 409 and changes nothing", () => {
    const f = netPay();
    const status = statusOf(() =>
      reviewFieldMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "net_pay_current", {
        action: "confirm",
        expected_version: f.version! + 5,
      }),
    );
    expect(status).toBe(409);
    expect(netPay().review_status).toBe("unreviewed");
  });

  it("refuses a correction or rejection without a reason with 422", () => {
    const f = netPay();
    expect(
      statusOf(() =>
        reviewFieldMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "net_pay_current", {
          action: "correct",
          value: "1",
          expected_version: f.version!,
        }),
      ),
    ).toBe(422);
    expect(
      statusOf(() =>
        reviewFieldMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "net_pay_current", {
          action: "reject",
          expected_version: f.version!,
        }),
      ),
    ).toBe(422);
  });

  it("returns copies, so callers cannot change the stored data by accident", () => {
    const f = netPay();
    f.value = "tampered";
    expect(netPay().value).toBe("2083.61");
  });
});

describe("uploading and processing", () => {
  it("creates processing documents and a queued job", () => {
    const { documents, job } = uploadMock(DANIEL_CASE_ID, ["paystub_oct.pdf", "mystery.jpg"], "auto", 0);
    expect(documents).toHaveLength(2);
    expect(documents.every((d) => d.status === "processing")).toBe(true);
    expect(job.status).toBe("queued");
    expect(job.progress).toBe(0);
    expect(listDocumentsMock(DANIEL_CASE_ID).map((d) => d.file_name)).toContain("mystery.jpg");
  });

  it("moves queued, running, then succeeded as time passes", () => {
    const { job } = uploadMock(DANIEL_CASE_ID, ["a.pdf"], "auto", 0);
    expect(getJobMock(job.id, JOB_QUEUE_MS - 1).status).toBe("queued");
    const running = getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS / 2);
    expect(running.status).toBe("running");
    expect(running.progress).toBeGreaterThan(0);
    expect(running.progress).toBeLessThan(1);
    expect(running.stage).toBeTruthy();
    const done = getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    expect(done.status).toBe("succeeded");
    expect(done.progress).toBe(1);
  });

  it("a finished job settles each document: typed ones wait for review, unknown ones need a type", () => {
    const { documents, job } = uploadMock(
      DANIEL_CASE_ID,
      ["bank_statement_oct.pdf", "scan_9.jpg"],
      "auto",
      0,
    );
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    const after = listDocumentsMock(DANIEL_CASE_ID);
    const bank = after.find((d) => d.id === documents[0].id)!;
    const unknown = after.find((d) => d.id === documents[1].id)!;
    expect(bank.status).toBe("needs_review");
    expect(bank.doc_type).toBe("bank_statement");
    expect(unknown.status).toBe("type_needed");
    expect(unknown.flags[0].code).toBe("DI-W501");
  });

  it("an uploaded pay stub gets the demo reading: net pay flagged, and its own page picture", () => {
    const { documents, job } = uploadMock(DANIEL_CASE_ID, ["reyes_paystub_nov.pdf"], "auto", 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    const id = documents[0].id;

    const extraction = getExtractionMock(DANIEL_CASE_ID, id);
    expect(extraction.document_id).toBe(id);
    expect(extraction.fields[0].name).toBe("net_pay_current");
    expect(extraction.fields[0].flags[0].code).toBe("DI-CHK-02");
    expect(extraction.fields.every((f) => f.evidence?.document_id === id)).toBe(true);

    const doc = listDocumentsMock(DANIEL_CASE_ID).find((d) => d.id === id)!;
    expect(doc.status).toBe("needs_review");
    expect(doc.flags[0].code).toBe("DI-CHK-02");
    expect(pageImageUrlMock(id, 1)).toBe("/mock/paystub-p1.svg");
    expect(pageImageUrlMock(id, 2)).toBeUndefined();
  });

  it("an uploaded copy of the pay stub does not share its fields with the original", () => {
    const { documents, job } = uploadMock(DANIEL_CASE_ID, ["paystub_copy.pdf"], "auto", 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
    const copy = getExtractionMock(DANIEL_CASE_ID, documents[0].id).fields[0];
    reviewFieldMock(DANIEL_CASE_ID, documents[0].id, copy.name, {
      action: "confirm",
      expected_version: copy.version!,
    });
    expect(netPay().review_status).toBe("unreviewed"); // the original pay stub is untouched
  });

  it("an unknown job is a 404", () => {
    expect(statusOf(() => getJobMock("nope"))).toBe(404);
  });

  it("guesses a type from the file name", () => {
    expect(guessType("Reyes_PayStub_Oct.pdf")).toBe("pay_stub");
    expect(guessType("mortgage_statement.pdf")).toBe("mortgage_statement");
    expect(guessType("scan_0042.jpg")).toBeNull();
  });
});

describe("choosing a type", () => {
  const needsType = () => listDocumentsMock(DANIEL_CASE_ID).find((d) => d.status === "type_needed")!;

  it("re-queues extraction for a document that needed a type", () => {
    const doc = needsType();
    const result = setDocumentTypeMock(DANIEL_CASE_ID, doc.id, "w2", undefined, 0);
    expect(result.document.doc_type).toBe("w2");
    expect(result.document.status).toBe("processing");
    expect(result.job?.status).toBe("queued");
    getJobMock(result.job!.id, JOB_QUEUE_MS + JOB_RUN_MS);
    const after = listDocumentsMock(DANIEL_CASE_ID).find((d) => d.id === doc.id)!;
    expect(after.status).toBe("needs_review");
    expect(after.flags).toEqual([]);
  });

  it("confirming the same type on a typed document queues nothing", () => {
    const result = setDocumentTypeMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, "pay_stub");
    expect(result.job).toBeUndefined();
    expect(typeChangesMock()).toEqual([]); // nothing changed, so nothing is recorded
  });

  it("records the change with the reason, who it was from and to, and when", () => {
    const doc = needsType();
    setDocumentTypeMock(DANIEL_CASE_ID, doc.id, "w2", "Scanned W-2, no title on page", Date.parse("2026-11-18T09:00:00Z"));
    expect(typeChangesMock()).toEqual([
      {
        documentId: doc.id,
        from: null,
        to: "w2",
        reason: "Scanned W-2, no title on page",
        at: "2026-11-18T09:00:00.000Z",
      },
    ]);
  });

  it("records a change with no reason as null, since the reason is optional", () => {
    setDocumentTypeMock(DANIEL_CASE_ID, needsType().id, "w2");
    expect(typeChangesMock()[0].reason).toBeNull();
  });

  it("refuses a reason longer than 500 characters with 422 and changes nothing", () => {
    const doc = needsType();
    const status = statusOf(() => setDocumentTypeMock(DANIEL_CASE_ID, doc.id, "w2", "x".repeat(501)));
    expect(status).toBe(422);
    expect(typeChangesMock()).toEqual([]);
    expect(listDocumentsMock(DANIEL_CASE_ID).find((d) => d.id === doc.id)!.status).toBe("type_needed");
  });

  it("accepts a reason of exactly 500 characters", () => {
    expect(() => setDocumentTypeMock(DANIEL_CASE_ID, needsType().id, "w2", "x".repeat(500))).not.toThrow();
  });
});

describe("the needs-review filter", () => {
  it("returns only documents that have flags", () => {
    const flagged = listDocumentsMock(DANIEL_CASE_ID, true);
    expect(flagged.length).toBeGreaterThan(0);
    expect(flagged.every((d) => d.flags.length > 0)).toBe(true);
  });
});
