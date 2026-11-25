import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildDanielAssets, DANIEL_SCENARIO, type AssetRun } from "@/mocks/assets";
import { DANIEL_CASE_ID } from "@/mocks/data";
import { TransactionsTable } from "./transactions-table";

const RUN: AssetRun = { scenario: DANIEL_SCENARIO, candidate_monthly: "5980.00", overtime_monthly: "444.41" };
const base = () => buildDanielAssets(RUN, "2026-11-23T09:00:00.000Z").transactions;
const row = (transactions: ReturnType<typeof base>, description: string, nth = 0) => {
  const t = transactions.filter((x) => x.description.startsWith(description))[nth];
  return within(screen.getByTestId(`transaction-${t.id}`));
};

const setup = (transactions = base(), handlers: { onReclassify?: unknown; onSource?: unknown } | null = {}) => {
  const onReclassify = vi.fn().mockResolvedValue(undefined);
  const onSource = vi.fn().mockResolvedValue(undefined);
  render(
    <TransactionsTable
      transactions={transactions}
      caseId={DANIEL_CASE_ID}
      pillarSlug="underwriting"
      onReclassify={handlers === null ? undefined : ((handlers.onReclassify as typeof onReclassify) ?? onReclassify)}
      onSource={handlers === null ? undefined : ((handlers.onSource as typeof onSource) ?? onSource)}
    />,
  );
  return { onReclassify, onSource };
};

