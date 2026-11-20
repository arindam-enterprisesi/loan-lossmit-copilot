import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildDanielIncome, POSSIBLE_LABEL } from "@/mocks/income";
import { IncomeFlagCard } from "./income-flag-card";

const flag = () => buildDanielIncome("2026-11-20T09:00:00.000Z").flags[0];
const renderCard = (f = flag()) =>
  render(<IncomeFlagCard flag={f} caseId="11111111-1111-4111-8111-111111111111" pillarSlug="underwriting" />);

describe("IncomeFlagCard", () => {
  it("shows the flag's code and what was found", () => {
    renderCard();
    expect(screen.getByText("income.short_history")).toBeInTheDocument();
    expect(screen.getByText(/their documented history is under 24 months/)).toBeInTheDocument();
  });

  it("shows both values side by side, each with its source", () => {
    renderCard();
    const documented = within(screen.getByText("Documented history").closest("div")!);
    expect(documented.getByText("2026 only (pay period 19 of 26)")).toBeInTheDocument();
    expect(documented.getByRole("link", { name: /Pay stub, 27 Sep 2026/ })).toHaveAttribute(
      "href",
      expect.stringContaining("/underwriting/document-intelligence/"),
    );
    expect(documented.getByText(/Page 2, line p2-L7/)).toBeInTheDocument();
    const needed = within(screen.getByText("History needed to count it").closest("div")!);
    expect(needed.getByText("24 months or more")).toBeInTheDocument();
    expect(needed.getByText(/income-method@1 \(illustrative\)/)).toBeInTheDocument();
    expect(needed.queryByRole("link")).not.toBeInTheDocument(); // no document to open
  });

  it("marks the AI explanation as possible, never as a finding", () => {
    renderCard();
    const explanation = within(screen.getByRole("region", { name: "Suggested explanation" }));
    expect(explanation.getByText(POSSIBLE_LABEL)).toBeInTheDocument();
    expect(explanation.getByText(/may have started this year/)).toBeInTheDocument();
    expect(explanation.getByText("Final pay stub of 2025 showing year-to-date overtime and bonus")).toBeInTheDocument();
    expect(explanation.queryByText("unverified figure")).not.toBeInTheDocument();
  });

  it("flags an explanation whose figure did not match its inputs", () => {
    const f = flag();
    f.explanations[0].figures_verified = false;
    renderCard(f);
    expect(screen.getByText("unverified figure")).toBeInTheDocument();
  });

  it("shows a flag with no explanation without an explanation box", () => {
    const f = flag();
    f.explanations = [];
    renderCard(f);
    expect(screen.queryByRole("region", { name: "Suggested explanation" })).not.toBeInTheDocument();
  });
});
