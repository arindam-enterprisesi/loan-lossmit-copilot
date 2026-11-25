import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { RecommendationWorkspace } from "@/components/recommendation/recommendation-workspace";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore, runCopilotMock } from "@/mocks/store";
import { UnderwritingCopilotWorkspace } from "./underwriting-copilot-workspace";

// CLAUDE.md rule 3: people make every decision, so no screen says approve, deny, offer, eligible or
// qualifies, even to say "never". Both agent screens are rendered the way a reviewer uses them (report,
// expanded cards, open windows, the sign-off) and every word they show, and every label a screen reader
// would read, is scanned.
const BANNED = /approv|deny|denied|denial|eligib|qualif|\boffer/i;

/** Text on the page, plus the words in attributes that are read aloud or shown on hover. */
function everythingShown(): string {
  const parts: string[] = [document.body.textContent ?? ""];
  document.body.querySelectorAll("[aria-label],[title],[placeholder],[alt]").forEach((el) => {
    for (const name of ["aria-label", "title", "placeholder", "alt"]) {
      const value = el.getAttribute(name);
      if (value) parts.push(value);
    }
  });
  return parts.join("\n");
}

const expectNoDecisionWords = () => {
  const text = everythingShown();
  const hit = text.match(BANNED);
  expect(hit ? text.slice(Math.max(0, hit.index! - 60), hit.index! + 60) : null).toBeNull();
};

beforeEach(() => resetMockStore());

describe("the scan itself", () => {
  it("catches each decision word, in any case, and lets the review words through", () => {
    for (const word of ["Approved", "deny", "Denied", "eligible", "Eligibility", "qualifies", "Qualifying", "We offer", "offers"]) {
      expect(BANNED.test(word)).toBe(true);
    }
    for (const word of ["Records a review. Not a decision.", "Met", "Not met", "Needs confirmation", "coffee"]) {
      expect(BANNED.test(word)).toBe(false);
    }
  });
});

describe("decision wording on the Underwriting copilot", () => {
  it("shows none of the decision words in the report, the conditions, the windows or the sign-off", async () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0); // a later run: every agent succeeds
    render(<UnderwritingCopilotWorkspace cases={mockCases.filter((c) => c.id === DANIEL_CASE_ID)} pillarSlug="underwriting" />);
    await screen.findByRole("heading", { name: "Suggested conditions" });
    expectNoDecisionWords();

    // Every window a reviewer can open.
    fireEvent.click(screen.getByRole("button", { name: "Reject condition 1" }));
    await screen.findByRole("dialog");
    expectNoDecisionWords();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Edit condition 2" }));
    await screen.findByRole("dialog");
    expectNoDecisionWords();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    await screen.findByRole("dialog");
    expectNoDecisionWords();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    // A cited guideline passage.
    fireEvent.click(screen.getAllByRole("button", { name: "Guideline passage" })[0]);
    await screen.findByText(/Overtime and bonus income may be counted when the borrower/);
    expectNoDecisionWords();
  });

  it("shows none of them once every condition has a decision and the review is signed off", async () => {
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    runCopilotMock("underwriting", DANIEL_CASE_ID, 0);
    render(<UnderwritingCopilotWorkspace cases={mockCases.filter((c) => c.id === DANIEL_CASE_ID)} pillarSlug="underwriting" />);
    await screen.findByRole("heading", { name: "Suggested conditions" });
    for (let n = 1; n <= 6; n++) fireEvent.click(screen.getByRole("button", { name: `Accept condition ${n}` }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign off review" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    await screen.findByText(/Review signed off by/);
    expectNoDecisionWords();
  });
});

describe("decision wording on the Loss Mitigation recommendation", () => {
  it("shows none of them in the lender view, the waterfall, the report or the override window", async () => {
    runCopilotMock("lm", ANGELA_CASE_ID, 0);
    runCopilotMock("lm", ANGELA_CASE_ID, 0);
    render(<RecommendationWorkspace cases={mockCases.filter((c) => c.id === ANGELA_CASE_ID)} />);
    await screen.findByRole("heading", { name: "Waterfall" });
    await screen.findByRole("heading", { name: "Sign off review" });
    expectNoDecisionWords();

    // Open every option card, as a reviewer reading the conditions would.
    for (const button of screen.getAllByRole("button", { name: /^Show conditions for / })) fireEvent.click(button);
    expectNoDecisionWords();

    fireEvent.click(screen.getAllByRole("button", { name: /^Override / })[0]);
    await screen.findByRole("dialog");
    expectNoDecisionWords();
  });
});
