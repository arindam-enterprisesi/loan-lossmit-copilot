import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { getJobMock, JOB_QUEUE_MS, JOB_RUN_MS, resetMockStore, runAssetsMock } from "@/mocks/store";
import { AssetsWorkspace } from "./assets-workspace";

beforeEach(() => resetMockStore());

const daniel = mockCases.filter((c) => c.id === DANIEL_CASE_ID);

/** An analysis that already finished, as if someone ran it earlier. */
const finishEarlierRun = () => {
  const job = runAssetsMock(DANIEL_CASE_ID, 0);
  getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
};

const renderScreen = (cases = daniel) => render(<AssetsWorkspace cases={cases} pillarSlug="underwriting" />);
const figure = (id: string) => within(screen.getByTestId(`figure-${id}`));
const reason = (text: string) => fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: text } });

describe("AssetsWorkspace before a run", () => {
  it("shows Daniel's saved loan scenario, says nothing has been run, and offers Run", async () => {
    renderScreen();
    expect(await screen.findByLabelText("Loan purpose")).toHaveValue("purchase");
    expect(screen.getByLabelText("Loan amount")).toHaveValue("360000.00");
    expect(screen.getByText(/No asset analysis yet for Daniel Reyes — purchase/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
    expect(screen.queryByTestId("figure-dti")).not.toBeInTheDocument();
  });
});

describe("AssetsWorkspace with an earlier result", () => {
  beforeEach(() => finishEarlierRun());

  it("shows Daniel's DTI of 44.70% with its working", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    expect(figure("dti").getByText("44.70%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show working for DTI" }));
    expect(await screen.findByText(/\(1,980\.00 \+ 693\.00\) ÷ 5,980\.00 × 100/)).toBeInTheDocument();
  });

  it("shows the strip, the flags, the obligations and the transactions", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    expect(figure("documented_assets").getByText("9,226.32")).toBeInTheDocument();
    expect(figure("funds_shortfall").getByText("27,273.68")).toBeInTheDocument();
    expect(figure("front_end_ratio").getByText("33.11%")).toBeInTheDocument();
    expect(figure("ltv").getByText("90.00%")).toBeInTheDocument();
    expect(screen.getByTestId("flag-AL-W101")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^obligation-/)).toHaveLength(6);
    expect(screen.getByRole("region", { name: "Account ending 6032" })).toBeInTheDocument();
    expect(screen.getByText("Illustrative settings")).toBeInTheDocument();
    expect(screen.getByText(/Candidate figures for the underwriter to review/)).toBeInTheDocument();
  });

  it("offers Run again instead of Run analysis", async () => {
    renderScreen();
    expect(await screen.findByRole("button", { name: "Run again" })).toBeEnabled();
  });
});

describe("AssetsWorkspace: deciding which debts count", () => {
  beforeEach(() => finishEarlierRun());

  const decide = (button: string, text: string, confirm: string) => {
    fireEvent.click(screen.getByRole("button", { name: button }));
    reason(text);
    fireEvent.click(screen.getByRole("button", { name: confirm }));
  };

  it("leaving out the student loan updates every figure at once: obligations 583.00, DTI 42.86%, the flag gone", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    decide("Exclude Brightpath Student Loan Servicing", "Deferred until 2027", "Exclude from DTI");

    expect(await figure("dti").findByText("42.86%")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(screen.getByTestId("obligations-total")).getByText("583.00")).toBeInTheDocument();
    expect(figure("dti").queryByText("Above the review level")).not.toBeInTheDocument();
    expect(screen.queryByTestId("flag-AL-W106")).not.toBeInTheDocument();
    expect(figure("front_end_ratio").getByText("33.11%")).toBeInTheDocument(); // not touched

    fireEvent.click(screen.getByRole("button", { name: "Show working for DTI" }));
    expect(await screen.findByText(/\(1,980\.00 \+ 583\.00\) ÷ 5,980\.00 × 100/)).toBeInTheDocument();
  });

  it("the decision, its reason and what the settings said stay on the row", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    decide("Exclude Brightpath Student Loan Servicing", "Deferred until 2027", "Exclude from DTI");
    const row = within(await screen.findByText("Reason: Deferred until 2027").then((el) => el.closest("tr")!));
    expect(row.getByText("Left out")).toBeInTheDocument();
    expect(row.getByText(/Excluded by demo\.reviewer/)).toBeInTheDocument();
    expect(row.getByText(/The settings said: counted/)).toBeInTheDocument();
  });

  it("counting the rent as well brings the DTI flag back at 68.53%, and it can be reversed", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    decide("Include Oakmont Apartments", "Keeping the apartment", "Include in DTI");
    expect(await figure("dti").findByText("68.53%")).toBeInTheDocument();
    expect(screen.getByTestId("flag-AL-W106")).toBeInTheDocument();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    decide("Exclude Oakmont Apartments", "Moving into the new home", "Exclude from DTI");
    expect(await figure("dti").findByText("44.70%")).toBeInTheDocument();
  });

  it("does not let a decision through without a reason", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.click(screen.getByRole("button", { name: "Exclude Northgate Card" }));
    expect(screen.getByRole("button", { name: "Exclude from DTI" })).toBeDisabled();
    expect(figure("dti").getByText("44.70%")).toBeInTheDocument();
  });

  it("the decision is still there after the screen is opened again", async () => {
    const first = renderScreen();
    await screen.findByTestId("figure-dti");
    decide("Exclude Brightpath Student Loan Servicing", "Deferred", "Exclude from DTI");
    await figure("dti").findByText("42.86%");
    first.unmount();

    renderScreen();
    await screen.findByTestId("figure-dti");
    expect(figure("dti").getByText("42.86%")).toBeInTheDocument();
  });
});

