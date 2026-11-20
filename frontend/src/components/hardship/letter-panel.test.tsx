import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ANGELA_CASE_ID } from "@/mocks/data";
import { buildAngelaHardship } from "@/mocks/hardship";
import type { ProfileKey } from "@/lib/hardship-types";
import { LetterPanel } from "./letter-panel";

const a = buildAngelaHardship("2026-11-20T09:00:00.000Z");

const renderLetter = (selectedKey: ProfileKey | null = null) =>
  render(
    <LetterPanel
      letter={a.letter}
      profile={a.profile}
      caseId={ANGELA_CASE_ID}
      pillarSlug="loss-mitigation"
      selectedKey={selectedKey}
    />,
  );

describe("LetterPanel", () => {
  it("shows every line of the letter with its line ID", () => {
    renderLetter();
    expect(screen.getByRole("heading", { name: "Hardship letter" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(16);
    const sixth = within(document.getElementById("letter-p1-L6")!);
    expect(sixth.getByText("p1-L6")).toBeInTheDocument();
    expect(sixth.getByText(/Because my employer/)).toBeInTheDocument();
  });

  it("highlights the quote for the reason, the duration and the intent, in place", () => {
    const { container } = renderLetter();
    const marks = Array.from(container.querySelectorAll("mark"));
    expect(marks.map((m) => [m.getAttribute("data-quote"), m.textContent])).toEqual([
      ["primary_reason", "cut my hours from 40 to 30 a week in July"],
      ["duration", "I do not know whether my hours will return to 40 a week"],
      ["intent", "I want to keep my home"],
    ]);
  });

  it("keeps the rest of a highlighted line as plain text", () => {
    renderLetter();
    const line = document.getElementById("letter-p1-L6")!;
    expect(line.textContent).toContain("Because my employer cut my hours from 40 to 30 a week in July, my pay fell by a quarter.");
    expect(line.querySelectorAll("mark")).toHaveLength(1);
  });

  it("shows the selected item's quote strongly and the others lightly", () => {
    const { container } = renderLetter("intent");
    const byKey = (k: string) => container.querySelector(`mark[data-quote="${k}"]`)!;
    expect(byKey("intent").className).toContain("bg-gold/50");
    expect(byKey("duration").className).toContain("bg-gold/20");
    expect(byKey("duration").className).not.toContain("bg-gold/50");
  });

  it("links to the letter in Document intake", () => {
    renderLetter();
    expect(screen.getByRole("link", { name: "Open the document" })).toHaveAttribute(
      "href",
      `/loss-mitigation/document-intake/${ANGELA_CASE_ID}/${a.letter.document_id}`,
    );
  });
});
