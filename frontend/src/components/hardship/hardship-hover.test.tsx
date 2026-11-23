import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProfileItem } from "@/lib/hardship-types";
import { toHardshipAssessment } from "@/lib/hardship-real";
import { realAngelaHardship } from "@/lib/hardship-real-sample";
import { ANGELA_CASE_ID, mockCases } from "@/mocks/data";
import { buildAngelaHardship } from "@/mocks/hardship";
import { getJobMock, JOB_QUEUE_MS, JOB_RUN_MS, resetMockStore, runHardshipMock } from "@/mocks/store";
import { HardshipWorkspace } from "./hardship-workspace";
import { LetterPanel } from "./letter-panel";
import { ProfilePanel } from "./profile-panel";

const a = buildAngelaHardship("2026-11-20T09:00:00.000Z");
const activeLineIds = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('li[data-active="true"]')).map((li) => li.id);

const renderLetter = (props: Partial<Parameters<typeof LetterPanel>[0]> = {}) =>
  render(
    <LetterPanel letter={a.letter} profile={a.profile} caseId={ANGELA_CASE_ID} pillarSlug="loss-mitigation" selectedKey={null} {...props} />,
  );

describe("LetterPanel: the lines of the item being pointed at light up", () => {
  it("lights nothing when nothing is hovered or picked", () => {
    const { container } = renderLetter();
    expect(activeLineIds(container)).toEqual([]);
  });

  it("lights the lines of the hovered item, and shows its quote strongly", () => {
    const { container } = renderLetter({ hoveredKey: "intent" });
    expect(activeLineIds(container)).toEqual(["letter-p1-L14"]);
    expect(container.querySelector('mark[data-quote="intent"]')!.className).toContain("bg-gold/50");
    expect(container.querySelector('mark[data-quote="duration"]')!.className).not.toContain("bg-gold/50");
  });

  it("the reason and the onset share line 6, so either one lights it", () => {
    expect(activeLineIds(renderLetter({ hoveredKey: "primary_reason" }).container)).toEqual(["letter-p1-L6"]);
    expect(activeLineIds(renderLetter({ hoveredKey: "onset" }).container)).toEqual(["letter-p1-L6"]);
  });

  it("pointing at an item wins over the one picked with Show in letter, until the pointer leaves", () => {
    const picked = renderLetter({ selectedKey: "duration", hoveredKey: "intent" });
    expect(activeLineIds(picked.container)).toEqual(["letter-p1-L14"]);
    picked.unmount();
    const left = renderLetter({ selectedKey: "duration", hoveredKey: null });
    expect(activeLineIds(left.container)).toEqual(["letter-p1-L9"]);
  });

  it("lights every line of a quote that runs over several lines", () => {
    const profile: ProfileItem[] = a.profile.map((p) =>
      p.key === "duration" ? { ...p, quote: { text: "I do not know", line_ids: ["p1-L9", "p1-L10"] } } : p,
    );
    const { container } = renderLetter({ profile, hoveredKey: "duration" });
    expect(activeLineIds(container)).toEqual(["letter-p1-L9", "letter-p1-L10"]);
  });

  it("an item with no quote lights nothing", () => {
    const profile = a.profile.map((p) => (p.key === "intent" ? { ...p, quote: null } : p));
    expect(activeLineIds(renderLetter({ profile, hoveredKey: "intent" }).container)).toEqual([]);
  });
});

describe("LetterPanel: when only the quoted lines are known", () => {
  const real = toHardshipAssessment(realAngelaHardship(), ANGELA_CASE_ID);

  it("says so, and still highlights the hovered item's line", () => {
    const { container } = render(
      <LetterPanel letter={real.letter} profile={real.profile} caseId={ANGELA_CASE_ID} pillarSlug="loss-mitigation" selectedKey={null} hoveredKey="duration" />,
    );
    expect(screen.getByText(/Only the quoted lines are shown/)).toBeInTheDocument();
    expect(activeLineIds(container)).toEqual(["letter-p1-L9"]);
    expect(screen.getByRole("link", { name: "Open the document" })).toBeInTheDocument();
  });

  it("shows no link when the backend did not name the letter's document", () => {
    render(
      <LetterPanel
        letter={{ ...real.letter, document_id: "" }}
        profile={real.profile}
        caseId={ANGELA_CASE_ID}
        pillarSlug="loss-mitigation"
        selectedKey={null}
      />,
    );
    expect(screen.queryByRole("link", { name: "Open the document" })).not.toBeInTheDocument();
  });

  it("a whole letter does not carry the note", () => {
    renderLetter();
    expect(screen.queryByText(/Only the quoted lines are shown/)).not.toBeInTheDocument();
  });
});

