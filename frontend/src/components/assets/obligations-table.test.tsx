import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { applyObligationReview, buildDanielAssets, DANIEL_SCENARIO, type AssetRun } from "@/mocks/assets";
import { DANIEL_CASE_ID } from "@/mocks/data";
import { ObligationsTable } from "./obligations-table";

const RUN: AssetRun = { scenario: DANIEL_SCENARIO, candidate_monthly: "5980.00", overtime_monthly: "444.41" };
const base = () => buildDanielAssets(RUN, "2026-11-23T09:00:00.000Z");
const row = (a: ReturnType<typeof base>, creditor: string) => within(screen.getByTestId(`obligation-${a.obligations.find((o) => o.creditor.startsWith(creditor))!.id}`));

const setup = (a = base(), onDecide: ((id: string, counts: boolean, reason: string) => Promise<void>) | null = vi.fn().mockResolvedValue(undefined)) => {
  render(
    <ObligationsTable
      obligations={a.obligations}
      total={a.monthly_obligations}
      caseId={DANIEL_CASE_ID}
      pillarSlug="underwriting"
      onDecide={onDecide ?? undefined}
    />,
  );
  return { onDecide };
};

describe("ObligationsTable: what is shown", () => {
  it("lists the six debts with payment, balance and where each was found", () => {
    const a = base();
    setup(a);
    const auto = row(a, "Lakeshore");
    expect(auto.getByText("420.00")).toBeInTheDocument();
    expect(auto.getByText("14,860.00")).toBeInTheDocument();
    expect(auto.getByText("Bank and credit report")).toBeInTheDocument();
    expect(row(a, "Harbor").getByText("Credit report")).toBeInTheDocument();
    expect(row(a, "Oakmont").getByText("Bank statements")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^obligation-/)).toHaveLength(6);
  });

  it("counts the five debts and leaves the rent out, with the reason for each", () => {
    const a = base();
    setup(a);
    expect(row(a, "Lakeshore").getByText("Counted")).toBeInTheDocument();
    expect(row(a, "Oakmont").getByText("Left out")).toBeInTheDocument();
    expect(row(a, "Oakmont").getByText("Current rent on a purchase of a primary residence.")).toBeInTheDocument();
    expect(row(a, "Oakmont").getByText("—")).toBeInTheDocument(); // rent has no balance
  });

  it("totals the counted payments, 693.00, with its working", async () => {
    setup();
    const total = within(screen.getByTestId("obligations-total"));
    expect(total.getByText("693.00")).toBeInTheDocument();
    expect(total.getByText("The underwriter decides which debts count.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Monthly obligations counted" }));
    expect(await screen.findByText(/88\.00 \+ 40\.00 \+ 35\.00 \+ 420\.00 \+ 110\.00/)).toBeInTheDocument();
  });

  it("has no buttons when no one can decide", () => {
    setup(base(), null);
    expect(screen.queryByRole("button", { name: /^(Include|Exclude) / })).not.toBeInTheDocument();
  });

  it("says so when no debts were found", () => {
    render(<ObligationsTable obligations={[]} total={null} caseId={DANIEL_CASE_ID} pillarSlug="underwriting" />);
    expect(screen.getByText("No recurring debts were found.")).toBeInTheDocument();
  });
});

describe("ObligationsTable: deciding", () => {
  it("offers the opposite of what is shown: Exclude for a counted debt, Include for one left out", () => {
    setup();
    expect(screen.getByRole("button", { name: "Exclude Lakeshore Auto Finance" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Include Oakmont Apartments" })).toBeInTheDocument();
  });

  it("opens a window that says what will happen and what the settings said, and waits for a reason", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Exclude Brightpath Student Loan Servicing" }));
    expect(screen.getByText("Exclude Brightpath Student Loan Servicing")).toBeInTheDocument();
    expect(screen.getByText(/110\.00 a month, will be left out of the DTI\. The ratios update at once/)).toBeInTheDocument();
    expect(screen.getByText(/The settings say: counted\. On the credit report and in the bank statements\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exclude from DTI" })).toBeDisabled();
  });

  it("sends the debt, the choice and the reason, then closes", async () => {
    const a = base();
    const { onDecide } = setup(a);
    fireEvent.click(screen.getByRole("button", { name: "Exclude Brightpath Student Loan Servicing" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Deferred until 2027" } });
    fireEvent.click(screen.getByRole("button", { name: "Exclude from DTI" }));
    const id = a.obligations.find((o) => o.creditor.startsWith("Brightpath"))!.id;
    await waitFor(() => expect(onDecide).toHaveBeenCalledWith(id, false, "Deferred until 2027"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("including the rent sends counts = true", async () => {
    const a = base();
    const { onDecide } = setup(a);
    fireEvent.click(screen.getByRole("button", { name: "Include Oakmont Apartments" }));
    expect(screen.getByRole("button", { name: "Include in DTI" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Keeping the apartment" } });
    fireEvent.click(screen.getByRole("button", { name: "Include in DTI" }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledWith(a.obligations[5].id, true, "Keeping the apartment"));
  });

  it("keeps the window open with the message when refused", async () => {
    setup(base(), vi.fn().mockRejectedValue(new Error("A reason is required")));
    fireEvent.click(screen.getByRole("button", { name: "Exclude Northgate Card" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Exclude from DTI" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows a decision with who, when and why, and what the settings said", () => {
    const a = base();
    const id = a.obligations.find((o) => o.creditor.startsWith("Brightpath"))!.id;
    const changed = applyObligationReview(a, RUN, id, { counts_toward_dti: false, reason: "Deferred until 2027" }, "demo.reviewer", "2026-11-23T10:00:00.000Z");
    setup(changed);
    const r = row(changed, "Brightpath");
    expect(r.getByText("Left out")).toBeInTheDocument();
    expect(r.getByText("Excluded by demo.reviewer, 23 Nov 2026")).toBeInTheDocument();
    expect(r.getByText("Reason: Deferred until 2027")).toBeInTheDocument();
    expect(r.getByText(/The settings said: counted\./)).toBeInTheDocument();
    expect(within(screen.getByTestId("obligations-total")).getByText("583.00")).toBeInTheDocument();
  });
});
