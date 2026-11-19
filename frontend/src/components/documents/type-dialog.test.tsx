import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DocumentType } from "@/lib/types";
import { TypeDialog } from "./type-dialog";

const setup = (
  props: {
    open?: boolean;
    currentType?: DocumentType | null;
    onConfirm?: (type: DocumentType, reason?: string) => Promise<void>;
  } = {},
) => {
  const onOpenChange = vi.fn();
  const onConfirm = props.onConfirm ?? vi.fn().mockResolvedValue(undefined);
  render(
    <TypeDialog
      open={props.open ?? true}
      onOpenChange={onOpenChange}
      fileName="scan_0042.jpg"
      currentType={props.currentType}
      onConfirm={onConfirm}
    />,
  );
  return { onOpenChange, onConfirm };
};

const pickType = (value: string) =>
  fireEvent.change(screen.getByLabelText("Document type"), { target: { value } });

describe("TypeDialog", () => {
  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("names the file and offers Choose when there is no type yet", () => {
    setup();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Choose document type")).toBeInTheDocument();
    expect(screen.getByText(/scan_0042\.jpg/)).toBeInTheDocument();
  });

  it("says Change and preselects the current type when there is one", () => {
    setup({ currentType: "pay_stub" });
    expect(screen.getByText("Change document type")).toBeInTheDocument();
    expect(screen.getByLabelText("Document type")).toHaveValue("pay_stub");
  });

  it("does not offer 'unrecognized' as a choice", () => {
    setup();
    const options = Array.from(screen.getByLabelText("Document type").querySelectorAll("option")).map((o) => o.value);
    expect(options).not.toContain("unrecognized");
    expect(options).toContain("w2");
  });

  it("keeps Confirm disabled until a type is chosen", () => {
    setup();
    expect(screen.getByRole("button", { name: "Confirm type" })).toBeDisabled();
    pickType("w2");
    expect(screen.getByRole("button", { name: "Confirm type" })).toBeEnabled();
  });

  it("sends the type and a trimmed reason, then closes", async () => {
    const { onConfirm, onOpenChange } = setup();
    pickType("w2");
    fireEvent.change(screen.getByLabelText("Reason (optional)"), { target: { value: "  Scanned W-2, no title  " } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("w2", "Scanned W-2, no title"));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("sends no reason at all when the box is left blank", async () => {
    const { onConfirm } = setup();
    pickType("pay_stub");
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("pay_stub", undefined));
  });

  it("counts the reason characters and stops at 500", () => {
    setup();
    const box = screen.getByLabelText("Reason (optional)");
    expect(box).toHaveAttribute("maxlength", "500");
    fireEvent.change(box, { target: { value: "hello" } });
    expect(screen.getByTestId("reason-count")).toHaveTextContent("5/500");
  });

  it("stays open and shows the message when saving fails", async () => {
    const { onOpenChange } = setup({ onConfirm: vi.fn().mockRejectedValue(new Error("Reason too long")) });
    pickType("w2");
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reason too long");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm type" })).toBeEnabled(); // can try again
  });

  it("Cancel closes without sending anything", () => {
    const { onConfirm, onOpenChange } = setup();
    pickType("w2");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
