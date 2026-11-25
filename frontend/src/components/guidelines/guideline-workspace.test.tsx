import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANGELA_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore } from "@/mocks/store";
import type { SourceSet } from "@/lib/guidelines-types";
import { GuidelineWorkspace } from "./guideline-workspace";

beforeEach(() => resetMockStore());

const renderScreen = (defaultSourceSet?: SourceSet) => render(<GuidelineWorkspace cases={mockCases} defaultSourceSet={defaultSourceSet} />);
const box = () => screen.getByLabelText("Your question");
const type = (text: string) => fireEvent.change(box(), { target: { value: text } });
const askButton = () => screen.getByRole("button", { name: "Ask" });
const asked = async (text: string) => {
  type(text);
  fireEvent.click(askButton());
  await screen.findByText(text, { selector: "p" });
};

describe("GuidelineWorkspace: before the first question", () => {
  it("invites a question, offers examples, and has Ask switched off until something is typed", () => {
    renderScreen();
    expect(screen.getByText("Ask about the loaded sources")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Example questions" })).toBeInTheDocument();
    expect(askButton()).toBeDisabled();
    type("hello");
    expect(askButton()).toBeEnabled();
    type("   ");
    expect(askButton()).toBeDisabled();
  });

  it("starts on All, or on the source set it is given (Loss Mitigation starts on Regulation X)", () => {
    const first = renderScreen();
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    first.unmount();
    renderScreen("regulation_x");
    expect(screen.getByRole("radio", { name: "Regulation X" })).toHaveAttribute("aria-checked", "true");
  });

  it("has Attach case switched off", () => {
    renderScreen();
    expect(screen.getByRole("switch", { name: "Attach case" })).toHaveAttribute("aria-checked", "false");
  });
});

describe("GuidelineWorkspace: asking", () => {
  it("shows the question, then the cited answer, and empties the box", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    expect(await screen.findByRole("article", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByText(/^Fannie Mae asks for a two-year history/)).toBeInTheDocument();
    expect(box()).toHaveValue("");
    expect(screen.queryByText("Ask about the loaded sources")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Example questions" })).not.toBeInTheDocument();
  });

  it("an example question is asked at once", async () => {
    renderScreen();
    fireEvent.click(screen.getByRole("button", { name: "How should a large deposit be documented?" }));
    expect(await screen.findByRole("article", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByText(/^A large deposit that is not regular income/)).toBeInTheDocument();
  });

  it("Enter sends the question, and Shift+Enter does not", async () => {
    renderScreen();
    type("How is overtime income evaluated?");
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    expect(screen.queryByRole("article", { name: "Answer" })).not.toBeInTheDocument();
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(await screen.findByRole("article", { name: "Answer" })).toBeInTheDocument();
  });

  it("keeps each question and answer, oldest first", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    await screen.findByRole("article", { name: "Answer" });
    await asked("What are the jumbo loan limits?");
    await waitFor(() => expect(screen.getAllByRole("article", { name: "Answer" })).toHaveLength(2));
    const articles = screen.getAllByRole("article", { name: "Answer" });
    expect(articles[0]).toHaveTextContent("Fannie Mae asks for a two-year history");
    expect(articles[1]).toHaveTextContent("No supporting passage found");
  });

  it("says 'No supporting passage found' when the sources are silent, and does not guess", async () => {
    renderScreen();
    await asked("What are the jumbo loan limits?");
    expect(await screen.findByText("No supporting passage found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Open citation/ })).not.toBeInTheDocument();
  });

  it("the source set limits the answer: overtime has no answer under Regulation X only", async () => {
    renderScreen();
    fireEvent.click(screen.getByRole("radio", { name: "Regulation X" }));
    await asked("How is overtime income evaluated?");
    expect(await screen.findByText("No supporting passage found")).toBeInTheDocument();
    expect(screen.getByText("Not legal advice; confirm with your compliance team.")).toBeInTheDocument();
  });

  it("a Regulation X answer carries the notice", async () => {
    renderScreen("regulation_x");
    await asked("What must a servicer do after receiving a loss mitigation application?");
    expect(await screen.findByText("Not legal advice; confirm with your compliance team.")).toBeInTheDocument();
    expect(screen.getByText(/^A servicer must acknowledge a loss mitigation application/)).toBeInTheDocument();
  });

  it("shows where the sources differ, side by side", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    const sides = await screen.findByRole("region", { name: "Sources differ" });
    expect(within(sides).getAllByRole("article")).toHaveLength(3);
  });

  it("New conversation clears everything", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    await screen.findByRole("article", { name: "Answer" });
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByRole("article", { name: "Answer" })).not.toBeInTheDocument();
    expect(screen.getByText("Ask about the loaded sources")).toBeInTheDocument();
  });

  it("will not send a question that is too long, and says so", () => {
    renderScreen();
    type("x".repeat(1001));
    expect(screen.getByText("A question can be at most 1000 characters.")).toBeInTheDocument();
    expect(askButton()).toBeDisabled();
    expect(box()).toHaveAttribute("aria-invalid", "true");
  });
});

describe("GuidelineWorkspace: attaching a case", () => {
  it("adds the case's facts to the answer: Angela's missing August statement", async () => {
    renderScreen();
    fireEvent.click(screen.getByRole("switch", { name: "Attach case" }));
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    await asked("What must a servicer do about a missing document in a received application?");
    const facts = await screen.findByRole("region", { name: "Facts to check" });
    expect(within(facts).getByText("Which statement is missing (the August bank statement)")).toBeInTheDocument();
    expect(screen.getByText(/Case attached: Angela Whitfield/)).toBeInTheDocument();
  });

  it("without it the same question lists no facts, and shows no case chip", async () => {
    renderScreen();
    await asked("What must a servicer do about a missing document in a received application?");
    await screen.findByRole("article", { name: "Answer" });
    expect(screen.queryByRole("region", { name: "Facts to check" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Case attached/)).not.toBeInTheDocument();
  });

  it("turning it off again stops attaching", async () => {
    renderScreen();
    fireEvent.click(screen.getByRole("switch", { name: "Attach case" }));
    fireEvent.click(screen.getByRole("switch", { name: "Attach case" }));
    expect(screen.queryByLabelText("Case")).not.toBeInTheDocument();
    await asked("How is overtime income evaluated?");
    await screen.findByRole("article", { name: "Answer" });
    expect(screen.queryByText(/Case attached/)).not.toBeInTheDocument();
  });
});

describe("GuidelineWorkspace: citations open passages", () => {
  const openFirstMarker = async () => {
    await asked("How is overtime income evaluated?");
    const answer = await screen.findByRole("article", { name: "Answer" });
    const sentence = within(answer).getByText(/^Fannie Mae asks for a two-year history/);
    fireEvent.click(within(sentence).getByRole("button", { name: /^Open citation 1/ }));
  };

  it("a marker opens the passage in a side panel, with its document, section, page, version and label", async () => {
    renderScreen();
    await openFirstMarker();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Overtime and bonus income may be counted when the borrower has received it for at least two years/)).toBeInTheDocument();
    expect(within(dialog).getByText("Authoritative")).toBeInTheDocument();
    const details = within(dialog).getByText("Document").closest("dl")!;
    expect(details).toHaveTextContent("Fannie Mae Selling Guide");
    expect(details).toHaveTextContent("B3-3.1-01 Overtime and bonus income");
    expect(details).toHaveTextContent("412");
    expect(details).toHaveTextContent("2026-09-02");
  });

  it("the lender overlay's passage is labelled Illustrative", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    const answer = await screen.findByRole("article", { name: "Answer" });
    const sentence = within(answer).getByText(/^The lender overlay counts it only with a two-year history/);
    fireEvent.click(within(sentence).getByRole("button", { name: /^Open citation 3/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Illustrative")).toBeInTheDocument();
    expect(within(dialog).queryByText("Authoritative")).not.toBeInTheDocument();
  });

  it("closes again", async () => {
    renderScreen();
    await openFirstMarker();
    await screen.findByRole("dialog");
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("GuidelineWorkspace: feedback", () => {
  it("marks an answer helpful, then changes it to wrongly cited", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    await screen.findByRole("article", { name: "Answer" });
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(await screen.findByText("Recorded: Helpful")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Wrongly cited" }));
    expect(await screen.findByText("Recorded: Wrongly cited")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "false");
  });

  it("each answer has its own feedback", async () => {
    renderScreen();
    await asked("How is overtime income evaluated?");
    await screen.findByRole("article", { name: "Answer" });
    await asked("How should a large deposit be documented?");
    await waitFor(() => expect(screen.getAllByRole("article", { name: "Answer" })).toHaveLength(2));
    const [first, second] = screen.getAllByRole("article", { name: "Answer" });
    fireEvent.click(within(first).getByRole("button", { name: "Not helpful" }));
    expect(await within(first).findByText("Recorded: Not helpful")).toBeInTheDocument();
    expect(within(second).queryByText(/^Recorded:/)).not.toBeInTheDocument();
  });
});
