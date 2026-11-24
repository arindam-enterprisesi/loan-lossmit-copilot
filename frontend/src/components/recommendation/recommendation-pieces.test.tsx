import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ANGELA_INPUTS, buildLenderView, evaluateAngela, overrideCondition, startRun } from "@/mocks/copilot";
import { ANGELA_CASE_ID } from "@/mocks/data";
import { LenderView } from "./lender-view";
import { RuleSetBanner } from "./rule-set-banner";
import { Waterfall } from "./waterfall";

describe("RuleSetBanner", () => {
  it("says 'Illustrative - Sample Investor A v1' and that these are not an actual investor's requirements", () => {
    render(<RuleSetBanner ruleSet={{ name: "Sample Investor A", version: "1", label: "illustrative", banner: "Illustrative: not an actual investor's requirements." }} />);
    const banner = within(screen.getByTestId("rule-set-banner"));
    expect(banner.getByText("Illustrative - Sample Investor A v1")).toBeInTheDocument();
    expect(banner.getByText("Illustrative: not an actual investor's requirements.")).toBeInTheDocument();
    expect(banner.getByText("Illustrative")).toBeInTheDocument(); // the chip
  });

  it("calls a rule set Authoritative only when it is, with no illustrative warning", () => {
    render(<RuleSetBanner ruleSet={{ name: "Investor B", version: "3", label: "authoritative", banner: null }} />);
    expect(screen.getByText("Authoritative - Investor B v3")).toBeInTheDocument();
    expect(screen.queryByText(/not an actual investor/)).not.toBeInTheDocument();
  });
});

describe("LenderView", () => {
  const view = buildLenderView();

  it("leads with the foreclosure loss, the modification's expected cost and the advantage", () => {
    render(<LenderView view={view} />);
    expect(within(screen.getByTestId("lender-foreclosure_loss")).getByText("16,310.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-foreclosure_loss")).getByText("Foreclosure loss")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-modification_cost")).getByText("13,893.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-modification_cost")).getByText("Modification expected cost")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-advantage")).getByText("2,417.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("lender-advantage")).getByText("Advantage of the modification")).toBeInTheDocument();
  });

  it("shows the working of the foreclosure loss: the claim, the net recovery, then the loss", async () => {
    render(<LenderView view={view} />);
    fireEvent.click(screen.getByRole("button", { name: "Show working for foreclosure loss" }));
    expect(await screen.findByText(/^212,400\.00 \+ 5,160\.00 =/)).toBeInTheDocument();
    expect(screen.getByText(/^265,000\.00 - 15% \(39,750\.00\) - 24,000\.00 =/)).toBeInTheDocument();
    expect(screen.getByText(/^217,560\.00 - 201,250\.00 =/)).toBeInTheDocument();
    expect(screen.getByText("201,250.00")).toBeInTheDocument(); // a result, in bold
    expect(screen.getByText("Calculated in code, with no AI call.")).toBeInTheDocument();
  });

  it("shows the working of the modification cost, and of the advantage", async () => {
    const { unmount } = render(<LenderView view={view} />);
    fireEvent.click(screen.getByRole("button", { name: "Show working for modification expected cost" }));
    expect(await screen.findByText(/^250\.00 x 36 =/)).toBeInTheDocument();
    expect(screen.getByText(/^16,310\.00 x 30% =/)).toBeInTheDocument();
    expect(screen.getByText(/^9,000\.00 \+ 4,893\.00 =/)).toBeInTheDocument();
    unmount();
    render(<LenderView view={view} />);
    fireEvent.click(screen.getByRole("button", { name: "Show working for advantage of the modification" }));
    expect(await screen.findByText(/^16,310\.00 - 13,893\.00 =/)).toBeInTheDocument();
  });

  it("lists the illustrative settings, and says final terms are never worked out here", () => {
    render(<LenderView view={view} />);
    const settings = within(screen.getByText("Settings used (illustrative)").closest("details") as HTMLElement);
    expect(settings.getByText("Property value").nextSibling).toHaveTextContent("265,000.00");
    expect(settings.getByText("Liquidation discount").nextSibling).toHaveTextContent("15%");
    expect(settings.getByText("Review horizon").nextSibling).toHaveTextContent("36 months");
    expect(settings.getByText("Chance of re-default after a modification").nextSibling).toHaveTextContent("30%");
    expect(screen.getByText(/Final terms are never computed here/)).toBeInTheDocument();
  });

  it("shows no working button for a figure the backend sent no working for", () => {
    render(<LenderView view={{ ...view, figures: [] }} />);
    expect(screen.queryByRole("button", { name: /Show working/ })).not.toBeInTheDocument();
    expect(screen.getByText("16,310.00")).toBeInTheDocument();
  });
});

