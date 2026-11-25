import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChecklistItem } from "@/lib/completeness";
import { CompletenessList } from "./completeness-list";

// What the real backend sends (backend/app/api/schemas/completeness.py): the contract's item, with no
// original_status, overridden_by or overridden_at.
const item = (over: Partial<ChecklistItem> & { item_id: string }): ChecklistItem => ({
  label: over.item_id,
  status: "partial",
  reason: "14 of 30 days of pay stubs found",
  document_ids: [],
  override_reason: null,
  ...over,
});

const setup = (items: ChecklistItem[], onOverride = vi.fn()) => {
  render(<CompletenessList items={items} documentBase="/underwriting/document-intelligence/c1" documentNames={{}} onOverride={onOverride} />);
  return { onOverride };
};

describe("CompletenessList with items shaped as the real backend sends them", () => {
  it("an overridden item shows 'Overridden' and the reason, and says nothing it was not told about who or when", () => {
    setup([item({ item_id: "pay_stubs_30_days", label: "Pay stubs covering 30 days", status: "overridden", override_reason: "Employer letter received" })]);
    const row = within(screen.getByTestId("item-pay_stubs_30_days"));
    expect(row.getByText("Overridden", { selector: "span" })).toBeInTheDocument();
    expect(row.getByText("Reason: Employer letter received")).toBeInTheDocument();
    expect(row.getByText("14 of 30 days of pay stubs found")).toBeInTheDocument(); // the checklist's own reason is kept
    expect(row.queryByText(/ by /)).not.toBeInTheDocument();
    expect(row.queryByText(/The checklist found/)).not.toBeInTheDocument();
    expect(row.queryByRole("button", { name: /^Override/ })).not.toBeInTheDocument();
  });

  it("an item the backend marked 'Needs review' arrives as partial, with its reason, and can be overridden", () => {
    const { onOverride } = setup([
      item({ item_id: "w2_two_years", label: "W-2 for two years", reason: "Needs review: the employer name could not be read" }),
    ]);
    const row = within(screen.getByTestId("item-w2_two_years"));
    expect(row.getByText("Needs review: the employer name could not be read")).toBeInTheDocument();
    fireEvent.click(row.getByRole("button", { name: "Override W-2 for two years" }));
    expect(onOverride).toHaveBeenCalledTimes(1);
  });

  it("a satisfied item has no override button, and a missing one has", () => {
    setup([item({ item_id: "a", status: "satisfied" }), item({ item_id: "b", status: "missing" })]);
    expect(within(screen.getByTestId("item-a")).queryByRole("button")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("item-b")).getByRole("button", { name: /^Override/ })).toBeInTheDocument();
  });
});
