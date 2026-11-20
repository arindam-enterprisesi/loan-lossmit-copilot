import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { getJobMock, JOB_QUEUE_MS, JOB_RUN_MS, resetMockStore, runIncomeMock } from "@/mocks/store";
import { IncomeWorkspace } from "./income-workspace";

beforeEach(() => {
  resetMockStore();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const daniel = mockCases.filter((c) => c.id === DANIEL_CASE_ID);

/** An analysis that already finished, as if someone ran it earlier. */
const finishEarlierRun = () => {
  const job = runIncomeMock(DANIEL_CASE_ID, 0);
  getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
};

const renderScreen = (cases = daniel) => render(<IncomeWorkspace cases={cases} pillarSlug="underwriting" />);

describe("IncomeWorkspace before a run", () => {
  it("explains that nothing has been run yet and offers the Run button", async () => {
    renderScreen();
    expect(await screen.findByText(/No income analysis yet for Daniel Reyes — purchase/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
    expect(screen.queryByText("Income components")).not.toBeInTheDocument();
  });
});

describe("IncomeWorkspace with an earlier result", () => {
  beforeEach(() => finishEarlierRun());

  it("shows Daniel's candidate monthly income of 5,980.00 with its label and working", async () => {
    renderScreen();
    const row = within(await screen.findByTestId("candidate-row"));
    expect(row.getByText("5,980.00")).toBeInTheDocument();
    expect(row.getByText("candidate - qualifying income is determined by the underwriter")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show working for Candidate monthly income" }));
    expect(screen.getByText("Sum of the components counted")).toBeInTheDocument();
  });

  it("shows the method, the components, the flag, the checks and the trend", async () => {
    renderScreen();
    await screen.findByText("Income components");
    expect(screen.getByText("Illustrative method")).toBeInTheDocument();
    expect(screen.getByText(/income-method@1 · run/)).toBeInTheDocument();
    expect(screen.getByText("Base pay (hourly)")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Flag income.short_history" })).toBeInTheDocument();
    expect(screen.getAllByText("Consistent")).toHaveLength(4);
    expect(screen.getByText(/Gross pay rose 5.49% in 2025/)).toBeInTheDocument();
  });

  it("offers Run again instead of Run analysis", async () => {
    renderScreen();
    expect(await screen.findByRole("button", { name: "Run again" })).toBeEnabled();
  });

  it("copies the suggested document requests", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Copy document requests" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("Documents that would help settle the income flags:");
    expect(text).toContain("- Final pay stub of 2025 showing year-to-date overtime and bonus");
    expect(text).toContain("- Employer letter stating how long overtime and bonus have been paid");
    expect(await screen.findByText("Copied to the clipboard.")).toBeInTheDocument();
  });

  it("says so when the clipboard is not available", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Copy document requests" }));
    expect(await screen.findByText(/Could not copy/)).toBeInTheDocument();
  });
});

describe("IncomeWorkspace including and excluding a component", () => {
  beforeEach(() => finishEarlierRun());

  const decide = (button: string, reason: string, confirm: string) => {
    fireEvent.click(screen.getByRole("button", { name: button }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: reason } });
    fireEvent.click(screen.getByRole("button", { name: confirm }));
  };

  it("counting overtime with a reason updates the candidate and its working at once", async () => {
    renderScreen();
    await screen.findByTestId("candidate-row");
    decide("Include Overtime (1.5x)", "Employer letter received", "Include in candidate");

    const row = within(screen.getByTestId("candidate-row"));
    expect(await row.findByText("6,424.41")).toBeInTheDocument();
    expect(row.queryByText("5,980.00")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const overtime = within(screen.getByTestId("component-overtime"));
    expect(overtime.getByText("Counted")).toBeInTheDocument();
    expect(overtime.getByText("Reason: Employer letter received")).toBeInTheDocument();
    expect(overtime.getByText(/The method said: left out/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show working for Candidate monthly income" }));
    expect(screen.getByText(/5,980\.00 \+ 444\.41/)).toBeInTheDocument();
    expect(screen.getByText(/Left out: Bonus \(228\.34\)/)).toBeInTheDocument();
  });

  it("the decision is still there after the screen is opened again", async () => {
    const first = renderScreen();
    await screen.findByTestId("candidate-row");
    decide("Include Overtime (1.5x)", "Employer letter received", "Include in candidate");
    await within(screen.getByTestId("candidate-row")).findByText("6,424.41");
    first.unmount();

    renderScreen();
    expect(await within(await screen.findByTestId("candidate-row")).findByText("6,424.41")).toBeInTheDocument();
  });

  it("excluding base pay takes it out, and including it again brings 5,980.00 back", async () => {
    renderScreen();
    await screen.findByTestId("candidate-row");
    decide("Exclude Base pay (hourly)", "Employment ended", "Exclude from candidate");
    expect(await within(screen.getByTestId("candidate-row")).findByText("0.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("component-base_pay")).getByText("Left out")).toBeInTheDocument();

    decide("Include Base pay (hourly)", "Employment confirmed", "Include in candidate");
    expect(await within(screen.getByTestId("candidate-row")).findByText("5,980.00")).toBeInTheDocument();
  });

  it("does not let a decision through without a reason", async () => {
    renderScreen();
    await screen.findByTestId("candidate-row");
    fireEvent.click(screen.getByRole("button", { name: "Include Overtime (1.5x)" }));
    expect(screen.getByRole("button", { name: "Include in candidate" })).toBeDisabled();
    expect(within(screen.getByTestId("candidate-row")).getByText("5,980.00")).toBeInTheDocument();
  });
});

describe("IncomeWorkspace running the analysis", () => {
  it("runs, shows progress with the stage, then the result", async () => {
    renderScreen();
    await screen.findByText(/No income analysis yet/);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    // While it runs: progress, a disabled button, and no result yet.
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText(/Income analysis: /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeDisabled();
    expect(screen.queryByText("Income components")).not.toBeInTheDocument();

    // The mock job takes about 4 seconds on the real clock.
    expect(await screen.findByText("Income components", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(within(screen.getByTestId("candidate-row")).getByText("5,980.00")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  }, 15000);

  it("shows the backend's message when a case has no income documents", async () => {
    renderScreen(mockCases);
    await screen.findByText(/No income analysis yet/);
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    await screen.findByText(/No income analysis yet for Angela Whitfield/);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This case has no income documents to analyse");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled(); // can try again
  });
});
