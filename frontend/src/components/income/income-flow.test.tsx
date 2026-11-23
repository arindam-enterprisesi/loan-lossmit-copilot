import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore } from "@/mocks/store";
import { IncomeWorkspace } from "./income-workspace";

/**
 * The Day 4 "done when" walked through in one go, on the real mock backend (nothing stubbed):
 * run the analysis, see 5,980.00, open the working, leave a component out with a reason, put it back.
 * The earlier tests check each piece alone; this one checks they work together in order.
 */
beforeEach(() => resetMockStore());

const daniel = mockCases.filter((c) => c.id === DANIEL_CASE_ID);

describe("Income analysis, start to finish for Daniel Reyes", () => {
  it("run → 5,980.00 → working → overtime counted with a reason → left out again", async () => {
    render(<IncomeWorkspace cases={daniel} pillarSlug="underwriting" />);

    // 1. Nothing run yet.
    await screen.findByText(/No income analysis yet for Daniel Reyes/);

    // 2. Run it: progress shows, then the result replaces it.
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    const candidate = await screen.findByTestId("candidate-row", {}, { timeout: 8000 });

    // 3. The candidate is 5,980.00 and says it is only a candidate.
    expect(within(candidate).getByText("5,980.00")).toBeInTheDocument();
    expect(
      within(candidate).getByText("candidate - qualifying income is determined by the underwriter"),
    ).toBeInTheDocument();

    // 4. Open the working behind base pay: the formula, its result and the pay stub it was read from.
    fireEvent.click(screen.getByRole("button", { name: "Show working for Base pay (hourly), monthly" }));
    expect(await screen.findByText(/34\.50 × 80\.00 hours × 26 periods ÷ 12/)).toBeInTheDocument();
    expect(screen.getByText("Base pay, monthly")).toBeInTheDocument();
    expect(screen.getAllByRole("link").some((l) => (l.getAttribute("href") ?? "").includes("document-intelligence"))).toBe(true);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Base pay, monthly")).not.toBeInTheDocument());

    // 5. The flag and its explanation are there, marked as possible, not as a finding.
    expect(screen.getByRole("article", { name: "Flag income.short_history" })).toBeInTheDocument();
    expect(screen.getAllByText(/possible — to be confirmed/i).length).toBeGreaterThan(0);

    // 6. Count overtime, with a reason: the candidate and its working change together.
    fireEvent.click(screen.getByRole("button", { name: "Include Overtime (1.5x)" }));
    expect(screen.getByRole("button", { name: "Include in candidate" })).toBeDisabled(); // no reason yet
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer letter received" } });
    fireEvent.click(screen.getByRole("button", { name: "Include in candidate" }));
    expect(await within(screen.getByTestId("candidate-row")).findByText("6,424.41")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(screen.getByTestId("component-overtime")).getByText("Reason: Employer letter received")).toBeInTheDocument();

    // 7. Leave it out again: the original 5,980.00 returns, and the history of the decision stays visible.
    fireEvent.click(screen.getByRole("button", { name: "Exclude Overtime (1.5x)" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Letter turned out to cover bonus only" } });
    fireEvent.click(screen.getByRole("button", { name: "Exclude from candidate" }));
    expect(await within(screen.getByTestId("candidate-row")).findByText("5,980.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("component-overtime")).getByText("Left out")).toBeInTheDocument();
  }, 20000);
});
