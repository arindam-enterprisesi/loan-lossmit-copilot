import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildDanielAssets, DANIEL_SCENARIO, type AssetRun } from "@/mocks/assets";
import { AssetSummary } from "./asset-summary";

const RUN: AssetRun = { scenario: DANIEL_SCENARIO, candidate_monthly: "5980.00", overtime_monthly: "444.41" };
const analysis = (run: AssetRun = RUN) => buildDanielAssets(run, "2026-11-23T09:00:00.000Z");
const renderStrip = (a = analysis()) => render(<AssetSummary analysis={a} pillarSlug="underwriting" />);
const card = (id: string) => within(screen.getByTestId(`figure-${id}`));

describe("AssetSummary: the strip", () => {
  it("shows the five figures from Feature Design 3.8", () => {
    renderStrip();
    expect(card("documented_assets").getByText("9,226.32")).toBeInTheDocument();
    expect(card("funds_to_close").getByText("36,500.00")).toBeInTheDocument();
    expect(card("front_end_ratio").getByText("33.11%")).toBeInTheDocument();
    expect(card("dti").getByText("44.70%")).toBeInTheDocument();
    expect(card("ltv").getByText("90.00%")).toBeInTheDocument();
  });

  it("shows the shortfall under funds to close, with its own working", () => {
    renderStrip();
    expect(card("funds_shortfall").getByText("27,273.68")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Shortfall" }));
    expect(screen.getByText(/36,500\.00 − 9,226\.32/)).toBeInTheDocument();
  });

  it("labels every figure as a candidate for the underwriter to review", () => {
    renderStrip();
    expect(screen.getAllByText("candidate - for underwriter review")).toHaveLength(5);
  });

  it("has Show working on every figure", () => {
    renderStrip();
    for (const name of ["Documented assets", "Funds to close", "Front-end ratio", "DTI", "LTV", "Shortfall"]) {
      expect(screen.getByRole("button", { name: `Show working for ${name}` })).toBeInTheDocument();
    }
  });

  it("opens DTI's working: 44.70% from the housing payment, the obligations and the income, with where they came from", async () => {
    renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Show working for DTI" }));
    expect(await screen.findByText(/\(1,980\.00 \+ 693\.00\) ÷ 5,980\.00 × 100/)).toBeInTheDocument();
    expect(screen.getByText("Read from")).toBeInTheDocument();
    expect(screen.getByText("Loan scenario (entered by hand)")).toBeInTheDocument();
    expect(screen.getByText("Candidate monthly income (income analysis)")).toBeInTheDocument();
  });

  it("links documented assets to the bank statement it was read from", async () => {
    renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Documented assets" }));
    const link = await screen.findByRole("link", { name: "Bank statement, Sep 2026, account ending 6032" });
    expect(link).toHaveAttribute("href", expect.stringContaining("/underwriting/document-intelligence/"));
  });

  it("marks DTI as above the review level while the flag is open", () => {
    renderStrip();
    expect(card("dti").getByText("Above the review level")).toBeInTheDocument();
    expect(card("ltv").queryByText("Above the review level")).not.toBeInTheDocument();
  });

  it("does not mark it once DTI is under the level", () => {
    renderStrip(analysis({ ...RUN, candidate_monthly: "9000.00" }));
    expect(card("dti").queryByText("Above the review level")).not.toBeInTheDocument();
  });

  it("shows a dash and says why when a figure could not be worked out, with no Show working", () => {
    renderStrip(analysis({ ...RUN, candidate_monthly: "0.00" }));
    expect(card("dti").getByText("—")).toBeInTheDocument();
    expect(card("dti").getByText("Cannot be worked out yet. See the flags below.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show working for DTI" })).not.toBeInTheDocument();
    expect(card("ltv").getByText("90.00%")).toBeInTheDocument(); // the others are unaffected
  });
});

describe("AssetSummary: other figures", () => {
  it("shows DTI at 41.61% if overtime were counted, as something to test and not a decision", () => {
    renderStrip();
    const other = within(screen.getByTestId("other-dti_with_overtime"));
    expect(other.getByText("DTI if overtime were counted")).toBeInTheDocument();
    expect(other.getByText("41.61%")).toBeInTheDocument();
    expect(other.getByText(/Whether it counts is a decision for a person/)).toBeInTheDocument();
  });

  it("opens the working for it", async () => {
    renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Show working for DTI if overtime were counted" }));
    expect(await screen.findByText(/\(1,980\.00 \+ 693\.00\) ÷ 6,424\.41 × 100/)).toBeInTheDocument();
  });

  it("is not shown when there is no what-if", () => {
    renderStrip(analysis({ ...RUN, overtime_monthly: null }));
    expect(screen.queryByLabelText("Other figures")).not.toBeInTheDocument();
  });
});
