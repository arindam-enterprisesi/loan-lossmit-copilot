import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildDanielAssets, DANIEL_SCENARIO, type AssetRun } from "@/mocks/assets";
import { DANIEL_CASE_ID } from "@/mocks/data";
import { AssetFlags } from "./asset-flags";

const RUN: AssetRun = { scenario: DANIEL_SCENARIO, candidate_monthly: "5980.00", overtime_monthly: "444.41" };
const flags = () => buildDanielAssets(RUN, "2026-11-23T09:00:00.000Z").flags;

describe("AssetFlags", () => {
  it("lists each flag with its code and the backend's sentence", () => {
    render(<AssetFlags flags={flags()} caseId={DANIEL_CASE_ID} pillarSlug="underwriting" />);
    const large = within(screen.getByTestId("flag-AL-W101"));
    expect(large.getByText("AL-W101")).toBeInTheDocument();
    expect(large.getByText("Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules.")).toBeInTheDocument();
    expect(screen.getByText("Documented assets of 9,226.32 are 27,273.68 short of the 36,500.00 needed to close.")).toBeInTheDocument();
    expect(screen.getByText("DTI 44.70% is above the review level of 43%.")).toBeInTheDocument();
  });

  it("shows the working and links the evidence to the statement line", () => {
    render(<AssetFlags flags={flags()} caseId={DANIEL_CASE_ID} pillarSlug="underwriting" />);
    expect(screen.getByText("36,500.00 − 9,226.32 = 27,273.68")).toBeInTheDocument();
    const link = within(screen.getByTestId("flag-AL-W101")).getByRole("link");
    expect(link).toHaveAttribute("href", expect.stringContaining(`/underwriting/document-intelligence/${DANIEL_CASE_ID}/`));
    expect(link).toHaveTextContent("Bank statement, Sep 2026, account ending 6032");
  });

  it("marks a flag as resolved once a person dealt with it", () => {
    const resolved = flags().map((f) => (f.code === "AL-W101" ? { ...f, status: "resolved" } : f));
    render(<AssetFlags flags={resolved} caseId={DANIEL_CASE_ID} pillarSlug="underwriting" />);
    expect(within(screen.getByTestId("flag-AL-W101")).getByText("Resolved")).toBeInTheDocument();
    expect(within(screen.getByTestId("flag-AL-W105")).queryByText("Resolved")).not.toBeInTheDocument();
  });

  it("says so when nothing is flagged", () => {
    render(<AssetFlags flags={[]} caseId={DANIEL_CASE_ID} pillarSlug="loss-mitigation" />);
    expect(screen.getByText("Nothing flagged.")).toBeInTheDocument();
  });
});
