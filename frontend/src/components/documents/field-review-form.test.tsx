import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Field } from "@/lib/types";
import { FieldReviewForm } from "./field-review-form";

const field: Field = {
  name: "net_pay_current",
  value: "2083.61",
  original_value: "2083.61",
  certainty: "low",
  flags: [],
  review_status: "unreviewed",
  version: 4,
};

const setup = (saved = true) => {
  const onSubmit = vi.fn().mockResolvedValue(saved);
  render(<FieldReviewForm field={field} onSubmit={onSubmit} />);
  return onSubmit;
};

describe("FieldReviewForm", () => {
  it("confirm sends straight away with the version it was loaded at", async () => {
    const onSubmit = setup();
    fireEvent.click(screen.getByRole("button", { name: "Confirm value" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({ action: "confirm", expected_version: 4 });
  });

  it("correct will not send without a value and a reason", () => {
    const onSubmit = setup();
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Corrected value"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(screen.getByText("Enter the corrected value.")).toBeInTheDocument();
    expect(screen.getByText(/Give a reason/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("correct sends the new value, the reason and the version", async () => {
    const onSubmit = setup();
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Corrected value"), { target: { value: "2033.61" } });
    fireEvent.change(screen.getByLabelText("Why is the value being corrected?"), {
      target: { value: "OCR misread the last digit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      action: "correct",
      value: "2033.61",
      reason: "OCR misread the last digit",
      expected_version: 4,
    });
  });

  it("reject needs only a reason", async () => {
    const onSubmit = setup();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(screen.queryByLabelText("Corrected value")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save rejection" }));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Why is the value being rejected?"), {
      target: { value: "Not on the page" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save rejection" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ action: "reject", reason: "Not on the page", expected_version: 4 }));
  });

  it("stays open with the typed reason when the save fails", async () => {
    const onSubmit = setup(false);
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Why is the value being corrected?"), {
      target: { value: "typo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(screen.getByLabelText("Why is the value being corrected?")).toHaveValue("typo");
  });

  it("always reminds that a review is not a decision", () => {
    setup();
    expect(screen.getByText("Records a review. Not a decision.")).toBeInTheDocument();
  });
});
