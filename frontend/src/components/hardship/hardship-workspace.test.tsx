import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { getJobMock, JOB_QUEUE_MS, JOB_RUN_MS, resetMockStore, runHardshipMock } from "@/mocks/store";
import { HardshipWorkspace } from "./hardship-workspace";

beforeEach(() => resetMockStore());

const angela = mockCases.filter((c) => c.id === ANGELA_CASE_ID);

/** An analysis that already finished, as if someone ran it earlier. */
const finishEarlierRun = () => {
  const job = runHardshipMock(ANGELA_CASE_ID, 0);
  getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
};

const renderScreen = (cases = angela) => render(<HardshipWorkspace cases={cases} pillarSlug="loss-mitigation" />);
const openBudgetTab = () => fireEvent.click(screen.getByRole("tab", { name: "Budget" }));
const card = (label: string) => within(screen.getByRole("article", { name: label }));

describe("HardshipWorkspace before a run", () => {
  it("explains that nothing has been run yet and offers the Run button", async () => {
    renderScreen();
    expect(await screen.findByText(/No hardship analysis yet for Angela Whitfield — hardship/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });
});

describe("HardshipWorkspace with an earlier result: the Hardship tab", () => {
  beforeEach(() => finishEarlierRun());

  it("has two tabs and opens on Hardship", async () => {
    renderScreen();
    await screen.findByText("Illustrative settings");
    expect(screen.getByRole("tab", { name: "Hardship" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Budget" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  });

  it("shows the letter beside the profile, with each quote highlighted", async () => {
    const { container } = renderScreen();
    expect(await screen.findByRole("heading", { name: "Hardship letter" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Hardship profile" })).toBeInTheDocument();
    expect(container.querySelectorAll("mark")).toHaveLength(3);
    expect(card("Primary reason").getByText("Reduction in income")).toBeInTheDocument();
    expect(card("Intent").getByText("Keep the home")).toBeInTheDocument();
  });

  it("shows the consistency checks with stated against documented values", async () => {
    renderScreen();
    const row = within(await screen.findByTestId("check-hours_vs_pay"));
    expect(row.getByText("Hours cut from 40 to 30 a week")).toBeInTheDocument();
    expect(row.getByText(/25\.00% lower/)).toBeInTheDocument();
    expect(screen.getAllByText("Consistent")).toHaveLength(5);
    expect(within(screen.getByTestId("check-spending")).getByText("Flagged")).toBeInTheDocument();
  });

  it("Show in letter makes that item's quote stand out", async () => {
    const { container } = renderScreen();
    await screen.findByRole("heading", { name: "Hardship letter" });
    fireEvent.click(screen.getByRole("button", { name: "Show Intent in the letter" }));
    expect(container.querySelector('mark[data-quote="intent"]')!.className).toContain("bg-gold/50");
    expect(container.querySelector('mark[data-quote="duration"]')!.className).not.toContain("bg-gold/50");
    expect(screen.getByRole("button", { name: "Show Intent in the letter" })).toHaveAttribute("aria-pressed", "true");
  });

  it("Confirm marks the item reviewer-confirmed and takes its Confirm button away", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    fireEvent.click(screen.getByRole("button", { name: "Confirm Primary reason" }));
    expect(await card("Primary reason").findByText("Reviewer-confirmed")).toBeInTheDocument();
    expect(card("Primary reason").queryByRole("button", { name: "Confirm Primary reason" })).not.toBeInTheDocument();
    expect(card("Intent").getByText("Not reviewed")).toBeInTheDocument(); // the others are untouched
  });

  it("correcting the duration with a reason shows the new value and keeps what the letter said", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    fireEvent.click(screen.getByRole("button", { name: "Correct Duration" }));
    fireEvent.change(screen.getByLabelText("Correct value"), { target: { value: "long_term" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer said the cut is permanent" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    // While the window is open the rest of the page is hidden from assistive technology.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await card("Duration").findByText("Long-term")).toBeInTheDocument();
    expect(card("Duration").getByText("Reviewer-corrected")).toBeInTheDocument();
    expect(card("Duration").getByText("Read from the letter: Unknown")).toBeInTheDocument();
    expect(card("Duration").getByText("Reason: Employer said the cut is permanent")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the confirmations are still there after the screen is opened again", async () => {
    const first = renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    fireEvent.click(screen.getByRole("button", { name: "Confirm Intent" }));
    await card("Intent").findByText("Reviewer-confirmed");
    first.unmount();

    renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    expect(card("Intent").getByText("Reviewer-confirmed")).toBeInTheDocument();
  });
});

describe("HardshipWorkspace with an earlier result: the Budget tab", () => {
  beforeEach(() => finishEarlierRun());

  const openBudget = async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    openBudgetTab();
    await screen.findByRole("heading", { name: "Measures" });
  };

  it("shows the measures and the stated against observed table", async () => {
    await openBudget();
    expect(screen.getByRole("tab", { name: "Budget" })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByTestId("measure-surplus")).getByText("-280.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("measure-surplus")).getByText("Stated -70.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("measure-housing_ratio")).getByText("40.95%")).toBeInTheDocument();
    expect(within(screen.getByTestId("measure-arrears")).getByText("5,160.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("measure-liquid_assets")).getByText("12.41% of arrears")).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-other")).getByText("+210.00")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Hardship letter" })).not.toBeInTheDocument(); // the other tab is not shown
  });

  it("opens the working behind a measure", async () => {
    await openBudget();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Arrears" }));
    expect(await screen.findByText(/3 × 1,720\.00/)).toBeInTheDocument();
  });

  it("adjusting 'Other' to 200.00 with a reason updates the measures and the table at once", async () => {
    await openBudget();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "200.00" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off car repair in July" } });
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));

    await waitFor(() => expect(within(screen.getByTestId("measure-surplus")).getByText("-70.00", { selector: "div.text-2xl" })).toBeInTheDocument());
    expect(within(screen.getByTestId("measure-surplus")).queryByText("Flagged")).not.toBeInTheDocument();
    expect(screen.queryByText("Flagged")).not.toBeInTheDocument(); // nothing is flagged any more
    expect(within(screen.getByTestId("budget-total")).getByText("3,420.00", { selector: "td.font-semibold" })).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-other")).getByText("Reason: One-off car repair in July")).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-other")).getByText(/Documents showed 410\.00/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show working for Monthly surplus (observed)" }));
    expect(await screen.findAllByText(/3,350\.00 − 3,420\.00/)).toHaveLength(2); // both bases now use the same total
  });

  it("the Hardship tab's spending check follows the adjustment", async () => {
    await openBudget();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "200.00" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off" } });
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Hardship" }));
    const spending = within(await screen.findByTestId("check-spending"));
    expect(spending.getByText("Consistent")).toBeInTheDocument();
    expect(spending.getByText("Stated and observed spending agree within the tolerance.")).toBeInTheDocument();
  });

  it("clearing an adjustment puts the surplus back at -280.00 and the flag back", async () => {
    await openBudget();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "200.00" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off car repair in July" } });
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));
    await waitFor(() => expect(within(screen.getByTestId("measure-surplus")).getByText("-70.00", { selector: "div.text-2xl" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Clear the adjustment to Other" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Not a one-off after all" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear adjustment" }));

    await waitFor(() => expect(within(screen.getByTestId("measure-surplus")).getByText("-280.00", { selector: "div.text-2xl" })).toBeInTheDocument());
    expect(within(screen.getByTestId("budget-other")).getByText("410.00", { selector: "td.font-semibold" })).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-other")).queryByText(/Adjusted by/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear the adjustment to Other" })).not.toBeInTheDocument();
  });

  it("does not let an adjustment through without a reason", async () => {
    await openBudget();
    fireEvent.click(screen.getByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "200.00" } });
    expect(screen.getByRole("button", { name: "Adjust item" })).toBeDisabled();
    expect(within(screen.getByTestId("measure-surplus")).getByText("-280.00")).toBeInTheDocument();
  });
});

describe("HardshipWorkspace running the analysis", () => {
  it("runs, shows progress with the stage, then the result", async () => {
    renderScreen();
    await screen.findByText(/No hardship analysis yet/);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    // While it runs: progress, a disabled button, and no result yet.
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText(/Hardship analysis: /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeDisabled();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();

    // The mock job takes about 4 seconds on the real clock.
    expect(await screen.findByRole("heading", { name: "Hardship letter" }, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  }, 15000);

  it("shows the backend's message when a case has no hardship letter", async () => {
    renderScreen(mockCases.filter((c) => c.id === DANIEL_CASE_ID)); // Daniel's file has no hardship letter
    await screen.findByText(/No hardship analysis yet for Daniel Reyes/);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This case has no hardship letter to read");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled(); // can try again
  });
});