describe("Waterfall", () => {
  const setup = (options = evaluateAngela(ANGELA_INPUTS), over: { onOverride?: ReturnType<typeof vi.fn>; onOpenPassage?: ReturnType<typeof vi.fn> } = {}) => {
    const onOverride = over.onOverride ?? vi.fn().mockResolvedValue(undefined);
    const onOpenPassage = over.onOpenPassage ?? vi.fn();
    render(<Waterfall options={options} onOverride={onOverride} onOpenPassage={onOpenPassage} />);
    return { onOverride, onOpenPassage };
  };
  const expand = (title: string) => fireEvent.click(screen.getByRole("button", { name: `Show conditions for ${title}` }));

  it("shows the options in order, with Loan modification met and the rest not met, and the last two together and not reached", () => {
    setup();
    const cards = within(screen.getByRole("list", { name: "Options in waterfall order" })).getAllByRole("listitem", { hidden: false }).filter((li) => li.hasAttribute("data-status"));
    expect(cards.map((c) => [c.getAttribute("data-testid"), c.getAttribute("data-status")])).toEqual([
      ["option-repayment_plan", "not_met"],
      ["option-forbearance", "not_met"],
      ["option-payment_deferral", "not_met"],
      ["option-loan_modification", "met"],
      ["option-short_sale_deed_in_lieu", "not_reached"],
    ]);
    expect(within(screen.getByTestId("option-repayment_plan")).getByText("Not met")).toBeInTheDocument();
    expect(within(screen.getByTestId("option-loan_modification")).getByText("Met")).toBeInTheDocument();
    const last = within(screen.getByTestId("option-short_sale_deed_in_lieu"));
    expect(last.getByText("Short sale and deed-in-lieu")).toBeInTheDocument();
    expect(last.getByText("Not reached")).toBeInTheDocument();
    expect(last.getByText("5–6")).toBeInTheDocument();
  });

  it("says the rules stop at the first option whose conditions are met, and that Met is not a decision", () => {
    setup();
    expect(screen.getByText(/stop at the first option whose conditions are met/)).toBeInTheDocument();
    expect(screen.getByText(/"Met" says only that an option's conditions are met\. It is not a decision\./)).toBeInTheDocument();
  });

  it("keeps the conditions folded until a card is opened, then shows them and can fold them again", () => {
    setup();
    expect(screen.queryByTestId("condition-repayment_plan.surplus")).not.toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Show conditions for Repayment plan" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Hide conditions for Repayment plan" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("condition-repayment_plan.surplus")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide conditions for Repayment plan" }));
    expect(screen.queryByTestId("condition-repayment_plan.surplus")).not.toBeInTheDocument();
  });

  it("shows each condition's status, its rule, and the values it used", () => {
    setup();
    expand("Repayment plan");
    const surplus = within(screen.getByTestId("condition-repayment_plan.surplus"));
    expect(surplus.getByText("Monthly surplus at least arrears / 6")).toBeInTheDocument();
    expect(surplus.getByText("Not met")).toBeInTheDocument();
    expect(surplus.getByText("surplus >= arrears / 6")).toBeInTheDocument();
    expect(surplus.getByText("Monthly surplus:").nextSibling).toHaveTextContent("-70.00");
    expect(surplus.getByText("Arrears:").nextSibling).toHaveTextContent("5,160.00");
    expect(surplus.getByText("Needed:").nextSibling).toHaveTextContent("860.00");
  });

  it("shows the modification's target payment against the contractual payment", () => {
    setup();
    expand("Loan modification");
    const target = within(screen.getByTestId("condition-loan_modification.target_payment"));
    expect(target.getByText("Met")).toBeInTheDocument();
    expect(target.getByText("Documented gross monthly income:").nextSibling).toHaveTextContent("4,200.00");
    expect(target.getByText("Target payment:").nextSibling).toHaveTextContent("1,470.00");
    expect(target.getByText("Contractual payment:").nextSibling).toHaveTextContent("1,720.00");
    const duration = within(screen.getByTestId("condition-loan_modification.hardship_long_term"));
    expect(duration.getByText("Hardship duration:").nextSibling).toHaveTextContent("Unknown");
  });

  it("opens the passage a rule cites", () => {
    const { onOpenPassage } = setup();
    expand("Repayment plan");
    fireEvent.click(screen.getByRole("button", { name: "Open the cited passage for Monthly surplus at least arrears / 6" }));
    expect(onOpenPassage).toHaveBeenCalledWith("sample-investor-a-v1.repayment-plan.2");
  });

  it("shows both options of the shared card under their own names, and says a derived condition is not set by a person", () => {
    setup();
    expand("Short sale and deed-in-lieu");
    const card = within(screen.getByTestId("option-short_sale_deed_in_lieu"));
    expect(card.getByRole("heading", { name: "Short sale" })).toBeInTheDocument();
    expect(card.getByRole("heading", { name: "Deed-in-lieu" })).toBeInTheDocument();
    const derived = within(screen.getByTestId("condition-short_sale.reached"));
    expect(derived.getByText(/Follows from the options before it/)).toBeInTheDocument();
    expect(derived.queryByRole("button", { name: /^Override/ })).not.toBeInTheDocument();
    expect(within(screen.getByTestId("condition-short_sale.rules")).getByRole("button", { name: /^Override/ })).toBeInTheDocument();
  });

  it("overrides a condition with a status and a reason, and will not accept the status already shown", async () => {
    const { onOverride } = setup();
    expand("Loan modification");
    fireEvent.click(screen.getByRole("button", { name: "Override Target payment of 35% of documented gross monthly income is below the contractual payment" }));
    await screen.findByRole("dialog");
    expect(screen.getByText(/The rules found: Met\./)).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Save override" });
    expect(screen.getByLabelText("Status")).toHaveValue("met");
    expect(screen.getByText("Pick a different status from the one shown now.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Income documents are being re-checked" } });
    expect(confirm).toBeDisabled(); // same status as now
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "not_met" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(onOverride).toHaveBeenCalledWith("loan_modification.target_payment", { status: "not_met", reason: "Income documents are being re-checked" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("offers every status except 'not reached' in the override window", async () => {
    setup();
    expand("Forbearance");
    fireEvent.click(screen.getByRole("button", { name: "Override Hardship temporary (confirmed)" }));
    await screen.findByRole("dialog");
    const options = within(screen.getByLabelText("Status")).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Met", "Not met", "Needs confirmation", "Not evaluable"]);
  });

  it("keeps the window open with the message and what was typed when the override fails", async () => {
    const onOverride = vi.fn().mockRejectedValue(new Error("A reason is required."));
    setup(undefined, { onOverride });
    expand("Forbearance");
    fireEvent.click(screen.getByRole("button", { name: "Override Hardship temporary (confirmed)" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "met" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "keep me" } });
    fireEvent.click(screen.getByRole("button", { name: "Save override" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("A reason is required.");
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("keep me");
  });

  it("shows an overridden condition with what the rules found beside it, who, when and why, and marks the card", () => {
    const run = startRun("lm", ANGELA_CASE_ID, 0, false);
    overrideCondition(run, "loan_modification.target_payment", { status: "not_met", reason: "Income documents are being re-checked" }, Date.parse("2026-11-24T10:00:00Z"));
    setup(run.options);
    const card = within(screen.getByTestId("option-loan_modification"));
    expect(card.getByText("Overridden")).toBeInTheDocument();
    expect(screen.getByTestId("option-loan_modification")).toHaveAttribute("data-status", "not_met");
    expand("Loan modification");
    const row = within(screen.getByTestId("condition-loan_modification.target_payment"));
    expect(row.getByText(/The rules found Met; now Not met\./)).toBeInTheDocument();
    expect(row.getByText(/By demo\.reviewer on 24 Nov 2026\. Reason: Income documents are being re-checked/)).toBeInTheDocument();
    // the waterfall now reaches the last two, which have no rules of their own
    expect(screen.getByTestId("option-short_sale_deed_in_lieu")).toHaveAttribute("data-status", "not_evaluable");
  });
});