describe("ProfilePanel: reports which card is being pointed at", () => {
  const setup = () => {
    const onHover = vi.fn();
    render(<ProfilePanel items={a.profile} selectedKey={null} onSelect={vi.fn()} onHover={onHover} onConfirm={vi.fn()} onCorrect={vi.fn()} />);
    return onHover;
  };
  const card = (label: string) => screen.getByRole("article", { name: label });

  it("reports the item while the pointer is on its card, and null when it leaves", () => {
    const onHover = setup();
    fireEvent.mouseEnter(card("Intent"));
    expect(onHover).toHaveBeenLastCalledWith("intent");
    fireEvent.mouseLeave(card("Intent"));
    expect(onHover).toHaveBeenLastCalledWith(null);
  });

  it("does the same for the keyboard: focusing a button on the card reports it", () => {
    const onHover = setup();
    fireEvent.focus(screen.getByRole("button", { name: "Confirm Duration" }));
    expect(onHover).toHaveBeenLastCalledWith("duration");
  });

  it("moving the focus between the buttons of one card is not leaving it", () => {
    const onHover = setup();
    const confirm = screen.getByRole("button", { name: "Confirm Duration" });
    const correct = screen.getByRole("button", { name: "Correct Duration" });
    fireEvent.focus(confirm);
    onHover.mockClear();
    fireEvent.blur(confirm, { relatedTarget: correct });
    expect(onHover).not.toHaveBeenCalled();
  });

  it("moving the focus out of the card reports null", () => {
    const onHover = setup();
    const confirm = screen.getByRole("button", { name: "Confirm Duration" });
    fireEvent.focus(confirm);
    fireEvent.blur(confirm, { relatedTarget: screen.getByRole("button", { name: "Confirm Intent" }) });
    expect(onHover).toHaveBeenLastCalledWith(null);
  });

  it("works without a hover handler", () => {
    render(<ProfilePanel items={a.profile} selectedKey={null} onSelect={vi.fn()} onConfirm={vi.fn()} onCorrect={vi.fn()} />);
    expect(() => fireEvent.mouseEnter(card("Intent"))).not.toThrow();
  });
});

describe("HardshipWorkspace: pointing at a profile item lights its lines in the letter", () => {
  beforeEach(() => {
    resetMockStore();
    const job = runHardshipMock(ANGELA_CASE_ID, 0);
    getJobMock(job.id, JOB_QUEUE_MS + JOB_RUN_MS);
  });

  const renderScreen = () =>
    render(<HardshipWorkspace cases={mockCases.filter((c) => c.id === ANGELA_CASE_ID)} pillarSlug="loss-mitigation" />);

  it("lights the lines while the pointer is on the card, and stops when it leaves", async () => {
    const { container } = renderScreen();
    const intent = await screen.findByRole("article", { name: "Intent" });
    expect(activeLineIds(container)).toEqual([]);

    fireEvent.mouseEnter(intent);
    expect(activeLineIds(container)).toEqual(["letter-p1-L14"]);
    expect(within(intent).getByText("Show in letter")).toBeInTheDocument(); // the existing button still works beside it

    fireEvent.mouseLeave(intent);
    expect(activeLineIds(container)).toEqual([]);
  });

  it("falls back to the item picked with Show in letter when the pointer leaves", async () => {
    const { container } = renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    fireEvent.click(screen.getByRole("button", { name: "Show Duration in the letter" }));
    expect(activeLineIds(container)).toEqual(["letter-p1-L9"]);

    const intent = screen.getByRole("article", { name: "Intent" });
    fireEvent.mouseEnter(intent);
    expect(activeLineIds(container)).toEqual(["letter-p1-L14"]);
    fireEvent.mouseLeave(intent);
    expect(activeLineIds(container)).toEqual(["letter-p1-L9"]);
  });
});
