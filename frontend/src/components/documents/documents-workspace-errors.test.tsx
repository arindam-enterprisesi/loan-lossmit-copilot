import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { DANIEL_CASE_ID, mockCases, mockDocuments } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  listDocuments: vi.fn(),
  setDocumentType: vi.fn(),
  uploadDocuments: vi.fn(),
  getJob: vi.fn(),
  getLatestCompleteness: vi.fn().mockRejectedValue(new Error("not run")),
  runCompleteness: vi.fn(),
  overrideCompletenessItem: vi.fn(),
}));
import { listDocuments } from "@/lib/api";
import { DocumentsWorkspace } from "./documents-workspace";

const list = vi.mocked(listDocuments);
const danielDocs = mockDocuments.filter((d) => d.case_id === DANIEL_CASE_ID);

beforeEach(() => {
  list.mockReset();
});

const renderScreen = () =>
  render(<DocumentsWorkspace cases={mockCases.slice(0, 1)} pillarSlug="underwriting" section="document-intelligence" />);

describe("DocumentsWorkspace loading, failing and empty", () => {
  it("shows a table-shaped skeleton while the list loads", () => {
    list.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading documents" })).toBeInTheDocument();
  });

  it("shows the error with Try again when the list cannot load, and no endless skeleton", async () => {
    list.mockRejectedValueOnce(new ApiError(500, "Server error"));
    list.mockResolvedValue(danielDocs);
    renderScreen();
    expect(await screen.findByText("Server error")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading documents" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(danielDocs[0].file_name)).toBeInTheDocument();
    expect(screen.queryByText("Server error")).not.toBeInTheDocument();
  });

  it("says what to do when the case has no documents yet", async () => {
    list.mockResolvedValue([]);
    renderScreen();
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
  });

  it("says nothing matches when the flagged-only filter hides everything", async () => {
    list.mockResolvedValueOnce(danielDocs).mockResolvedValue([]);
    renderScreen();
    await screen.findByText(danielDocs[0].file_name);
    fireEvent.click(screen.getByLabelText("Only documents with flagged fields"));
    expect(await screen.findByText("No documents with flagged fields")).toBeInTheDocument();
  });
});
