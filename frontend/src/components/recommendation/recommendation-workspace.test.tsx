import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore, runCopilotMock } from "@/mocks/store";
import { RecommendationWorkspace } from "./recommendation-workspace";

beforeEach(() => resetMockStore());

const angela = mockCases.filter((c) => c.id === ANGELA_CASE_ID);

/** A run that finished earlier. A run started at time 0 is long over by now. The first run of a case has the demo's failed Critic. */
const finishEarlierRun = ({ criticFails }: { criticFails: boolean }) => {
  runCopilotMock("lm", ANGELA_CASE_ID, 0);
  if (!criticFails) runCopilotMock("lm", ANGELA_CASE_ID, 0);
};

const renderScreen = (cases = angela) => render(<RecommendationWorkspace cases={cases} />);
const card = (key: string) => within(screen.getByTestId(`option-${key}`));
const expand = (title: string) => fireEvent.click(screen.getByRole("button", { name: `Show conditions for ${title}` }));

describe("RecommendationWorkspace before a run", () => {
  it("says nothing has been run and offers Run recommendation, with no banner, figures or waterfall", async () => {
    renderScreen();
    expect(await screen.findByText(/No recommendation yet for Angela Whitfield — hardship/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run recommendation" })).toBeEnabled();
    expect(screen.queryByTestId("rule-set-banner")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Waterfall" })).not.toBeInTheDocument();
  });
});

describe("RecommendationWorkspace with an earlier run", () => {
  beforeEach(() => finishEarlierRun({ criticFails: false }));

  it("opens with the illustrative banner for Sample Investor A version 1", async () => {
    renderScreen();
    const banner = within(await screen.findByTestId("rule-set-banner"));
    expect(banner.getByText("Illustrative - Sample Investor A v1")).toBeInTheDocument();
    expect(banner.getByText("Illustrative: not an actual investor's requirements.")).toBeInTheDocument();
  });

  it("shows the lender's view first: foreclosure loss 16,310.00, modification expected cost 13,893.00, advantage 2,417.00", async () => {
    renderScreen();
    await screen.findByTestId("lender-advantage");
    expect(within(screen.getByTestId("lender-foreclosure_loss")).getByText("16,310.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-modification_cost")).getByText("13,893.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-advantage")).getByText("2,417.00")).toBeInTheDocument();
    // the lender view comes before the waterfall on the page
    const lender = screen.getByRole("heading", { name: "Lender view", level: 2 });
    const waterfall = screen.getByRole("heading", { name: "Waterfall" });
    expect(lender.compareDocumentPosition(waterfall) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the working of the foreclosure loss", async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Show working for foreclosure loss" }));
    expect(await screen.findByText(/^217,560\.00 - 201,250\.00 =/)).toBeInTheDocument();
  });

  it("shows the waterfall in order: repayment plan, forbearance and payment deferral not met, loan modification met, short sale and deed-in-lieu not reached", async () => {
    renderScreen();
    await screen.findByTestId("option-repayment_plan");
    const statuses = ["repayment_plan", "forbearance", "payment_deferral", "loan_modification", "short_sale_deed_in_lieu"].map((k) =>
      screen.getByTestId(`option-${k}`).getAttribute("data-status"),
    );
    expect(statuses).toEqual(["not_met", "not_met", "not_met", "met", "not_reached"]);
    expect(card("repayment_plan").getByText("Not met")).toBeInTheDocument();
    expect(card("loan_modification").getByText("Met")).toBeInTheDocument();
    expect(card("short_sale_deed_in_lieu").getByText("Not reached")).toBeInTheDocument();
  });

  it("expands a card to its conditions with the values used and opens the cited passage", async () => {
    renderScreen();
    await screen.findByTestId("option-repayment_plan");
    expand("Repayment plan");
    const surplus = within(screen.getByTestId("condition-repayment_plan.surplus"));
    expect(surplus.getByText("Needed:").nextSibling).toHaveTextContent("860.00");
    fireEvent.click(screen.getByRole("button", { name: "Open the cited passage for Hardship resolved (confirmed)" }));
    expect(await screen.findByText("A repayment plan is considered only when the borrower's hardship has been confirmed as resolved.")).toBeInTheDocument();
    expect(screen.getAllByText("Sample Investor A guide").length).toBeGreaterThanOrEqual(1); // the passage panel names its document
    expect(screen.getAllByText("Illustrative: not an actual investor's requirements.").length).toBeGreaterThanOrEqual(2); // the banner and the passage
  });

  it("shows the agents done and the report: lender view, the borrower's situation, missing information, compliance points, items for review", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Report" });
    for (const agent of ["researcher", "writer", "critic"]) expect(within(screen.getByTestId(`agent-${agent}`)).getByText("Done")).toBeInTheDocument();
    expect(screen.getByText(/an expected cost of 13,893\.00, which is 2,417\.00 lower/)).toBeInTheDocument();
    expect(screen.getByText(/Income fell by 25% from July 2026/)).toBeInTheDocument();
    expect(screen.getByText("The August 2026 bank statement")).toBeInTheDocument();
    expect(screen.getByText(/12 CFR 1024\.41\(b\)/)).toBeInTheDocument();
    expect(screen.getByText("Confirm the hardship duration and intent before relying on the waterfall.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing here is a decision/)).toBeInTheDocument();
  });

  it("has the same sign-off bar, and records the review as the specialist's, not a decision", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Sign off review" });
    expect(screen.getByText("Records a review. Not a decision.")).toBeInTheDocument();
    expect(screen.queryByText(/suggested conditions? ha(s|ve) not been reviewed/)).not.toBeInTheDocument(); // there are no suggested conditions here
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "Add a note to request the August statement" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    expect(await screen.findByText("Review recorded.")).toBeInTheDocument();
    expect(screen.getByText("Review signed off")).toBeInTheDocument();
    expect(within(await screen.findByRole("list", { name: "Sign-offs" })).getByText(/demo\.reviewer · .* · version 1 · Add a note to request the August statement/)).toBeInTheDocument();
  });

  it("adds a note on a part of the report, and on the waterfall, beside what the agents wrote", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Compliance points" });
    const complianceBefore = screen.getByRole("heading", { name: "Compliance points" }).closest("section")!.textContent;

    fireEvent.click(screen.getByRole("button", { name: "Add a note on Compliance points" }));
    fireEvent.change(screen.getByLabelText("Note on Compliance points"), { target: { value: "  Check the 120-day date with the servicer  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    const notes = await screen.findByRole("list", { name: "Notes on Compliance points" });
    expect(within(notes).getByText("Check the 120-day date with the servicer")).toBeInTheDocument();
    expect(within(notes).getByText(/Reviewer note · demo\.reviewer · /)).toBeInTheDocument();
    // the box closes, and the agents' own text is unchanged
    expect(screen.queryByLabelText("Note on Compliance points")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Compliance points" }).closest("section")!.textContent).toContain(complianceBefore!.replace("Add note", ""));

    fireEvent.click(screen.getByRole("button", { name: "Add a note on Waterfall" }));
    fireEvent.change(screen.getByLabelText("Note on Waterfall"), { target: { value: "Modification looks right to me" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByRole("list", { name: "Notes on Waterfall" })).toBeInTheDocument();
  });

  it("a note after the sign-off puts the report back in review and keeps the sign-off", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Sign off review" });
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    await screen.findByText("Review signed off");
    fireEvent.click(screen.getByRole("button", { name: "Add a note on Lender view" }));
    fireEvent.change(screen.getByLabelText("Note on Lender view"), { target: { value: "Second look" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText(/The report changed after the last sign-off/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Sign-offs" })).toBeInTheDocument();
  });

  it("will not save a blank note, and Cancel throws the box away", async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Add a note on Missing information" }));
    expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Note on Missing information"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Note on Missing information")).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Notes on Missing information" })).not.toBeInTheDocument();
  });

  it("overrides a condition with a reason: the statuses recompute, the rules' own status stays visible, and the report says it predates the override", async () => {
    renderScreen();
    await screen.findByTestId("option-loan_modification");
    expand("Loan modification");
    fireEvent.click(screen.getByRole("button", { name: "Override Intent to keep the home (confirmed)" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "needs_confirmation" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "The borrower has not yet confirmed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save override" }));

    await waitFor(() => expect(screen.getByTestId("option-loan_modification")).toHaveAttribute("data-status", "needs_confirmation"));
    expect(card("loan_modification").getAllByText("Needs confirmation").length).toBeGreaterThanOrEqual(1); // on the card and on the condition
    expect(card("loan_modification").getByText("Overridden")).toBeInTheDocument();
    const row = within(screen.getByTestId("condition-loan_modification.intent"));
    expect(row.getByText(/The rules found Met; now Needs confirmation\./)).toBeInTheDocument();
    expect(row.getByText(/Reason: The borrower has not yet confirmed/)).toBeInTheDocument();
    // an option that is not met no longer stops the waterfall: the last two are reached, with no rules of their own
    expect(screen.getByTestId("option-short_sale_deed_in_lieu")).toHaveAttribute("data-status", "not_evaluable");
    expect(screen.getByText(/The report text below was written before them/)).toBeInTheDocument();
  });

  it("an override that makes an earlier option met stops the waterfall there", async () => {
    renderScreen();
    await screen.findByTestId("option-forbearance");
    expand("Forbearance");
    fireEvent.click(screen.getByRole("button", { name: "Override Hardship temporary (confirmed)" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "met" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer confirmed the hours are coming back" } });
    fireEvent.click(screen.getByRole("button", { name: "Save override" }));
    await waitFor(() => expect(screen.getByTestId("option-forbearance")).toHaveAttribute("data-status", "met"));
    expect(screen.getByTestId("option-loan_modification")).toHaveAttribute("data-status", "not_reached");
    expect(screen.getByTestId("option-short_sale_deed_in_lieu")).toHaveAttribute("data-status", "not_reached");
  });
});

describe("RecommendationWorkspace when the Critic failed", () => {
  beforeEach(() => finishEarlierRun({ criticFails: true }));

  it("shows the Critic failed, with Re-run, and says the report has not been checked; the waterfall is untouched", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Report" });
    expect(within(screen.getByTestId("agent-critic")).getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/The Critic's check is not available/)).toBeInTheDocument();
    expect(screen.getByTestId("option-loan_modification")).toHaveAttribute("data-status", "met");
  });

  it("re-runs the Critic alone and the notice goes", async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Re-run the Critic" }));
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByTestId("lender-advantage")).toBeInTheDocument(); // the rules' results stay on screen
    await waitFor(() => expect(within(screen.getByTestId("agent-critic")).getByText("Done")).toBeInTheDocument(), { timeout: 6000 });
    await screen.findByRole("heading", { name: "Report" });
    expect(screen.queryByText(/The Critic's check is not available/)).not.toBeInTheDocument();
  }, 15000);
});

describe("RecommendationWorkspace during a run", () => {
  it("shows the lender view and the waterfall at once, because the rules are code, then the report when the agents are done", async () => {
    renderScreen();
    await screen.findByText(/No recommendation yet/);
    fireEvent.click(screen.getByRole("button", { name: "Run recommendation" }));
    expect(await screen.findByTestId("lender-advantage")).toBeInTheDocument();
    expect(screen.getByTestId("option-loan_modification")).toHaveAttribute("data-status", "met");
    expect(screen.getByText("Writing the report")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run/ })).toBeDisabled();
    expect(screen.queryByRole("heading", { name: "Report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign off review" })).not.toBeInTheDocument();
    await screen.findByRole("heading", { name: "Report" }, { timeout: 9000 });
    expect(screen.getByRole("heading", { name: "Sign off review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  }, 20000);
});

describe("RecommendationWorkspace for a case the agents cannot read", () => {
  it("says so, with Try again", async () => {
    renderScreen(mockCases.filter((c) => c.id === DANIEL_CASE_ID));
    fireEvent.click(await screen.findByRole("button", { name: "Run recommendation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("There is nothing for the agents to work from on this case yet.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
