import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/shared/toast";
import { ApiError } from "@/lib/api-error";
import { sortFlaggedFirst } from "@/lib/documents";
import { DANIEL_CASE_ID } from "@/mocks/data";
import { PAYSTUB_DOC_ID } from "@/mocks/extraction";
import { getExtractionMock, listDocumentsMock, resetMockStore } from "@/mocks/store";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getExtraction: vi.fn(),
  listDocuments: vi.fn(),
  reviewField: vi.fn(),
  setDocumentType: vi.fn(),
  getJob: vi.fn(),
  getPageImage: vi.fn().mockResolvedValue(undefined),
}));
import { getExtraction, listDocuments, reviewField } from "@/lib/api";
import { ReviewWorkspace } from "./review-workspace";

const extraction = vi.mocked(getExtraction);
const documents = vi.mocked(listDocuments);
const review = vi.mocked(reviewField);

beforeEach(() => {
  resetMockStore();
  extraction.mockReset();
  documents.mockReset();
  review.mockReset();
  documents.mockImplementation(async () => listDocumentsMock(DANIEL_CASE_ID));
});

const renderScreen = () =>
  render(
    <ToastProvider>
      <ReviewWorkspace caseId={DANIEL_CASE_ID} documentId={PAYSTUB_DOC_ID} backHref="/underwriting/document-intelligence" />
    </ToastProvider>,
  );

describe("ReviewWorkspace loading and failing to load", () => {
  it("shows a skeleton shaped like the screen while it loads", () => {
    extraction.mockReturnValue(new Promise(() => {})); // never answers
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the document" })).toBeInTheDocument();
  });

  it("shows the error with Try again when it cannot load, and Try again loads it", async () => {
    extraction.mockRejectedValueOnce(new ApiError(500, "Server error"));
    extraction.mockImplementation(async () => getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    expect(screen.getByRole("link", { name: /Back to documents/ })).toBeInTheDocument(); // can still leave

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Extracted fields")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("'nothing to review yet' (404) is an empty state with Check again, not an error", async () => {
    extraction.mockRejectedValue(new ApiError(404, "no extraction"));
    renderScreen();
    expect(await screen.findByText("Nothing to review yet")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    extraction.mockImplementation(async () => getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID));
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Extracted fields")).toBeInTheDocument();
  });
});

describe("ReviewWorkspace when saving a review fails", () => {
  const firstField = () => sortFlaggedFirst(getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID).fields)[0];

  it("shows the message with Try again, and the field stays as it was", async () => {
    extraction.mockImplementation(async () => getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID));
    review.mockRejectedValue(new ApiError(503, "Could not save"));
    renderScreen();
    await screen.findByText("Extracted fields");
    fireEvent.click(screen.getByRole("button", { name: "Confirm value" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm value" })).toBeInTheDocument(); // the form is still there to retry by hand
  });

  it("Try again sends the same review once more", async () => {
    extraction.mockImplementation(async () => getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID));
    const field = firstField();
    review.mockRejectedValueOnce(new ApiError(503, "Could not save"));
    review.mockResolvedValue({ ...field, review_status: "confirmed", version: (field.version ?? 1) + 1 });
    renderScreen();
    await screen.findByText("Extracted fields");
    fireEvent.click(screen.getByRole("button", { name: "Confirm value" }));
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    await waitFor(() => expect(review).toHaveBeenCalledTimes(2));
    expect(review.mock.calls[1]).toEqual(review.mock.calls[0]); // the same field, the same review
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("a conflict is still the Reload message on the screen, not a toast", async () => {
    extraction.mockImplementation(async () => getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID));
    review.mockRejectedValue(new ApiError(409, "version conflict"));
    renderScreen();
    await screen.findByText("Extracted fields");
    fireEvent.click(screen.getByRole("button", { name: "Confirm value" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This value changed since you opened it");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });
});
