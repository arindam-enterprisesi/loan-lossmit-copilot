import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { applyBudgetAdjustment, buildAngelaHardship } from "@/mocks/hardship";
import { BudgetTable } from "./budget-table";

const base = () => buildAngelaHardship("2026-11-20T09:00:00.000Z");
const row = (id: string) => within(screen.getByTestId(`budget-${id}`));

const setup = (
  budget = base().budget,
  onAdjust: ((id: string, amount: string, reason: string) => Promise<void>) | null = vi.fn().mockResolvedValue(undefined),
) => {
  render(<BudgetTable budget={budget} onAdjust={onAdjust ?? undefined} />);
  return { onAdjust };
};

describe("BudgetTable", () => {
  it("shows stated and observed by category, with thousands separators", () => {
    setup();
    expect(row("housing").getAllByText("1,720.00")).toHaveLength(2); // stated and observed
    expect(row("utilities").getAllByText("310.00")).toHaveLength(2);
    expect(row("other").getByText("200.00")).toBeInTheDocument();
    expect(row("other").getByText("410.00")).toBeInTheDocument();
  });

  it("highlights the difference in 'Other': +210.00, flagged, with the sentence", () => {
    setup();
    const other = row("other");
    expect(other.getByText("+210.00")).toBeInTheDocument();
    expect(other.getByText("Flagged")).toBeInTheDocument();
    expect(other.getByText("Observed 'other' spending 410.00 against 200.00 stated — ask the borrower")).toBeInTheDocument();
    expect(screen.getByTestId("budget-other").className).toContain("bg-gold/10");
  });

  it("shows 0.00 and no highlight where stated and observed agree", () => {
    setup();
    expect(row("housing").getByText("0.00")).toBeInTheDocument();
    expect(row("housing").queryByText("Flagged")).not.toBeInTheDocument();
    expect(screen.getByTestId("budget-housing").className).not.toContain("bg-gold/10");
    expect(screen.getAllByText("Flagged")).toHaveLength(1);
  });

  it("totals both bases and says where the observed amounts come from", () => {
    setup();
    const total = within(screen.getByTestId("budget-total"));
    expect(total.getByText("3,420.00")).toBeInTheDocument();
    expect(total.getByText("3,630.00")).toBeInTheDocument();
    expect(screen.getByText(/Observed basis: July 2026 statement/)).toBeInTheDocument();
  });

  it("shows a gap that came without a sign as it came, with no plus added", () => {
    const budget = base().budget;
    budget.lines = budget.lines.map((l) => (l.id === "other" ? { ...l, difference_unsigned: true } : l));
    setup(budget);
    expect(row("other").getByText("210.00")).toBeInTheDocument();
    expect(row("other").queryByText("+210.00")).not.toBeInTheDocument();
  });

  it("has no Adjust buttons when no one can adjust", () => {
    setup(base().budget, null);
    expect(screen.queryByRole("button", { name: /^Adjust / })).not.toBeInTheDocument();
  });

  it("offers Adjust on every category", () => {
    setup();
    expect(screen.getAllByRole("button", { name: /^Adjust / })).toHaveLength(5);
  });

  it("Adjust opens a window with the stated and documented amounts and the current amount in the box", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Adjust Other")).toBeInTheDocument();
    expect(screen.getByText("Stated 200.00. The documents showed 410.00.")).toBeInTheDocument();
    expect(screen.getByLabelText("Amount counted each month")).toHaveValue("410.00");
    expect(screen.getByRole("button", { name: "Adjust item" })).toBeDisabled(); // no reason yet
  });

  it("sends the item, the amount and the reason, then closes", async () => {
    const { onAdjust } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "200.00" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off car repair in July" } });
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));
    await waitFor(() => expect(onAdjust).toHaveBeenCalledWith("other", "200.00", "One-off car repair in July"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("will not send an amount that is not a plain amount", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "lots" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off" } });
    expect(screen.getByText("Enter an amount such as 200.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adjust item" })).toBeDisabled();
  });

  it("keeps the window open with the message when the adjustment is refused", async () => {
    setup(base().budget, vi.fn().mockRejectedValue(new Error("Server is busy")));
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off" } });
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Server is busy");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("One-off");
  });

  it("shows an adjustment with who, when and why, and what the documents showed", () => {
    const adjusted = applyBudgetAdjustment(
      base(),
      "other",
      { amount: "200.00", reason: "One-off car repair" },
      "demo.reviewer",
      "2026-11-20T10:00:00.000Z",
    ).budget;
    setup(adjusted);
    const other = row("other");
    expect(other.getByText(/Adjusted by demo\.reviewer, 20 Nov 2026\. Documents showed 410\.00\./)).toBeInTheDocument();
    expect(other.getByText("Reason: One-off car repair")).toBeInTheDocument();
    expect(other.queryByText("Flagged")).not.toBeInTheDocument(); // the gap is gone
    expect(within(screen.getByTestId("budget-total")).getByText("3,420.00", { selector: "td.font-semibold" })).toBeInTheDocument();
  });

  it("the window shows what the documents showed, not the adjusted amount, when adjusting again", () => {
    const adjusted = applyBudgetAdjustment(base(), "other", { amount: "300.00", reason: "r" }, "u", "2026-11-20T10:00:00.000Z").budget;
    setup(adjusted);
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    expect(screen.getByText("Stated 200.00. The documents showed 410.00.")).toBeInTheDocument();
    expect(screen.getByLabelText("Amount counted each month")).toHaveValue("300.00");
  });
});
