import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockDocuments } from "@/mocks/data";
import { DocumentTable } from "./document-table";

const danielDocs = mockDocuments.filter((d) => d.case_id === DANIEL_CASE_ID);

const setup = (docs = danielDocs, onSetType = vi.fn()) => {
  render(
    <DocumentTable
      documents={docs}
      pillarSlug="underwriting"
      section="document-intelligence"
      onSetType={onSetType}
    />,
  );
  return onSetType;
};

describe("DocumentTable", () => {
  it("links a reviewable document to its review screen", () => {
    setup();
    const payStub = danielDocs.find((d) => d.doc_type === "pay_stub")!;
    const link = screen.getByRole("link", { name: "Review" });
    expect(link).toHaveAttribute(
      "href",
      `/underwriting/document-intelligence/${DANIEL_CASE_ID}/${payStub.id}`,
    );
  });

  it("shows the flag code beside a flagged document", () => {
    setup();
    expect(screen.getByText("DI-CHK-02")).toBeInTheDocument();
  });

  it("asks for a type when the document could not be classified", async () => {
    const onSetType = setup();
    const row = screen.getByText("scan_0042.jpg").closest("tr")!;
    const button = row.querySelector("button")!;
    expect(button).toBeDisabled(); // nothing chosen yet
    fireEvent.change(row.querySelector("select")!, { target: { value: "w2" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(onSetType).toHaveBeenCalledTimes(1));
    expect(onSetType).toHaveBeenCalledWith(danielDocs.find((d) => d.file_name === "scan_0042.jpg")!.id, "w2");
  });

  it("shows processing documents without a review link", () => {
    setup(mockDocuments.filter((d) => d.case_id === ANGELA_CASE_ID));
    const row = screen.getByText("whitfield_paystub_2026-10.pdf").closest("tr")!;
    expect(row).toHaveTextContent("Processing…");
    expect(row.querySelector("a")).toBeNull();
  });

  it("says so when there is nothing to list", () => {
    setup([]);
    expect(screen.getByText("No documents to show.")).toBeInTheDocument();
  });
});
