import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore, runCopilotMock } from "@/mocks/store";
import { UnderwritingCopilotWorkspace } from "./underwriting-copilot-workspace";

beforeEach(() => resetMockStore());

const daniel = mockCases.filter((c) => c.id === DANIEL_CASE_ID);

/** A run that finished earlier. A run started at time 0 is long over by now. The first run of a case has the demo's failed Critic. */
const finishEarlierRun = ({ criticFails }: { criticFails: boolean }) => {
  runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
  if (!criticFails) runCopilotMock("underwriting", DANIEL_CASE_ID, 0); // a later run: every agent succeeds
};

const renderScreen = (cases = daniel) => render(<UnderwritingCopilotWorkspace cases={cases} pillarSlug="underwriting" />);
const reason = (text: string) => fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: text } });
const condition = (n: number) => within(screen.getByTestId(`condition-uwc-${n}`));

describe("UnderwritingCopilotWorkspace before a run", () => {
  it("says nothing has been run and offers Run copilot, with no agents or report", async () => {
    renderScreen();
    expect(await screen.findByText(/No underwriting report yet for Daniel Reyes — purchase/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run copilot" })).toBeEnabled();
    expect(screen.queryByRole("list", { name: "Agent progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Findings" })).not.toBeInTheDocument();
  });
});

describe("UnderwritingCopilotWorkspace with an earlier run", () => {
  beforeEach(() => finishEarlierRun({ criticFails: false }));

  it("shows the three agents done, and offers Run again", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Case snapshot" });
    for (const agent of ["researcher", "writer", "critic"]) expect(within(screen.getByTestId(`agent-${agent}`)).getByText("Done")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Re-run/ })).not.toBeInTheDocument();
  });

  it("shows the case snapshot with amounts formatted and the ratios as the backend wrote them", async () => {
    renderScreen();
    const snapshot = within(await screen.findByRole("heading", { name: "Case snapshot" }).then((h) => h.closest("section")!));
    expect(snapshot.getByText("Daniel Reyes")).toBeInTheDocument();
    expect(snapshot.getByText("400,000.00")).toBeInTheDocument();
    expect(snapshot.getByText("360,000.00")).toBeInTheDocument();
    expect(snapshot.getByText("5,980.00")).toBeInTheDocument();
    expect(snapshot.getAllByText("44.70%").length).toBeGreaterThanOrEqual(1);
    expect(snapshot.getByText("90.00%")).toBeInTheDocument();
  });

  it("shows the DTI conflict openly: 44.70%, or 41.61% if overtime is counted", async () => {
    renderScreen();
    const title = await screen.findByText("DTI changes with the treatment of overtime");
    const callout = within(title.closest("[role=note]") as HTMLElement);
    expect(callout.getByText("DTI changes with the treatment of overtime")).toBeInTheDocument();
    expect(callout.getByText("44.70%")).toBeInTheDocument();
    expect(callout.getByText("41.61%")).toBeInTheDocument();
    expect(callout.getByText(/The underwriter decides which income to use/)).toBeInTheDocument();
  });

  it("groups the eight findings by priority: three significant, four attention, one information, each with evidence", async () => {
    renderScreen();
    await screen.findByRole("region", { name: "Significant findings" });
    expect(within(screen.getByRole("region", { name: "Significant findings" })).getAllByRole("article")).toHaveLength(3);
    expect(within(screen.getByRole("region", { name: "Attention findings" })).getAllByRole("article")).toHaveLength(4);
    expect(within(screen.getByRole("region", { name: "Information findings" })).getAllByRole("article")).toHaveLength(1);
    const dti = within(screen.getByRole("article", { name: "DTI is 44.70%, above the illustrative 43% review level" }));
    expect(dti.getByRole("link", { name: "DTI" })).toHaveAttribute("href", "/underwriting/assets-liabilities");
    expect(dti.getByRole("link", { name: "Rule AL-W106" })).toBeInTheDocument();
    const netPay = within(screen.getByRole("article", { name: "The printed net pay was corrected by a reviewer" }));
    expect(netPay.getByRole("link", { name: "Document" })).toHaveAttribute("href", expect.stringContaining("/underwriting/document-intelligence/"));
  });

  it("shows the missing information, the risks and the guideline references, and opens a passage", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Potential risks" });
    expect(screen.getByText("Page 3 of the August 2026 bank statement")).toBeInTheDocument();
    expect(screen.getByText("The funds to close are not yet documented.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Guideline passage" })[0]);
    expect(await screen.findByText(/Overtime and bonus income may be counted when the borrower/)).toBeInTheDocument();
  });

  it("lists the six suggested conditions, none reviewed, with the sign-off bar under them", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Suggested conditions" });
    expect(screen.getAllByTestId(/^condition-uwc-/)).toHaveLength(6);
    expect(screen.getAllByText("Not reviewed")).toHaveLength(6);
    expect(screen.getByRole("heading", { name: "Sign off review" })).toBeInTheDocument();
    expect(screen.getByText("Records a review. Not a decision.")).toBeInTheDocument();
    expect(screen.getByText(/6 suggested conditions have not been reviewed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign off review" })).toBeDisabled();
  });

  it("accepts a condition, rejects one with a reason, edits one, and adds one, keeping what the agents wrote", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Suggested conditions" });

    fireEvent.click(screen.getByRole("button", { name: "Accept condition 1" }));
    await waitFor(() => expect(condition(1).getByText("Accepted")).toBeInTheDocument());
    expect(screen.getByText(/5 suggested conditions have not been reviewed/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reject condition 6" }));
    await screen.findByRole("dialog");
    reason("not required for this file");
    fireEvent.click(screen.getByRole("button", { name: "Reject condition" }));
    await waitFor(() => expect(condition(6).getByText("Rejected")).toBeInTheDocument());
    expect(condition(6).getByText("Reason: not required for this file")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^condition-uwc-/)).toHaveLength(6); // still listed

    fireEvent.click(screen.getByRole("button", { name: "Edit condition 3" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Condition text"), { target: { value: "Provide the two newest pay stubs." } });
    reason("Shorter ask");
    fireEvent.click(screen.getByRole("button", { name: "Save edit" }));
    await waitFor(() => expect(condition(3).getByText("Edited")).toBeInTheDocument());
    expect(condition(3).getByText("Provide the two newest pay stubs.")).toBeInTheDocument();
    expect(condition(3).getByText(/Provide pay stubs that cover the full 30-day period/).textContent).toContain("Written by the agents:");

    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "Provide the gift letter." } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add condition" }));
    await waitFor(() => expect(screen.getAllByTestId(/^condition-uwc-/)).toHaveLength(7));
    expect(condition(7).getByText("Added by a reviewer")).toBeInTheDocument();
  });

  it("signs off only once every condition has a decision, then says who signed and when", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Sign off review" });
    const signOffButton = () => screen.getByRole("button", { name: "Sign off review" });
    for (let n = 1; n <= 5; n++) {
      fireEvent.click(screen.getByRole("button", { name: `Accept condition ${n}` }));
      await waitFor(() => expect(condition(n).getByText("Accepted")).toBeInTheDocument());
      expect(signOffButton()).toBeDisabled(); // one is still undecided
    }
    expect(screen.getByText(/1 suggested condition has not been reviewed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reject condition 6" }));
    await screen.findByRole("dialog");
    reason("not required for this file");
    fireEvent.click(screen.getByRole("button", { name: "Reject condition" }));
    await waitFor(() => expect(condition(6).getByText("Rejected")).toBeInTheDocument());
    await waitFor(() => expect(signOffButton()).toBeEnabled());
    expect(screen.queryByText(/have not been reviewed/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "Reviewed the file" } });
    fireEvent.click(signOffButton());
    expect(await screen.findByText("Review recorded.")).toBeInTheDocument();
    expect(screen.getByText("Review signed off")).toBeInTheDocument();
    expect(await screen.findByText(/Review signed off by/)).toHaveTextContent(/demo\.reviewer on \d{1,2} \w{3} \d{4}, version 1\./);
    const earlier = await screen.findByRole("list", { name: "Sign-offs" });
    expect(within(earlier).getByText(/demo\.reviewer · .* · version 1 · Reviewed the file/)).toBeInTheDocument();
  });

  it("a change after the sign-off puts the report back in review and keeps the sign-off", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Sign off review" });
    for (let n = 1; n <= 6; n++) {
      fireEvent.click(screen.getByRole("button", { name: `Accept condition ${n}` }));
      await waitFor(() => expect(condition(n).getByText("Accepted")).toBeInTheDocument());
    }
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    await screen.findByText("Review signed off");
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "Provide the gift letter." } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add condition" }));
    expect(await screen.findByText(/The report changed after the last sign-off/)).toBeInTheDocument();
    expect(screen.getByText("In review")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Sign-offs" })).toBeInTheDocument();
  });
});

