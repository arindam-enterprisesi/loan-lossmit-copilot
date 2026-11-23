import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReasonDialog } from "./reason-dialog";

const setup = (
  props: { open?: boolean; note?: string; onConfirm?: (reason: string) => Promise<void> } = {},
) => {
  const onOpenChange = vi.fn();
  const onConfirm = props.onConfirm ?? vi.fn().mockResolvedValue(undefined);
  const view = render(
    <ReasonDialog
      open={props.open ?? true}
      onOpenChange={onOpenChange}
      title="Override Pay stubs"
      description="The item will count as satisfied."
      note={props.note}
      confirmLabel="Override item"
      maxLength={500}
      onConfirm={onConfirm}
    />,
  );
  return { onOpenChange, onConfirm, view };
};

const type = (text: string) =>
  fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: text } });

describe("ReasonDialog", () => {
  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the title, the description and, when given, what the system said before", () => {
    setup({ note: "The checklist found: 14 of 30 days" });
    expect(screen.getByText("Override Pay stubs")).toBeInTheDocument();
    expect(screen.getByText("The item will count as satisfied.")).toBeInTheDocument();
    expect(screen.getByText("The checklist found: 14 of 30 days")).toBeInTheDocument();
  });

  it("leaves out the note box when there is no note", () => {
    setup();
    expect(screen.queryByText(/The checklist found/)).not.toBeInTheDocument();
  });

  it("will not confirm until there is a real reason", () => {
    setup();
    const confirm = screen.getByRole("button", { name: "Override item" });
    expect(confirm).toBeDisabled();
    type("   ");
    expect(confirm).toBeDisabled();
    type("Letter received");
    expect(confirm).toBeEnabled();
  });

  it("sends the trimmed reason and closes", async () => {
    const { onConfirm, onOpenChange } = setup();
    type("  Letter received  ");
    fireEvent.click(screen.getByRole("button", { name: "Override item" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("Letter received", ""));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("stays open with the message and the typed reason when saving fails", async () => {
    const { onOpenChange } = setup({ onConfirm: vi.fn().mockRejectedValue(new Error("Server is busy")) });
    type("Letter received");
    fireEvent.click(screen.getByRole("button", { name: "Override item" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Server is busy");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Letter received");
  });

  it("starts with an empty box every time it is opened", () => {
    const { view } = setup();
    type("left over");
    view.rerender(
      <ReasonDialog
        open={false}
        onOpenChange={vi.fn()}
        title="Override Pay stubs"
        description="d"
        confirmLabel="Override item"
        maxLength={500}
        onConfirm={vi.fn()}
      />,
    );
    view.rerender(
      <ReasonDialog
        open
        onOpenChange={vi.fn()}
        title="Override Pay stubs"
        description="d"
        confirmLabel="Override item"
        maxLength={500}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("");
  });

  it("counts the characters against the limit", () => {
    setup();
    expect(screen.getByLabelText("Reason (required)")).toHaveAttribute("maxlength", "500");
    type("hello");
    expect(screen.getByTestId("reason-count")).toHaveTextContent("5/500");
  });
});

describe("ReasonDialog with an extra field", () => {
  const amountField = {
    label: "Amount counted each month",
    initialValue: "410.00",
    validate: (v: string) => (/^\d+(\.\d{1,2})?$/.test(v) ? null : "Enter an amount such as 200.00"),
  };
  const setupField = (field: Parameters<typeof ReasonDialog>[0]["field"]) => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <ReasonDialog
        open
        onOpenChange={vi.fn()}
        title="Adjust Other"
        description="d"
        confirmLabel="Adjust item"
        maxLength={500}
        field={field}
        onConfirm={onConfirm}
      />,
    );
    return { onConfirm };
  };

  it("starts the box with the initial value", () => {
    setupField(amountField);
    expect(screen.getByLabelText("Amount counted each month")).toHaveValue("410.00");
  });

  it("needs both the reason and a valid value, and sends both trimmed", async () => {
    const { onConfirm } = setupField(amountField);
    const confirm = screen.getByRole("button", { name: "Adjust item" });
    expect(confirm).toBeDisabled(); // no reason yet
    type("One-off repair");
    expect(confirm).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "  200.00 " } });
    fireEvent.click(confirm);
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("One-off repair", "200.00"));
  });

  it("shows the message and blocks confirming while the value is not acceptable", () => {
    setupField(amountField);
    type("One-off repair");
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "two hundred" } });
    expect(screen.getByText("Enter an amount such as 200.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adjust item" })).toBeDisabled();
  });

  it("blocks confirming when the value is emptied", () => {
    setupField(amountField);
    type("One-off repair");
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Adjust item" })).toBeDisabled();
  });

  it("offers a list when the field has options, and sends the chosen one", async () => {
    const { onConfirm } = setupField({
      label: "Correct value",
      initialValue: "unknown",
      options: [
        { value: "temporary", label: "Temporary" },
        { value: "long_term", label: "Long-term" },
        { value: "unknown", label: "Unknown" },
      ],
    });
    const select = screen.getByLabelText("Correct value");
    expect(select).toHaveValue("unknown");
    fireEvent.change(select, { target: { value: "long_term" } });
    type("Employer confirmed the cut is permanent");
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("Employer confirmed the cut is permanent", "long_term"));
  });
});
