import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Field } from "@/lib/types";
import { FieldList } from "./field-list";

const base: Field = {
  name: "x",
  value: "v",
  original_value: "v",
  certainty: "high",
  flags: [],
  review_status: "unreviewed",
  version: 1,
};

const fields: Field[] = [
  { ...base, name: "employer_name", value: "Northwind" },
  {
    ...base,
    name: "net_pay_current",
    value: "2083.61",
    original_value: "2083.61",
    certainty: "low",
    flags: [{ code: "DI-CHK-02", severity: "error", message: "Net pay does not match" }],
  },
  { ...base, name: "gross_pay_current", value: "3070.50" },
];

describe("FieldList", () => {
  it("shows the flagged field first, with its flag code and message", () => {
    render(<FieldList fields={fields} selectedName={null} onSelect={() => {}} onReview={async () => true} />);
    // direct children only: each flag line inside a field is itself a list item
    const items = Array.from(screen.getByRole("list", { name: "Extracted fields" }).children);
    expect(items[0]).toHaveTextContent("Net pay current");
    expect(items[0]).toHaveTextContent("DI-CHK-02");
    expect(items[0]).toHaveTextContent("Net pay does not match");
    expect(items[1]).toHaveTextContent("Employer name");
  });

  it("tells the parent which field was picked", () => {
    const onSelect = vi.fn();
    render(<FieldList fields={fields} selectedName={null} onSelect={onSelect} onReview={async () => true} />);
    fireEvent.click(screen.getByRole("button", { name: /Employer name/ }));
    expect(onSelect).toHaveBeenCalledWith("employer_name");
  });

  it("only the selected field shows review actions", () => {
    render(
      <FieldList fields={fields} selectedName="employer_name" onSelect={() => {}} onReview={async () => true} />,
    );
    expect(screen.getAllByRole("button", { name: "Confirm value" })).toHaveLength(1);
  });

  it("shows the original value struck through after a correction", () => {
    const corrected: Field = {
      ...base,
      name: "net_pay_current",
      value: "2033.61",
      original_value: "2083.61",
      review_status: "corrected",
      review_reason: "OCR misread",
      version: 2,
    };
    render(<FieldList fields={[corrected]} selectedName={null} onSelect={() => {}} onReview={async () => true} />);
    expect(screen.getByText("2033.61")).toBeInTheDocument();
    const original = screen.getByText("2083.61");
    expect(original.tagName).toBe("S");
    expect(screen.getByText("Corrected")).toBeInTheDocument();
    expect(screen.getByText(/OCR misread/)).toBeInTheDocument();
  });

  it("says so when nothing was extracted", () => {
    render(<FieldList fields={[]} selectedName={null} onSelect={() => {}} onReview={async () => true} />);
    expect(screen.getByText("No fields were extracted from this document.")).toBeInTheDocument();
  });
});
