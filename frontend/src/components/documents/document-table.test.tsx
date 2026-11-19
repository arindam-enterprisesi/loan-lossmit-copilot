import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockDocuments } from "@/mocks/data";
import { DocumentTable } from "./document-table";

const danielDocs = mockDocuments.filter((d) => d.case_id === DANIEL_CASE_ID);

const setup = (docs = danielDocs, onSetType = vi.fn().mockResolvedValue(undefined)) => {
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

  it("offers a Choose type button, and only on documents that could not be classified", () => {
    setup();
    expect(screen.getAllByRole("button", { name: "Choose type" })).toHaveLength(1);
    const row = screen.getByText("scan_0042.jpg").closest("tr")!;
    expect(row).toHaveTextContent("Choose type");
  });

  it("Choose type opens the dialog for that document, and nothing is sent until Confirm", () => {
    const onSetType = setup();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Choose type" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveTextContent("scan_0042.jpg");
    expect(onSetType).not.toHaveBeenCalled();
  });

  it("sends the document, the chosen type and the reason, then closes the dialog", async () => {
    const onSetType = setup();
    fireEvent.click(screen.getByRole("button", { name: "Choose type" }));
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: "w2" } });
    fireEvent.change(screen.getByLabelText("Reason (optional)"), { target: { value: "Title cut off" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));

    const id = danielDocs.find((d) => d.file_name === "scan_0042.jpg")!.id;
    await waitFor(() => expect(onSetType).toHaveBeenCalledWith(id, "w2", "Title cut off"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog open and shows the message when the type could not be saved", async () => {
    setup(danielDocs, vi.fn().mockRejectedValue(new Error("Reason too long")));
    fireEvent.click(screen.getByRole("button", { name: "Choose type" }));
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: "w2" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reason too long");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
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
