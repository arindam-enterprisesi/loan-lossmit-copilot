import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ANGELA_CASE_ID } from "@/mocks/data";
import { buildAngelaHardship } from "@/mocks/hardship";
import { MeasuresStrip } from "./measures-strip";

const a = buildAngelaHardship("2026-11-20T09:00:00.000Z");
const renderStrip = (measures = a.measures) =>
  render(<MeasuresStrip measures={measures} caseId={ANGELA_CASE_ID} pillarSlug="loss-mitigation" />);
const measure = (id: string) => within(screen.getByTestId(`measure-${id}`));

describe("MeasuresStrip", () => {
  it("shows monthly surplus: observed -280.00 flagged, with the stated -70.00 beside it", () => {
    renderStrip();
    const m = measure("surplus");
    expect(m.getByText("Monthly surplus (observed)")).toBeInTheDocument();
    expect(m.getByText("-280.00")).toBeInTheDocument();
    expect(m.getByText("Stated -70.00")).toBeInTheDocument();
    expect(m.getByText("Flagged")).toBeInTheDocument();
    expect(m.getByText("Observed deficit 280.00 against 70.00 stated")).toBeInTheDocument();
    expect(screen.getByTestId("measure-surplus").className).toContain("bg-gold/10");
  });

  it("shows the housing ratio 40.95% up from 30.71%", () => {
    renderStrip();
    const m = measure("housing_ratio");
    expect(m.getByText("40.95%")).toBeInTheDocument();
    expect(m.getByText("Before the cut 30.71%")).toBeInTheDocument();
    expect(m.queryByText("Flagged")).not.toBeInTheDocument();
  });

  it("shows arrears 5,160.00, and liquid assets 640.25 = 12.41% of arrears", () => {
    renderStrip();
    expect(measure("arrears").getByText("5,160.00")).toBeInTheDocument();
    expect(measure("liquid_assets").getByText("640.25")).toBeInTheDocument();
    expect(measure("liquid_assets").getByText("12.41% of arrears")).toBeInTheDocument();
  });

  it("shows the change in pay as a percent", () => {
    renderStrip();
    expect(measure("income_change").getByText("-25.00%")).toBeInTheDocument();
  });

  it("only the surplus is flagged", () => {
    renderStrip();
    expect(screen.getAllByText("Flagged")).toHaveLength(1);
  });

  it("has a Show working drawer on every measure", () => {
    renderStrip();
    expect(screen.getAllByRole("button", { name: /^Show working for / })).toHaveLength(a.measures.length);
  });

  it("opens the working for the surplus with both bases and where it was read from", () => {
    renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Monthly surplus (observed)" }));
    expect(screen.getByText(/3,350\.00 − 3,420\.00/)).toBeInTheDocument();
    expect(screen.getByText(/3,350\.00 − 3,630\.00/)).toBeInTheDocument();
    expect(screen.getByText("Read from")).toBeInTheDocument();
  });

  it("opens the working for the housing ratio, now and before the cut", () => {
    renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Show working for Housing ratio" }));
    expect(screen.getByText(/1,720\.00 ÷ 4,200\.00 × 100/)).toBeInTheDocument();
    expect(screen.getByText(/1,720\.00 ÷ 5,600\.00 × 100/)).toBeInTheDocument();
  });
});
