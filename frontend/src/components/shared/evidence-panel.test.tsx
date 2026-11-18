import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidencePanel } from "./evidence-panel";

// Box of line p1-L31 ("Net Pay 2,083.61") from the neutral OCR example in the technical design.
const bbox = { x0: 0.242, y0: 0.4, x1: 0.311, y1: 0.41 };

describe("EvidencePanel", () => {
  it("draws the cited box as a percentage of the page", () => {
    render(<EvidencePanel page={1} lineIds={["p1-L31"]} bbox={bbox} />);
    const box = screen.getByTestId("evidence-box");
    expect(parseFloat(box.style.left)).toBeCloseTo(24.2, 5);
    expect(parseFloat(box.style.top)).toBeCloseTo(40, 5);
    expect(parseFloat(box.style.width)).toBeCloseTo(6.9, 5);
    expect(parseFloat(box.style.height)).toBeCloseTo(1, 5);
    expect(box.style.left.endsWith("%")).toBe(true);
  });

  it("draws no box when the field has no position", () => {
    render(<EvidencePanel page={2} lineIds={[]} />);
    expect(screen.queryByTestId("evidence-box")).not.toBeInTheDocument();
  });

  it("shows the page number and the cited line IDs", () => {
    render(<EvidencePanel page={3} lineIds={["p3-L4", "p3-L5"]} />);
    expect(screen.getByText("Page 3")).toBeInTheDocument();
    expect(screen.getByText("p3-L4")).toBeInTheDocument();
    expect(screen.getByText("p3-L5")).toBeInTheDocument();
  });

  it("shows the page image when a link is given", () => {
    render(<EvidencePanel page={1} lineIds={[]} imageUrl="https://example.test/p1.png" />);
    expect(screen.getByAltText("Page 1")).toHaveAttribute("src", "https://example.test/p1.png");
  });
});
