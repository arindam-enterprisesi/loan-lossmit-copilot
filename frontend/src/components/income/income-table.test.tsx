import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildDanielIncome } from "@/mocks/income";
import { IncomeTable } from "./income-table";

const analysis = () => buildDanielIncome("2026-11-20T09:00:00.000Z");
const renderTable = (a = analysis()) => render(<IncomeTable analysis={a} pillarSlug="underwriting" />);

describe("IncomeTable", () => {
  it("shows each component with current period, year to date and monthly amounts", () => {
    renderTable();
    const base = within(screen.getByTestId("component-base_pay"));
    expect(base.getByText("Base pay (hourly)")).toBeInTheDocument();
    expect(base.getByText("2,760.00")).toBeInTheDocument();
    expect(base.getByText("52,440.00")).toBeInTheDocument();
    expect(base.getByText("5,980.00")).toBeInTheDocument();
    const overtime = within(screen.getByTestId("component-overtime"));
    expect(overtime.getByText("444.41")).toBeInTheDocument();
    expect(within(screen.getByTestId("component-bonus")).getByText("228.34")).toBeInTheDocument();
  });

  it("marks what is counted and gives the reason for what is left out", () => {
    renderTable();
    expect(within(screen.getByTestId("component-base_pay")).getByText("Counted")).toBeInTheDocument();
    const overtime = within(screen.getByTestId("component-overtime"));
    expect(overtime.getByText("Left out")).toBeInTheDocument();
    expect(overtime.getByText(/24 months are needed/)).toBeInTheDocument();
  });

  it("ends with the candidate monthly income, labelled as the brief requires", () => {
    renderTable();
    const row = within(screen.getByTestId("candidate-row"));
    expect(row.getByText("Candidate monthly income")).toBeInTheDocument();
    expect(row.getByText("candidate - qualifying income is determined by the underwriter")).toBeInTheDocument();
    expect(row.getByText("5,980.00")).toBeInTheDocument();
  });

  it("opens the working for one figure, with the formula and where it was read from", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Base pay (hourly), monthly" }));
    expect(screen.getByText(/34.50 × 80.00 hours × 26 periods ÷ 12/)).toBeInTheDocument();
    expect(screen.getByText("Read from")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Pay stub, 27 Sep 2026/ })[0]).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/underwriting\/document-intelligence\/11111111-.*\/d1000000-/),
    );
  });

  it("opens the working for the candidate total", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Candidate monthly income" }));
    expect(screen.getByText("Sum of the components counted")).toBeInTheDocument();
    expect(screen.getByText(/Left out: Overtime \(1.5x\) \(444.41\), Bonus \(228.34\)/)).toBeInTheDocument();
  });

  it("has a working drawer for every figure: 3 per component and the candidate total", () => {
    renderTable();
    expect(screen.getAllByRole("button", { name: /^Show working for/ })).toHaveLength(3 * 3 + 1);
  });

  it("has no Include or Exclude buttons when no one can decide", () => {
    renderTable();
    expect(screen.queryByRole("button", { name: /^(Include|Exclude) / })).not.toBeInTheDocument();
  });

  it("offers Exclude on what is counted and Include on what is left out", () => {
    render(<IncomeTable analysis={analysis()} pillarSlug="underwriting" onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Exclude Base pay (hourly)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Include Overtime (1.5x)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Include Bonus" })).toBeInTheDocument();
  });

  it("sends the component, the decision and the reason from the dialog", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<IncomeTable analysis={analysis()} pillarSlug="underwriting" onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Include Overtime (1.5x)" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer letter" } });
    fireEvent.click(screen.getByRole("button", { name: "Include in candidate" }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledWith("overtime", true, "Employer letter"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows a person's decision with who, when and why, next to what the method said", () => {
    const a = analysis();
    a.components[1].included = true;
    a.components[1].override = {
      included: true,
      reason: "Employer letter received",
      by: "demo.reviewer",
      at: "2026-11-20T10:00:00.000Z",
    };
    render(<IncomeTable analysis={a} pillarSlug="underwriting" onDecide={vi.fn()} />);
    const overtime = within(screen.getByTestId("component-overtime"));
    expect(overtime.getByText("Counted")).toBeInTheDocument();
    expect(overtime.getByText(/Included by demo\.reviewer/)).toBeInTheDocument();
    expect(overtime.getByText("Reason: Employer letter received")).toBeInTheDocument();
    expect(overtime.getByText(/The method said: left out\. Documented history covers 2026 only/)).toBeInTheDocument();
    expect(overtime.getByRole("button", { name: "Exclude Overtime (1.5x)" })).toBeInTheDocument(); // can be undone
  });

  it("shows a dash where a component has no figure", () => {
    const a = analysis();
    a.components[2].current_period = null;
    renderTable(a);
    expect(within(screen.getByTestId("component-bonus")).getByText("—")).toBeInTheDocument();
  });
});
