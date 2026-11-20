import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { IncomeComponent } from "@/lib/income-types";
import { buildDanielIncome } from "@/mocks/income";
import { IncomeDecisionDialog } from "./income-decision-dialog";

const component = (id: string): IncomeComponent =>
  buildDanielIncome("2026-11-20T09:00:00.000Z").components.find((c) => c.id === id)!;

const setup = (
  props: { component?: IncomeComponent | null; onConfirm?: (included: boolean, reason: string) => Promise<void> } = {},
) => {
  const onOpenChange = vi.fn();
  const onConfirm = props.onConfirm ?? vi.fn().mockResolvedValue(undefined);
  render(
    <IncomeDecisionDialog
      component={props.component === undefined ? component("overtime") : props.component}
      onOpenChange={onOpenChange}
      onConfirm={onConfirm}
    />,
  );
  return { onOpenChange, onConfirm };
};

const type = (text: string) =>
  fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: text } });

describe("IncomeDecisionDialog", () => {
  it("renders nothing while there is no component", () => {
    setup({ component: null });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers to include a component that is left out, and says what the method said", () => {
    setup();
    expect(screen.getByText("Include Overtime (1.5x)")).toBeInTheDocument();
    expect(screen.getByText(/444\.41 a month, will be added to the candidate monthly income/)).toBeInTheDocument();
    expect(screen.getByText(/The method says: left out\. Documented history covers 2026 only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Include in candidate" })).toBeInTheDocument();
  });

  it("offers to exclude a component that is counted", () => {
    setup({ component: component("base_pay") });
    expect(screen.getByText("Exclude Base pay (hourly)")).toBeInTheDocument();
    expect(screen.getByText(/5,980\.00 a month, will be taken out/)).toBeInTheDocument();
    expect(screen.getByText(/The method says: counted\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exclude from candidate" })).toBeInTheDocument();
  });

  it("keeps the button disabled until there is a reason, and a blank one does not count", () => {
    setup();
    const button = screen.getByRole("button", { name: "Include in candidate" });
    expect(button).toBeDisabled();
    type("     ");
    expect(button).toBeDisabled();
    type("Employer letter received");
    expect(button).toBeEnabled();
  });

  it("sends the decision with a trimmed reason, then closes", async () => {
    const { onConfirm, onOpenChange } = setup();
    type("  Employer letter received  ");
    fireEvent.click(screen.getByRole("button", { name: "Include in candidate" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(true, "Employer letter received"));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("sends included=false when excluding", async () => {
    const { onConfirm } = setup({ component: component("base_pay") });
    type("Employment ended");
    fireEvent.click(screen.getByRole("button", { name: "Exclude from candidate" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(false, "Employment ended"));
  });

  it("counts the characters and stops at 500", () => {
    setup();
    expect(screen.getByLabelText("Reason (required)")).toHaveAttribute("maxlength", "500");
    type("hello");
    expect(screen.getByTestId("reason-count")).toHaveTextContent("5/500");
  });

  it("stays open, shows the message and keeps the reason when saving fails", async () => {
    const { onOpenChange } = setup({ onConfirm: vi.fn().mockRejectedValue(new Error("Server is busy")) });
    type("Employer letter received");
    fireEvent.click(screen.getByRole("button", { name: "Include in candidate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Server is busy");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Employer letter received");
    expect(screen.getByRole("button", { name: "Include in candidate" })).toBeEnabled();
  });

  it("Cancel closes without sending anything", () => {
    const { onConfirm, onOpenChange } = setup();
    type("Employer letter received");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
