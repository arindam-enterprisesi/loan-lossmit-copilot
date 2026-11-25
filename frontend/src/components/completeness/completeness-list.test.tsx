import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { applyOverride, buildCompleteness } from "@/mocks/completeness";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "@/mocks/data";
import { CompletenessList } from "./completeness-list";

const daniel = () => buildCompleteness(DANIEL_CASE_ID, "pillar1-wage-earner@1", "2026-11-20T09:00:00.000Z", "c1");
const angela = () => buildCompleteness(ANGELA_CASE_ID, "pillar2-hardship@1", "2026-11-20T09:00:00.000Z", "c2");

const names = {
  "d1000000-0000-4000-8000-000000000001": "reyes_paystub_2026-09.pdf",
};

const renderList = (items = daniel().items, onOverride: (i: unknown) => void = vi.fn()) =>
  render(
    <CompletenessList
      items={items}
      documentBase="/underwriting/document-intelligence/case-1"
      documentNames={names}
      onOverride={onOverride}
    />,
  );

describe("CompletenessList", () => {
  it("shows a status chip, the label and the reason for each item", () => {
    renderList();
    const stubs = within(screen.getByTestId("item-pay_stubs_30_days"));
    expect(stubs.getByText("Partially satisfied")).toBeInTheDocument();
    expect(stubs.getByText("Pay stubs covering 30 days")).toBeInTheDocument();
    expect(stubs.getByText("14 of 30 days of pay stubs found")).toBeInTheDocument();
    expect(within(screen.getByTestId("item-credit_report_120_days")).getByText("Satisfied")).toBeInTheDocument();
  });

  it("shows a Missing chip for an item with no documents", () => {
    renderList(angela().items);
    expect(within(screen.getByTestId("item-bank_statement_2026-08")).getByText("Missing")).toBeInTheDocument();
  });

  it("links the documents used by file name, and says Document when the name is not known", () => {
    renderList();
    const link = within(screen.getByTestId("item-pay_stubs_30_days")).getByRole("link", {
      name: "reyes_paystub_2026-09.pdf",
    });
    expect(link).toHaveAttribute(
      "href",
      "/underwriting/document-intelligence/case-1/d1000000-0000-4000-8000-000000000001",
    );
    expect(within(screen.getByTestId("item-w2_two_years")).getByRole("link", { name: "Document" })).toBeInTheDocument();
  });

  it("has no documents line for an item that used none", () => {
    renderList();
    expect(within(screen.getByTestId("item-tax_returns_two_years")).queryByText(/Documents used/)).not.toBeInTheDocument();
  });

  it("offers Override only on items that are partly met or missing", () => {
    renderList();
    expect(screen.getByRole("button", { name: "Override Pay stubs covering 30 days" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Override Credit report within 120 days" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Override / })).toHaveLength(4);
  });

  it("hands the item to onOverride when Override is pressed", () => {
    const onOverride = vi.fn();
    renderList(daniel().items, onOverride);
    fireEvent.click(screen.getByRole("button", { name: "Override W-2s for the last two tax years" }));
    expect(onOverride).toHaveBeenCalledWith(expect.objectContaining({ item_id: "w2_two_years" }));
  });

  it("has no Override buttons when no one can override", () => {
    render(
      <CompletenessList
        items={daniel().items}
        documentBase="/underwriting/document-intelligence/case-1"
        documentNames={names}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Override / })).not.toBeInTheDocument();
  });

  it("shows an override with who, when and why, next to what the checklist found", () => {
    const overridden = applyOverride(angela(), "bank_statement_2026-08", "Statement requested", "demo.reviewer", "2026-11-20T10:00:00.000Z");
    renderList(overridden.items);
    const row = within(screen.getByTestId("item-bank_statement_2026-08"));
    expect(row.getByText("Overridden")).toBeInTheDocument();
    expect(row.getByText(/Overridden by demo\.reviewer/)).toBeInTheDocument();
    expect(row.getByText("Reason: Statement requested")).toBeInTheDocument();
    expect(row.getByText("The checklist found: missing")).toBeInTheDocument();
    expect(row.getByText("No bank statement found for August 2026. October 2026 was found.")).toBeInTheDocument();
    expect(row.queryByRole("button", { name: /^Override / })).not.toBeInTheDocument(); // already done
  });
});
