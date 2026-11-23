import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ShowWorkingDrawer } from "./show-working-drawer";

const steps = [
  { label: "Base pay, monthly", formula: "34.50 × 80.00 hours × 26 periods ÷ 12", result: "5,980.00", note: "Illustrative method" },
];

describe("ShowWorkingDrawer", () => {
  it("opens to show each step exactly as given", () => {
    render(<ShowWorkingDrawer title="Base pay, monthly" steps={steps} />);
    expect(screen.queryByText("Base pay, monthly")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Show working/ }));
    expect(screen.getByText(/34.50 × 80.00 hours × 26 periods ÷ 12/)).toBeInTheDocument();
    expect(screen.getByText("5,980.00")).toBeInTheDocument();
    expect(screen.getByText("Illustrative method")).toBeInTheDocument();
  });

  it("lists where the inputs were read from, linking the documents", () => {
    render(
      <ShowWorkingDrawer
        title="Base pay, monthly"
        steps={steps}
        evidence={[
          { label: "Pay stub, 27 Sep 2026", detail: "Page 1, line p1-L14", href: "/underwriting/document-intelligence/c1/d1" },
          { label: "Income method income-method@1" },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Show working/ }));
    expect(screen.getByText("Read from")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pay stub, 27 Sep 2026" })).toHaveAttribute(
      "href",
      "/underwriting/document-intelligence/c1/d1",
    );
    expect(screen.getByText(/Page 1, line p1-L14/)).toBeInTheDocument();
    expect(screen.getByText("Income method income-method@1").tagName).not.toBe("A");
  });

  it("has no 'Read from' section when there is no evidence", () => {
    render(<ShowWorkingDrawer title="x" steps={steps} />);
    fireEvent.click(screen.getByRole("button", { name: /Show working/ }));
    expect(screen.queryByText("Read from")).not.toBeInTheDocument();
  });

  it("can carry its own accessible name when several share a screen", () => {
    render(
      <ShowWorkingDrawer title="x" steps={steps} triggerLabel="Working" triggerAriaLabel="Show working for Base pay, monthly" />,
    );
    expect(screen.getByRole("button", { name: "Show working for Base pay, monthly" })).toHaveTextContent("Working");
  });
});
