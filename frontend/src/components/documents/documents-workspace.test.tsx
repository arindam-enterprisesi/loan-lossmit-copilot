import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore } from "@/mocks/store";
import { DocumentsWorkspace } from "./documents-workspace";

beforeEach(() => resetMockStore());

describe("DocumentsWorkspace with the completeness panel", () => {
  it("shows the documents and, below them, the completeness check for the same case", async () => {
    render(
      <DocumentsWorkspace
        cases={mockCases.filter((c) => c.id === DANIEL_CASE_ID)}
        pillarSlug="underwriting"
        section="document-intelligence"
      />,
    );
    expect(await screen.findByRole("heading", { name: "Documents for Daniel Reyes — purchase" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Completeness for Daniel Reyes — purchase" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    expect(await screen.findByText("Incomplete")).toBeInTheDocument();
    expect(screen.getByText(/pillar1-wage-earner@1/)).toBeInTheDocument();
  });

  it("runs the loss mitigation checklist on the Document intake screen", async () => {
    render(
      <DocumentsWorkspace
        cases={mockCases.filter((c) => c.id === ANGELA_CASE_ID)}
        pillarSlug="loss-mitigation"
        section="document-intake"
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    expect(await screen.findByText(/pillar2-loss-mitigation@1/)).toBeInTheDocument();
    expect(screen.getByText("August 2026 bank statement")).toBeInTheDocument();
  });

  it("starts the check afresh when another case is picked", async () => {
    render(<DocumentsWorkspace cases={mockCases} pillarSlug="underwriting" section="document-intelligence" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    await screen.findByText("Incomplete");

    fireEvent.change(screen.getByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    expect(await screen.findByRole("heading", { name: "Completeness for Angela Whitfield — hardship" })).toBeInTheDocument();
    expect(await screen.findByText(/No completeness result yet/)).toBeInTheDocument();
  });
});
