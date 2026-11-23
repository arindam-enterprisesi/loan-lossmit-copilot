import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ANGELA_CASE_ID } from "@/mocks/data";
import { buildAngelaHardship } from "@/mocks/hardship";
import { ChecksTable } from "./checks-table";

const a = buildAngelaHardship("2026-11-20T09:00:00.000Z");
const renderTable = (checks = a.checks) =>
  render(<ChecksTable checks={checks} caseId={ANGELA_CASE_ID} pillarSlug="loss-mitigation" />);

describe("ChecksTable", () => {
  it("shows a row per check with its label and what was found", () => {
    renderTable();
    expect(screen.getAllByRole("row")).toHaveLength(1 + a.checks.length); // header + checks
    const row = within(screen.getByTestId("check-hours_vs_pay"));
    expect(row.getByText("Hours cut against the change in pay")).toBeInTheDocument();
    expect(row.getByText(/A cut from 40 to 30 hours is a quarter fewer hours/)).toBeInTheDocument();
  });

  it("puts the stated value and the documented value side by side, each with its source", () => {
    renderTable();
    const row = within(screen.getByTestId("check-hours_vs_pay"));
    expect(row.getByText("Hours cut from 40 to 30 a week")).toBeInTheDocument();
    expect(row.getByText(/Pay fell from 2,800\.00 to 2,100\.00 a half-month \(25\.00% lower\)/)).toBeInTheDocument();
    expect(row.getByText(/Hardship letter/)).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/loss-mitigation\/document-intake\/.*\/d2000000-0000-4000-8000-000000000002$/),
    );
    expect(row.getByText(/Page 1, line p1-L6/)).toBeInTheDocument();
    expect(row.getByText("Pay stubs")).toBeInTheDocument();
  });

  it("marks the checks that agree as Consistent and the spending check as Flagged", () => {
    renderTable();
    expect(screen.getAllByText("Consistent")).toHaveLength(5);
    const spending = within(screen.getByTestId("check-spending"));
    expect(spending.getByText("Flagged")).toBeInTheDocument();
    expect(spending.getByText("3,420.00 a month")).toBeInTheDocument();
    expect(spending.getByText("3,630.00 a month")).toBeInTheDocument();
    expect(spending.getByText("Observed 'other' spending 410.00 against 200.00 stated — ask the borrower")).toBeInTheDocument();
  });

  it("highlights the flagged row only", () => {
    renderTable();
    expect(screen.getByTestId("check-spending").className).toContain("bg-gold/10");
    expect(screen.getByTestId("check-reason").className).not.toContain("bg-gold/10");
  });

  it("shows a source with no document as plain text", () => {
    const checks = structuredClone(a.checks);
    delete checks[0].stated.source.document_id;
    checks[0].stated.source.label = "The borrower's call";
    renderTable(checks);
    expect(within(screen.getByTestId("check-hours_vs_pay")).queryByRole("link", { name: "The borrower's call" })).not.toBeInTheDocument();
    expect(screen.getByText(/The borrower's call/)).toBeInTheDocument();
  });
});
