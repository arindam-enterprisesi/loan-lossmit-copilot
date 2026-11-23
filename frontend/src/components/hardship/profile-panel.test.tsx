import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProfileItem } from "@/lib/hardship-types";
import { applyConfirmation, buildAngelaHardship } from "@/mocks/hardship";
import { ProfilePanel } from "./profile-panel";

const base = () => buildAngelaHardship("2026-11-20T09:00:00.000Z");
const AT = "2026-11-20T10:00:00.000Z";

const setup = (
  items: ProfileItem[] = base().profile,
  handlers: { onCorrect?: (key: string, value: string, reason: string) => Promise<void> } = {},
) => {
  const onSelect = vi.fn();
  const onConfirm = vi.fn();
  const onCorrect = handlers.onCorrect ?? vi.fn().mockResolvedValue(undefined);
  render(
    <ProfilePanel
      items={items}
      selectedKey={null}
      onSelect={onSelect}
      onConfirm={onConfirm}
      onCorrect={onCorrect as never}
    />,
  );
  return { onSelect, onConfirm, onCorrect };
};

const card = (label: string) => within(screen.getByRole("article", { name: label }));

describe("ProfilePanel", () => {
  it("shows reason, onset, duration and intent, each with its value, its quote and the line it came from", () => {
    setup();
    expect(card("Primary reason").getByText("Reduction in income")).toBeInTheDocument();
    expect(card("Primary reason").getByText(/“cut my hours from 40 to 30 a week in July”/)).toBeInTheDocument();
    expect(card("Primary reason").getByText("Letter, line p1-L6")).toBeInTheDocument();
    expect(card("Onset").getByText("July 2026")).toBeInTheDocument();
    expect(card("Duration").getByText("Unknown")).toBeInTheDocument();
    expect(card("Intent").getByText("Keep the home")).toBeInTheDocument();
  });

  it("ticks each quote that was verified, and says so plainly when one was not", () => {
    const items = base().profile;
    items[2] = { ...items[2], quote_verified: false };
    setup(items);
    expect(screen.getAllByText("✓ Quote verified")).toHaveLength(3);
    expect(card("Duration").getByText("Quote not verified")).toBeInTheDocument();
  });

  it("says when an item has no quote", () => {
    const items = base().profile;
    items[1] = { ...items[1], quote: null };
    setup(items);
    expect(card("Onset").getByText("No quote for this item.")).toBeInTheDocument();
  });

  it("starts every item as not reviewed, with Confirm and Correct", () => {
    setup();
    expect(screen.getAllByText("Not reviewed")).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: /^Confirm / })).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: /^Correct / })).toHaveLength(4);
  });

  it("Confirm and Show in letter hand the item's key to the screen", () => {
    const { onConfirm, onSelect } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Confirm Intent" }));
    expect(onConfirm).toHaveBeenCalledWith("intent");
    fireEvent.click(screen.getByRole("button", { name: "Show Duration in the letter" }));
    expect(onSelect).toHaveBeenCalledWith("duration");
  });

  it("a confirmed item says reviewer-confirmed, by whom and when, and loses its Confirm button", () => {
    const items = applyConfirmation(base(), { key: "intent", action: "confirm" }, "demo.reviewer", AT).profile;
    setup(items);
    expect(card("Intent").getByText("Reviewer-confirmed")).toBeInTheDocument();
    expect(card("Intent").getByText(/Confirmed by demo\.reviewer, 20 Nov 2026/)).toBeInTheDocument();
    expect(card("Intent").queryByRole("button", { name: "Confirm Intent" })).not.toBeInTheDocument();
    expect(card("Intent").getByRole("button", { name: "Correct Intent" })).toBeInTheDocument(); // can still be corrected
  });

  it("a corrected item shows the new value, the reason and what the letter said", () => {
    const items = applyConfirmation(
      base(),
      { key: "duration", action: "correct", value: "long_term", reason: "Employer said it is permanent" },
      "demo.reviewer",
      AT,
    ).profile;
    setup(items);
    expect(card("Duration").getByText("Long-term")).toBeInTheDocument();
    expect(card("Duration").getByText("Reviewer-corrected")).toBeInTheDocument();
    expect(card("Duration").getByText("Reason: Employer said it is permanent")).toBeInTheDocument();
    expect(card("Duration").getByText("Read from the letter: Unknown")).toBeInTheDocument();
  });

  it("Correct opens a window with the allowed values, what the letter said, and a required reason", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Correct Duration" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Correct Duration")).toBeInTheDocument();
    expect(screen.getByText(/The letter reading says: Unknown/)).toBeInTheDocument();
    const select = screen.getByLabelText("Correct value");
    expect(select).toHaveValue("unknown");
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
      "Temporary",
      "Long-term",
      "Unknown",
    ]);
    expect(screen.getByRole("button", { name: "Save correction" })).toBeDisabled();
  });

  it("sends the key, the chosen value and the reason, then closes", async () => {
    const { onCorrect } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Correct Duration" }));
    fireEvent.change(screen.getByLabelText("Correct value"), { target: { value: "long_term" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer said it is permanent" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    await waitFor(() => expect(onCorrect).toHaveBeenCalledWith("duration", "long_term", "Employer said it is permanent"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("the onset is typed, not picked", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Correct Onset" }));
    expect(screen.getByLabelText("Correct onset")).toHaveValue("July 2026");
    expect(screen.getByLabelText("Correct onset").tagName).toBe("INPUT");
  });

  it("keeps the window open with the message when the correction is refused", async () => {
    setup(base().profile, { onCorrect: vi.fn().mockRejectedValue(new Error("A reason is required")) });
    fireEvent.click(screen.getByRole("button", { name: "Correct Intent" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Changed their mind" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Changed their mind");
  });

  it("Cancel sends nothing", () => {
    const { onCorrect } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Correct Intent" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onCorrect).not.toHaveBeenCalled();
  });
});