describe("AssetsWorkspace: transactions", () => {
  beforeEach(() => finishEarlierRun());

  it("marking the 2,000.00 deposit as sourced resolves its flag, with the note on the line", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.click(screen.getByRole("button", { name: /^Mark as sourced: ZELLE FROM PATRICIA OWENS/ }));
    reason("Gift from a relative, letter on file");
    fireEvent.click(screen.getByRole("button", { name: "Mark as sourced" }));

    expect(await within(screen.getByTestId("flag-AL-W101")).findByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText("Source: Gift from a relative, letter on file")).toBeInTheDocument();
    expect(figure("dti").getByText("44.70%")).toBeInTheDocument(); // no ratio changes: the underwriter still decides
  });

  it("reclassifying a line changes its chip, keeps the system's label and shows the reason", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.click(screen.getAllByRole("button", { name: /^Reclassify TARGET T-1124/ })[0]);
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "everyday spending" } });
    reason("A grocery run");
    fireEvent.click(screen.getByRole("button", { name: "Save category" }));

    expect(await screen.findByText("Reason: A grocery run")).toBeInTheDocument();
    expect(screen.getAllByText("The system said: Other").length).toBe(1);
    expect(screen.getByText(/Changed by demo\.reviewer/)).toBeInTheDocument();
  });
});

describe("AssetsWorkspace: the loan scenario", () => {
  beforeEach(() => finishEarlierRun());

  it("saving a changed scenario after a run says the figures use the earlier one", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.change(screen.getByLabelText("Proposed monthly housing payment"), { target: { value: "2100.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    expect(await screen.findByRole("status")).toHaveTextContent("The loan scenario was saved after these figures were worked out");
    expect(figure("front_end_ratio").getByText("33.11%")).toBeInTheDocument(); // still the earlier figures
  });

  it("refuses a property value of zero before sending, and nothing changes", async () => {
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.change(screen.getByLabelText("Property value"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    expect(screen.getByText("Must be more than zero")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("AssetsWorkspace running the analysis", () => {
  it("saves a changed scenario, runs, shows progress with the stage, then new figures: front-end ratio 35.12%", async () => {
    renderScreen();
    await screen.findByLabelText("Loan purpose");
    fireEvent.change(screen.getByLabelText("Proposed monthly housing payment"), { target: { value: "2100.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    await waitFor(() => expect(screen.queryByText("Not saved yet.")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    // While it runs: progress, a disabled button, and no result yet.
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText(/Asset and liability analysis: /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeDisabled();
    expect(screen.queryByTestId("figure-dti")).not.toBeInTheDocument();

    // The mock job takes about 4 seconds on the real clock.
    expect(await screen.findByText("35.12%", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(figure("dti").getByText("46.71%")).toBeInTheDocument(); // (2,100.00 + 693.00) ÷ 5,980.00
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  }, 15000);

  it("another case with no loan scenario waits for one before it can run, and a save is refused by the backend", async () => {
    renderScreen(mockCases);
    await screen.findByLabelText("Loan purpose");
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    expect(await screen.findByText("Save the loan scenario first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Loan purpose"), { target: { value: "purchase" } });
    fireEvent.change(screen.getByLabelText("Occupancy"), { target: { value: "primary residence" } });
    for (const [label, value] of [
      ["Property value", "300000.00"],
      ["Loan amount", "240000.00"],
      ["Proposed monthly housing payment", "1500.00"],
      ["Funds needed to close", "20000.00"],
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Case not found");
    expect(screen.getByLabelText("Property value")).toHaveValue("300000.00"); // what was typed is kept
  });
});