describe("UnderwritingCopilotWorkspace when the Critic failed", () => {
  beforeEach(() => finishEarlierRun({ criticFails: true }));

  it("shows the Critic failed with Re-run, and says the report has not been checked", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Case snapshot" });
    const critic = within(screen.getByTestId("agent-critic"));
    expect(critic.getByText("Failed")).toBeInTheDocument();
    expect(critic.getByRole("button", { name: "Re-run the Critic" })).toBeEnabled();
    expect(screen.getByText(/The Critic's check is not available/)).toBeInTheDocument();
    expect(within(screen.getByTestId("agent-researcher")).getByText("Done")).toBeInTheDocument(); // the others are untouched
  });

  it("re-runs the Critic alone, and the notice goes when it is done", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Case snapshot" });
    fireEvent.click(screen.getByRole("button", { name: "Re-run the Critic" }));
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled(); // not while an agent is running
    await waitFor(() => expect(within(screen.getByTestId("agent-critic")).getByText("Done")).toBeInTheDocument(), { timeout: 6000 });
    expect(within(screen.getByTestId("agent-critic")).getByText("Attempt 2")).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Case snapshot" });
    expect(screen.queryByText(/The Critic's check is not available/)).not.toBeInTheDocument();
  }, 15000);
});

describe("UnderwritingCopilotWorkspace during a run", () => {
  it("shows the agents working and the report once they are done, with Run disabled in between", async () => {
    renderScreen();
    await screen.findByText(/No underwriting report yet/);
    fireEvent.click(screen.getByRole("button", { name: "Run copilot" }));
    expect(await screen.findByRole("list", { name: "Agent progress" })).toBeInTheDocument();
    expect(screen.getByText("Writing the report")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run/ })).toBeDisabled();
    expect(screen.queryByRole("heading", { name: "Findings" })).not.toBeInTheDocument();
    await screen.findByRole("heading", { name: "Findings" }, { timeout: 9000 });
    expect(screen.queryByText("Writing the report")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
    expect(within(screen.getByTestId("agent-critic")).getByText("Failed")).toBeInTheDocument(); // the demo's first run
  }, 20000);
});

describe("UnderwritingCopilotWorkspace for a case the agents cannot read", () => {
  it("says so, with Try again, and stays out of the way", async () => {
    renderScreen(mockCases.filter((c) => c.id === ANGELA_CASE_ID));
    fireEvent.click(await screen.findByRole("button", { name: "Run copilot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("There is nothing for the agents to work from on this case yet.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Agent progress" })).not.toBeInTheDocument();
  });
});
