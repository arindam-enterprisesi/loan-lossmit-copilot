import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ViewerBox } from "@/lib/viewer";
import { PageViewer } from "./page-viewer";

const boxes: ViewerBox[] = [
  { name: "net_pay_current", label: "Net pay current", page: 1, bbox: { x0: 0.242, y0: 0.4, x1: 0.311, y1: 0.41 } },
  { name: "employer_name", label: "Employer name", page: 1, bbox: { x0: 0.1, y0: 0.07, x1: 0.46, y1: 0.09 } },
  { name: "ending_balance", label: "Ending balance", page: 2, bbox: { x0: 0.2, y0: 0.5, x1: 0.3, y1: 0.52 } },
];

const setup = (props: Partial<React.ComponentProps<typeof PageViewer>> = {}) => {
  const handlers = { onPageChange: vi.fn(), onSelect: vi.fn(), onHover: vi.fn() };
  render(
    <PageViewer
      page={1}
      pageCount={2}
      boxes={boxes}
      selectedName="net_pay_current"
      hoveredName={null}
      lineIds={["p1-L31"]}
      imageUrl="/mock/paystub-p1.svg"
      {...handlers}
      {...props}
    />,
  );
  return handlers;
};

describe("PageViewer boxes", () => {
  it("draws a box for every field on this page, with the selected one marked", () => {
    setup();
    expect(screen.getAllByTestId("field-box")).toHaveLength(1); // employer name
    const selected = screen.getByTestId("evidence-box");
    expect(selected).toHaveAttribute("data-field", "net_pay_current");
    expect(parseFloat(selected.style.left)).toBeCloseTo(24.2, 5);
    expect(parseFloat(selected.style.top)).toBeCloseTo(40, 5);
  });

  it("does not draw boxes that belong to another page", () => {
    setup();
    expect(screen.queryByRole("button", { name: /Ending balance/ })).not.toBeInTheDocument();
  });

  it("clicking a box selects its field", () => {
    const { onSelect } = setup();
    fireEvent.click(screen.getByRole("button", { name: /Employer name/ }));
    expect(onSelect).toHaveBeenCalledWith("employer_name");
  });

  it("hovering a box reports it, and leaving clears it", () => {
    const { onHover } = setup();
    const box = screen.getByRole("button", { name: /Employer name/ });
    fireEvent.mouseEnter(box);
    expect(onHover).toHaveBeenLastCalledWith("employer_name");
    fireEvent.mouseLeave(box);
    expect(onHover).toHaveBeenLastCalledWith(null);
  });

  it("styles a hovered box differently from a plain one", () => {
    setup({ hoveredName: "employer_name" });
    expect(screen.getByTestId("field-box").className).toContain("border-teal ");
  });

  it("shows the selected field's line IDs", () => {
    setup();
    expect(screen.getByText("p1-L31")).toBeInTheDocument();
  });

  it("draws a blank page when there is no image yet", () => {
    setup({ imageUrl: undefined });
    expect(screen.queryByAltText("Page 1")).not.toBeInTheDocument();
    expect(screen.getByTestId("evidence-box")).toBeInTheDocument();
  });
});

describe("PageViewer image events", () => {
  it("tells the parent when the image fails to load, so it can fetch a fresh link", () => {
    const onImageError = vi.fn();
    setup({ onImageError });
    fireEvent.error(screen.getByAltText("Page 1"));
    expect(onImageError).toHaveBeenCalledTimes(1);
  });

  it("tells the parent when the image loads", () => {
    const onImageLoad = vi.fn();
    setup({ onImageLoad });
    fireEvent.load(screen.getByAltText("Page 1"));
    expect(onImageLoad).toHaveBeenCalledTimes(1);
  });

  it("keeps the boxes when the image is missing, so reviewing still works", () => {
    setup({ imageUrl: undefined });
    expect(screen.getByTestId("evidence-box")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Employer name/ })).toBeInTheDocument();
  });
});

describe("PageViewer zoom", () => {
  it("starts at 100% and zooms the page canvas in and out", () => {
    setup();
    const canvas = screen.getByTestId("page-canvas");
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("100%");
    expect(canvas.style.width).toBe("100%");

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("150%");
    expect(canvas.style.width).toBe("150%");

    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("75%");
  });

  it("keeps boxes at the same percentage position at any zoom", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const selected = screen.getByTestId("evidence-box");
    // Positions are percentages of the canvas, which itself grows with zoom.
    expect(parseFloat(selected.style.left)).toBeCloseTo(24.2, 5);
    expect(screen.getByTestId("page-canvas").style.width).toBe("200%");
  });

  it("stops at the smallest and largest zoom", () => {
    setup();
    for (let i = 0; i < 10; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("300%");
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
    for (let i = 0; i < 10; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("50%");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
  });

  it("goes back to 100% with Reset zoom", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset zoom" }));
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("100%");
  });
});

describe("PageViewer pages", () => {
  it("shows which page it is on and asks the parent to change it", () => {
    const { onPageChange } = setup();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("disables Previous on the first page and Next on the last", () => {
    setup();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).not.toBeDisabled();
  });

  it("draws the other page's boxes when the parent moves to it", () => {
    setup({ page: 2, selectedName: "ending_balance" });
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-box")).toHaveAttribute("data-field", "ending_balance");
    expect(screen.queryByRole("button", { name: /Employer name/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});
