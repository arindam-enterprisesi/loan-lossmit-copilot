import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LoanScenario } from "@/lib/assets-types";
import { LoanScenarioForm } from "./loan-scenario-form";

const saved: LoanScenario = {
  purpose: "purchase",
  occupancy: "primary residence",
  property_value: "400000.00",
  loan_amount: "360000.00",
  proposed_housing_payment: "1980.00",
  funds_to_close: "36500.00",
  updated_at: "2026-11-23T08:00:00.000Z",
};

const setup = (scenario: LoanScenario | null = saved, onSave = vi.fn().mockResolvedValue(undefined)) => {
  render(<LoanScenarioForm scenario={scenario} onSave={onSave} />);
  return onSave;
};
const field = (label: string) => screen.getByLabelText(label);
const type = (label: string, value: string) => fireEvent.change(field(label), { target: { value } });
const save = () => fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));

describe("LoanScenarioForm", () => {
  it("shows the saved scenario in its boxes, and when it was saved", () => {
    setup();
    expect(field("Loan purpose")).toHaveValue("purchase");
    expect(field("Occupancy")).toHaveValue("primary residence");
    expect(field("Property value")).toHaveValue("400000.00");
    expect(field("Loan amount")).toHaveValue("360000.00");
    expect(field("Proposed monthly housing payment")).toHaveValue("1980.00");
    expect(field("Funds needed to close")).toHaveValue("36500.00");
    expect(screen.getByText("Saved 23 Nov 2026")).toBeInTheDocument();
  });

  it("starts empty when nothing has been entered, and says so", () => {
    setup(null);
    expect(field("Loan purpose")).toHaveValue("");
    expect(field("Property value")).toHaveValue("");
    expect(screen.getByText("Not saved yet")).toBeInTheDocument();
  });

  it("offers the purposes and occupancies, and keeps a value the backend already holds", () => {
    setup({ ...saved, purpose: "bridge loan" });
    const purposes = Array.from(field("Loan purpose").querySelectorAll("option")).map((o) => o.textContent);
    expect(purposes).toEqual(["Choose…", "purchase", "refinance", "cash-out refinance", "bridge loan"]);
    expect(field("Loan purpose")).toHaveValue("bridge loan");
  });

  it("sends what was typed, as text, when it is acceptable", async () => {
    const onSave = setup();
    type("Proposed monthly housing payment", "2100.00");
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({
      purpose: "purchase",
      occupancy: "primary residence",
      property_value: "400000.00",
      loan_amount: "360000.00",
      proposed_housing_payment: "2100.00",
      funds_to_close: "36500.00",
    });
  });

  it("names each mistake next to its box, and sends nothing", () => {
    const onSave = setup(null);
    type("Property value", "0");
    type("Loan amount", "lots");
    save();
    expect(screen.getByText("Choose the loan purpose")).toBeInTheDocument();
    expect(screen.getByText("Choose the occupancy")).toBeInTheDocument();
    expect(screen.getByText("Must be more than zero")).toBeInTheDocument();
    expect(screen.getAllByText("Enter an amount such as 400000.00").length).toBeGreaterThanOrEqual(1);
    expect(field("Property value")).toHaveAttribute("aria-invalid", "true");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("clears a box's message as soon as it is edited", () => {
    setup(null);
    save();
    expect(screen.getByText("Choose the loan purpose")).toBeInTheDocument();
    fireEvent.change(field("Loan purpose"), { target: { value: "purchase" } });
    expect(screen.queryByText("Choose the loan purpose")).not.toBeInTheDocument();
  });

  it("says 'Not saved yet' after an edit, and stops saying it once saved", async () => {
    setup();
    expect(screen.queryByText("Not saved yet.")).not.toBeInTheDocument();
    type("Loan amount", "350000.00");
    expect(screen.getByText("Not saved yet.")).toBeInTheDocument();
    save();
    await waitFor(() => expect(screen.queryByText("Not saved yet.")).not.toBeInTheDocument());
  });

  it("shows the backend's message and keeps what was typed when saving fails", async () => {
    setup(saved, vi.fn().mockRejectedValue(new Error("Property value must be more than zero")));
    type("Funds needed to close", "40000.00");
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent("Property value must be more than zero");
    expect(field("Funds needed to close")).toHaveValue("40000.00");
    expect(screen.getByRole("button", { name: "Save scenario" })).toBeEnabled(); // can try again
  });

  it("does not send twice while it is saving", async () => {
    let finish!: () => void;
    const onSave = vi.fn().mockReturnValue(new Promise<void>((resolve) => (finish = resolve)));
    setup(saved, onSave);
    save();
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Loan scenario" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    finish();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save scenario" })).toBeEnabled());
  });
});