describe("TransactionsTable: what is shown", () => {
  it("groups the lines under the account ending 6032 and counts them", () => {
    setup();
    const section = screen.getByRole("region", { name: "Account ending 6032" });
    expect(within(section).getByText("30 lines")).toBeInTheDocument();
    expect(within(section).getAllByRole("row")).toHaveLength(31); // the header and 30 lines
  });

  it("shows each line's date, description, counterparty, amount and category", () => {
    const t = base();
    setup(t);
    const rent = row(t, "OAKMONT");
    expect(rent.getByText("1 Sept 2026")).toBeInTheDocument();
    expect(rent.getByText("OAKMONT APARTMENTS RENT")).toBeInTheDocument();
    expect(rent.getByText(/Oakmont Apartments/)).toBeInTheDocument();
    expect(rent.getByText("-1,425.00")).toBeInTheDocument();
    expect(rent.getByText("Housing payment")).toBeInTheDocument();
  });

  it("links each line to the statement it is on", () => {
    const t = base();
    setup(t);
    expect(row(t, "OAKMONT").getByRole("link", { name: "line p1-L8" })).toHaveAttribute(
      "href",
      expect.stringContaining(`/underwriting/document-intelligence/${DANIEL_CASE_ID}/`),
    );
  });

  it("both paychecks carry 'Matches pay stub', with the backend's working as the hover text", () => {
    const t = base();
    setup(t);
    for (const nth of [0, 1]) {
      const pay = row(t, "CEDAR VALLEY", nth);
      expect(pay.getByText("Matches pay stub")).toBeInTheDocument();
      expect(pay.getByText("Matches pay stub").closest("span[title]")).toHaveAttribute("title", expect.stringContaining("2,033.61"));
    }
  });

  it("flags the 2,000.00 transfer as a large deposit, with the sentence, and highlights the row", () => {
    const t = base();
    setup(t);
    const deposit = row(t, "ZELLE");
    expect(deposit.getByText("Large deposit")).toBeInTheDocument();
    expect(deposit.getByText("Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules.")).toBeInTheDocument();
    expect(screen.getByTestId(`transaction-${t.find((x) => x.description.startsWith("ZELLE"))!.id}`).className).toContain("bg-gold/10");
    expect(screen.getByTestId(`transaction-${t[0].id}`).className).not.toContain("bg-gold/10");
  });

  it("filters to the lines that need a look, and says how many there are", () => {
    setup();
    fireEvent.click(screen.getByLabelText(/Only lines that need a look \(1\)/));
    const section = screen.getByRole("region", { name: "Account ending 6032" });
    expect(within(section).getByText("1 of 30 lines")).toBeInTheDocument();
    expect(within(section).getAllByRole("row")).toHaveLength(2);
    expect(screen.queryByText("OAKMONT APARTMENTS RENT")).not.toBeInTheDocument();
  });

  it("says when no lines need a look", () => {
    const clean = base().map((t) => ({ ...t, flags: [] }));
    setup(clean);
    fireEvent.click(screen.getByLabelText(/Only lines that need a look \(0\)/));
    expect(screen.getByText("No lines need a look on this account.")).toBeInTheDocument();
  });

  it("shows a line the model could not label as needing review", () => {
    const t = base();
    t[6] = { ...t[6], needs_review: true };
    setup(t);
    expect(row(t, "TARGET").getByText("Needs review")).toBeInTheDocument();
  });

  it("says so when there are no lines", () => {
    setup([]);
    expect(screen.getByText("No bank lines were found.")).toBeInTheDocument();
  });

  it("has no action buttons when no one can change anything", () => {
    setup(base(), null);
    expect(screen.queryByRole("button", { name: /Reclassify/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Action" })).not.toBeInTheDocument();
  });
});

describe("TransactionsTable: reclassify", () => {
  it("opens a window with the categories, starting on the current one, and what the system chose", () => {
    const t = base();
    setup(t);
    fireEvent.click(screen.getByRole("button", { name: "Reclassify TARGET T-1124 (p1-L14)" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("The system labelled it: Other")).toBeInTheDocument();
    const select = screen.getByLabelText("Category");
    expect(select).toHaveValue("other");
    expect(select.querySelectorAll("option")).toHaveLength(14);
    expect(screen.getByRole("button", { name: "Save category" })).toBeDisabled(); // no reason yet
  });

  it("sends the line, the chosen category and the reason, then closes", async () => {
    const t = base();
    const { onReclassify } = setup(t);
    const target = t.find((x) => x.description === "TARGET T-1124")!;
    fireEvent.click(screen.getByRole("button", { name: `Reclassify TARGET T-1124 (${target.line_id})` }));
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "everyday spending" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "A grocery run" } });
    fireEvent.click(screen.getByRole("button", { name: "Save category" }));
    await waitFor(() => expect(onReclassify).toHaveBeenCalledWith(target.id, "everyday spending", "A grocery run"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the window open with the message when it is refused", async () => {
    const t = base();
    setup(t, { onReclassify: vi.fn().mockRejectedValue(new Error("A reason is required")) });
    fireEvent.click(screen.getByRole("button", { name: "Reclassify OAKMONT APARTMENTS RENT (p1-L8)" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save category" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("x");
  });

  it("shows a changed line with who, when and why, and what the system said", () => {
    const t = base();
    t[6] = {
      ...t[6],
      category: "everyday spending",
      category_source: "user",
      change: { reason: "A grocery run", by: "demo.reviewer", at: "2026-11-23T10:00:00.000Z" },
    };
    setup(t);
    const changed = row(t, "TARGET");
    expect(changed.getByText("Everyday spending")).toBeInTheDocument();
    expect(changed.getByText("Changed by demo.reviewer, 23 Nov 2026")).toBeInTheDocument();
    expect(changed.getByText("Reason: A grocery run")).toBeInTheDocument();
    expect(changed.getByText("The system said: Other")).toBeInTheDocument();
  });
});

describe("TransactionsTable: marking a deposit as sourced", () => {
  it("only deposits can be marked", () => {
    setup();
    expect(screen.getAllByRole("button", { name: /^Mark as sourced:/ })).toHaveLength(3); // two paychecks and the transfer
    expect(screen.queryByRole("button", { name: /Mark as sourced: OAKMONT/ })).not.toBeInTheDocument();
  });

  it("sends the deposit, sourced, and the note", async () => {
    const t = base();
    const { onSource } = setup(t);
    const deposit = t.find((x) => x.description.startsWith("ZELLE"))!;
    fireEvent.click(screen.getByRole("button", { name: `Mark as sourced: ${deposit.description} (${deposit.line_id})` }));
    expect(screen.getByText("Mark the deposit as sourced")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Gift from a relative, letter on file" } });
    fireEvent.click(screen.getByRole("button", { name: "Mark as sourced" }));
    await waitFor(() => expect(onSource).toHaveBeenCalledWith(deposit.id, true, "Gift from a relative, letter on file"));
  });

  it("shows a sourced deposit with its note, and offers to remove the mark", async () => {
    const t = base();
    const i = t.findIndex((x) => x.description.startsWith("ZELLE"));
    t[i] = { ...t[i], sourced: true, sourced_note: "Gift letter on file" };
    const { onSource } = setup(t);
    const deposit = row(t, "ZELLE");
    expect(deposit.getByText("Sourced")).toBeInTheDocument();
    expect(deposit.getByText("Source: Gift letter on file")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: `Remove the sourced mark from ${t[i].description} (${t[i].line_id})` }));
    expect(screen.getByText("Remove the sourced mark")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Wrong deposit" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove mark" }));
    await waitFor(() => expect(onSource).toHaveBeenCalledWith(t[i].id, false, "Wrong deposit"));
  });
});
