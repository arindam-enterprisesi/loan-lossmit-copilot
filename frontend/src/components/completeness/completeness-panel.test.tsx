import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockDocuments } from "@/mocks/data";
import { resetMockStore, runCompletenessMock } from "@/mocks/store";
import { CompletenessPanel } from "./completeness-panel";

beforeEach(() => resetMockStore());
afterEach(() => vi.unstubAllGlobals());

const renderDaniel = () =>
  render(
    <CompletenessPanel
      caseId={DANIEL_CASE_ID}
      caseTitle="Daniel Reyes — purchase"
      pillarSlug="underwriting"
      section="document-intelligence"
      documents={mockDocuments.filter((d) => d.case_id === DANIEL_CASE_ID)}
    />,
  );
const renderAngela = () =>
  render(
    <CompletenessPanel
      caseId={ANGELA_CASE_ID}
      caseTitle="Angela Whitfield — hardship"
      pillarSlug="loss-mitigation"
      section="document-intake"
    />,
  );

describe("CompletenessPanel before a run", () => {
  it("says nothing has been run and offers Run checklist", async () => {
    renderDaniel();
    expect(await screen.findByText(/No completeness result yet/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Completeness for Daniel Reyes — purchase" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run checklist" })).toBeEnabled();
    expect(screen.queryByText("Outstanding items")).not.toBeInTheDocument();
  });

  it("cannot run when its menu section has no checklist", async () => {
    render(<CompletenessPanel caseId={DANIEL_CASE_ID} pillarSlug="unknown" section="x" />);
    await screen.findByText(/No completeness result yet/);
    expect(screen.getByRole("button", { name: "Run checklist" })).toBeDisabled();
  });
});

describe("CompletenessPanel running the checklist for Daniel", () => {
  it("shows Incomplete, the checklist, every item with its status, and what is outstanding", async () => {
    renderDaniel();
    await screen.findByText(/No completeness result yet/);
    fireEvent.click(screen.getByRole("button", { name: "Run checklist" }));

    expect(await screen.findByText("Incomplete")).toBeInTheDocument();
    expect(screen.getByText("Illustrative checklist")).toBeInTheDocument();
    expect(screen.getByText(/pillar1-wage-earner@1 · run/)).toBeInTheDocument();
    expect(screen.getAllByText("Partially satisfied")).toHaveLength(4);
    expect(screen.getAllByText("Satisfied")).toHaveLength(1);
    expect(screen.getByText("14 of 30 days of pay stubs found")).toBeInTheDocument();

    const outstanding = within(screen.getByRole("heading", { name: "Outstanding items" }).parentElement!);
    expect(outstanding.getByText("W-2 for 2024")).toBeInTheDocument();
    expect(outstanding.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  });

  it("links each document used to its review screen, by file name", async () => {
    renderDaniel();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    const link = await screen.findByRole("link", { name: "reyes_paystub_2026-09.pdf" });
    expect(link).toHaveAttribute(
      "href",
      `/underwriting/document-intelligence/${DANIEL_CASE_ID}/d1000000-0000-4000-8000-000000000001`,
    );
  });

  it("copies the outstanding items", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderDaniel();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy outstanding items" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("Outstanding items for this case:");
    expect(text).toContain("- W-2 for 2024");
    expect(text).toContain("- Form 1040 for 2024");
    expect(await screen.findByText("Copied to the clipboard.")).toBeInTheDocument();
  });

  it("says so when the clipboard is not available", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    renderDaniel();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy outstanding items" }));
    expect(await screen.findByText(/Could not copy/)).toBeInTheDocument();
  });

  it("shows the earlier result when the screen is opened again", async () => {
    runCompletenessMock(DANIEL_CASE_ID, "pillar1-wage-earner@1");
    renderDaniel();
    expect(await screen.findByText("Incomplete")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  });
});

describe("CompletenessPanel overriding an item for Angela", () => {
  const openOverride = async () => {
    renderAngela();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    fireEvent.click(await screen.findByRole("button", { name: "Override Bank statements covering 2 months" }));
  };
  const reason = (text: string) =>
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: text } });

  it("starts incomplete with the August bank statement missing", async () => {
    renderAngela();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    expect(await screen.findByText("Incomplete")).toBeInTheDocument();
    expect(within(screen.getByTestId("item-bank_statement_2026-08")).getByText("Missing")).toBeInTheDocument();
    expect(screen.getByText("August 2026 bank statement")).toBeInTheDocument();
  });

  it("shows what the checklist found and will not confirm without a reason", async () => {
    await openOverride();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/The checklist found: No bank statement found for August 2026/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Override item" })).toBeDisabled();
    reason("   ");
    expect(screen.getByRole("button", { name: "Override item" })).toBeDisabled();
  });

  it("an override with a reason counts the item as satisfied: Complete, nothing outstanding", async () => {
    await openOverride();
    reason("Statement requested, due Monday");
    fireEvent.click(screen.getByRole("button", { name: "Override item" }));

    expect(await screen.findByText("Complete for this checklist")).toBeInTheDocument();
    expect(screen.queryByText("Incomplete")).not.toBeInTheDocument();
    expect(screen.getByText("Nothing outstanding.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy outstanding items" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const row = within(screen.getByTestId("item-bank_statement_2026-08"));
    expect(row.getByText("Overridden")).toBeInTheDocument();
    expect(row.getByText("Reason: Statement requested, due Monday")).toBeInTheDocument();
    expect(row.getByText("The checklist found: missing")).toBeInTheDocument();
  });

  it("the override is still there when the screen is opened again", async () => {
    await openOverride();
    reason("Statement requested");
    fireEvent.click(screen.getByRole("button", { name: "Override item" }));
    await screen.findByText("Complete for this checklist");

    renderAngela();
    expect((await screen.findAllByText("Complete for this checklist")).length).toBeGreaterThan(0);
  });

  it("Cancel changes nothing", async () => {
    await openOverride();
    reason("Statement requested");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Incomplete")).toBeInTheDocument();
  });
});
