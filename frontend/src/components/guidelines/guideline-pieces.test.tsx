import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { buildGuidelineAnswer } from "@/mocks/guidelines";
import type { FeedbackRating, GuidelineAnswer, SourceSet } from "@/lib/guidelines-types";
import { AnswerCard } from "./answer-card";
import { AttachCase } from "./attach-case";
import { FeedbackBar } from "./feedback-bar";
import { SourceComparison } from "./source-comparison";
import { SourceSetPicker } from "./source-set-picker";

const AT = "2026-11-23T09:00:00.000Z";
const ask = (question: string, source_set: SourceSet = "all", case_id: string | null = null): GuidelineAnswer =>
  buildGuidelineAnswer({ question, source_set, case_id }, "g1", AT);

describe("SourceSetPicker", () => {
  const Harness = ({ start = "all" as SourceSet, onChange = vi.fn() }) => {
    const [value, setValue] = useState<SourceSet>(start);
    return (
      <SourceSetPicker
        value={value}
        onChange={(v) => {
          setValue(v);
          onChange(v);
        }}
      />
    );
  };

  it("has Guidelines, Regulation X and All, with exactly one chosen", () => {
    render(<Harness />);
    const options = within(screen.getByRole("radiogroup", { name: "Source set" })).getAllByRole("radio");
    expect(options.map((o) => o.textContent)).toEqual(["Guidelines", "Regulation X", "All"]);
    expect(options.map((o) => o.getAttribute("aria-checked"))).toEqual(["false", "false", "true"]);
  });

  it("choosing one changes the choice", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Regulation X" }));
    expect(onChange).toHaveBeenCalledWith("regulation_x");
    expect(screen.getByRole("radio", { name: "Regulation X" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "false");
  });

  it("the arrow keys move between them, and wrap around", () => {
    render(<Harness start="guidelines" />);
    const group = screen.getByRole("radiogroup");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Regulation X" })).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
  });

  it("does nothing when disabled", () => {
    const onChange = vi.fn();
    render(<SourceSetPicker value="all" onChange={onChange} disabled />);
    fireEvent.click(screen.getByRole("radio", { name: "Guidelines" }));
    fireEvent.keyDown(screen.getByRole("radiogroup"), { key: "ArrowRight" });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("AttachCase", () => {
  const setup = (attached = false, over: Partial<Parameters<typeof AttachCase>[0]> = {}) => {
    const onAttachedChange = vi.fn();
    const onCaseChange = vi.fn();
    render(
      <AttachCase cases={mockCases} attached={attached} caseId={mockCases[0].id} onAttachedChange={onAttachedChange} onCaseChange={onCaseChange} {...over} />,
    );
    return { onAttachedChange, onCaseChange };
  };

  it("is a switch, off by default, with a line saying what it does", () => {
    setup();
    expect(screen.getByRole("switch", { name: "Attach case" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/Adds the case's facts/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Case")).not.toBeInTheDocument();
  });

  it("turning it on asks for the change, and shows the case to attach once it is on", () => {
    const { onAttachedChange } = setup();
    fireEvent.click(screen.getByRole("switch", { name: "Attach case" }));
    expect(onAttachedChange).toHaveBeenCalledWith(true);
  });

  it("when on, lists the cases and reports the one chosen", () => {
    const { onCaseChange } = setup(true);
    expect(screen.getByRole("switch", { name: "Attach case" })).toHaveAttribute("aria-checked", "true");
    expect(within(screen.getByLabelText("Case")).getAllByRole("option")).toHaveLength(mockCases.length);
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    expect(onCaseChange).toHaveBeenCalledWith(ANGELA_CASE_ID);
  });

  it("cannot be turned on when there is no case, and says so", () => {
    setup(false, { cases: [], caseId: null });
    expect(screen.getByRole("switch", { name: "Attach case" })).toBeDisabled();
    expect(screen.getByText("No case to attach.")).toBeInTheDocument();
  });

  it("is disabled while a question is being answered", () => {
    setup(true, { disabled: true });
    expect(screen.getByRole("switch", { name: "Attach case" })).toBeDisabled();
    expect(screen.getByLabelText("Case")).toBeDisabled();
  });
});

describe("FeedbackBar", () => {
  it("has the three choices, none chosen to start with, and no 'recorded' line", () => {
    render(<FeedbackBar value={null} onRate={vi.fn()} />);
    for (const name of ["Helpful", "Not helpful", "Wrongly cited"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-pressed", "false");
    }
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reports a choice, and shows the one already given as chosen", () => {
    const onRate = vi.fn();
    render(<FeedbackBar value="not_helpful" onRate={onRate} />);
    expect(screen.getByRole("button", { name: "Not helpful" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Recorded: Not helpful");
    fireEvent.click(screen.getByRole("button", { name: "Wrongly cited" }));
    expect(onRate).toHaveBeenCalledWith("wrongly_cited");
  });

  it("does not send the same choice again", () => {
    const onRate = vi.fn();
    render(<FeedbackBar value="helpful" onRate={onRate} />);
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(onRate).not.toHaveBeenCalled();
  });

  it("is disabled while one is being sent", () => {
    render(<FeedbackBar value={null} pending onRate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Helpful" })).toBeDisabled();
  });
});

describe("AnswerCard: a cited answer", () => {
  const setup = (answer: GuidelineAnswer, feedback: FeedbackRating | null = null, caseTitle?: string) => {
    const onOpenCitation = vi.fn();
    const onRate = vi.fn();
    render(<AnswerCard answer={answer} caseTitle={caseTitle} feedback={feedback} onOpenCitation={onOpenCitation} onRate={onRate} />);
    return { onOpenCitation, onRate };
  };

  // The sentences are one block; the side-by-side columns repeat the same markers, so queries stay inside it.
  const sentences = () => screen.getByText(/^Overtime and bonus income may be counted when it is likely to continue\./).parentElement!;

  it("shows each sentence with a numbered marker at its end, and the source set", () => {
    const a = ask("How is overtime income evaluated?", "guidelines");
    setup(a);
    expect(within(sentences()).getAllByRole("button", { name: /^Open citation/ })).toHaveLength(a.sentences.flatMap((s) => s.citations).length);
    expect(within(sentences()).getByRole("button", { name: "Open citation 3: Overlay 2.4 Overtime and bonus" })).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Answer" })).getByText("Guidelines")).toBeInTheDocument();
  });

  it("a marker opens its citation", () => {
    const a = ask("How is overtime income evaluated?", "guidelines");
    const { onOpenCitation } = setup(a);
    fireEvent.click(within(sentences()).getAllByRole("button", { name: /^Open citation 2: 5303\.1/ })[0]);
    expect(onOpenCitation).toHaveBeenCalledWith(2);
  });

  it("a sentence supported by two passages has two markers", () => {
    const a = ask("How is overtime income evaluated?", "guidelines");
    setup(a);
    const sentence = screen.getByText(/^Overtime and bonus income may be counted when it is likely to continue\./);
    expect(within(sentence).getAllByRole("button")).toHaveLength(2);
  });

  it("shows the sources side by side where they differ, and nothing about which one wins", () => {
    setup(ask("How is overtime income evaluated?", "guidelines"));
    const sides = screen.getByRole("region", { name: "Sources differ" });
    expect(within(sides).getByText("Sources differ: How long the overtime history must be")).toBeInTheDocument();
    expect(within(sides).getAllByRole("article")).toHaveLength(3);
    expect(within(sides).getByText("Lender overlay (demo)")).toBeInTheDocument();
    expect(within(sides).getByText("Illustrative")).toBeInTheDocument();
    expect(within(sides).getAllByText("Authoritative")).toHaveLength(2);
  });

  it("has no side-by-side block when the answer has no comparison", () => {
    setup(ask("How should a large deposit be documented?", "guidelines"));
    expect(screen.queryByRole("region", { name: "Sources differ" })).not.toBeInTheDocument();
  });

  it("says when a sentence was removed because its citation did not check out", () => {
    setup(ask("How should a large deposit be documented?", "guidelines"));
    expect(screen.getByRole("note")).toHaveTextContent("1 sentence was removed because its citation did not check out.");
  });

  it("says it in the plural for several", () => {
    setup({ ...ask("How is overtime income evaluated?", "guidelines"), removed_sentences: 3 });
    expect(screen.getByText("3 sentences were removed because their citations did not check out.")).toBeInTheDocument();
  });

  it("with a case attached, lists the facts to check and says they are not a conclusion", () => {
    setup(ask("How is overtime income evaluated?", "guidelines", DANIEL_CASE_ID), null, "Daniel Reyes — purchase");
    const facts = screen.getByRole("region", { name: "Facts to check" });
    expect(within(facts).getAllByRole("listitem")).toHaveLength(2);
    expect(within(facts).getByText(/not a conclusion about the borrower or the servicer/)).toBeInTheDocument();
    expect(screen.getByText("Case attached: Daniel Reyes — purchase")).toBeInTheDocument();
  });

  it("has no facts block without a case", () => {
    setup(ask("How is overtime income evaluated?", "guidelines"));
    expect(screen.queryByRole("region", { name: "Facts to check" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Case attached/)).not.toBeInTheDocument();
  });

  it("a Regulation X answer carries the notice, and a guidelines answer does not", () => {
    setup(ask("What must a servicer do after receiving a loss mitigation application?", "regulation_x", ANGELA_CASE_ID));
    expect(screen.getByText("Not legal advice; confirm with your compliance team.")).toBeInTheDocument();
  });

  it("no notice on a guidelines answer", () => {
    setup(ask("How is overtime income evaluated?", "guidelines"));
    expect(screen.queryByText(/Not legal advice/)).not.toBeInTheDocument();
  });

  it("offers feedback, reports a choice and shows the one given", () => {
    const { onRate } = setup(ask("How is overtime income evaluated?", "guidelines"));
    fireEvent.click(screen.getByRole("button", { name: "Wrongly cited" }));
    expect(onRate).toHaveBeenCalledWith("wrongly_cited");
  });
});

describe("AnswerCard: no supporting passage", () => {
  it("says so plainly, gives no sentences, no markers and no feedback to give", () => {
    render(<AnswerCard answer={ask("What are the jumbo loan limits?")} feedback={null} onOpenCitation={vi.fn()} onRate={vi.fn()} />);
    expect(screen.getByText("No supporting passage found")).toBeInTheDocument();
    expect(screen.getByText(/so no answer is given/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Open citation/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Feedback on this answer" })).not.toBeInTheDocument();
  });

  it("a Regulation X search that finds nothing still carries the notice", () => {
    render(<AnswerCard answer={ask("How is overtime income evaluated?", "regulation_x")} feedback={null} onOpenCitation={vi.fn()} onRate={vi.fn()} />);
    expect(screen.getByText("No supporting passage found")).toBeInTheDocument();
    expect(screen.getByText("Not legal advice; confirm with your compliance team.")).toBeInTheDocument();
  });
});

describe("AnswerCard: an answer that fails its own checks", () => {
  it("is not shown, with a message, when a sentence cites something that was not retrieved", () => {
    const bad = { ...ask("How is overtime income evaluated?", "guidelines"), passages: [] };
    render(<AnswerCard answer={bad} feedback={null} onOpenCitation={vi.fn()} onRate={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This answer could not be checked against its sources, so it is not shown.");
    expect(screen.queryByText(/Overtime and bonus income may be counted/)).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Feedback on this answer" })).not.toBeInTheDocument();
  });
});

describe("SourceComparison", () => {
  it("shows nothing for an answer with no comparison, or with fewer than two passages to compare", () => {
    const none = ask("How should a large deposit be documented?", "guidelines");
    const { container } = render(<SourceComparison answer={none} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    const lone = { ...ask("How is overtime income evaluated?", "guidelines"), comparison: { topic: "t", markers: [1] } };
    const { container: c2 } = render(<SourceComparison answer={lone} onOpen={vi.fn()} />);
    expect(c2).toBeEmptyDOMElement();
  });

  it("each column's marker opens its passage", async () => {
    const onOpen = vi.fn();
    render(<SourceComparison answer={ask("What does the lender overlay say about overtime?", "guidelines")} onOpen={onOpen} />);
    const columns = screen.getAllByRole("article");
    expect(columns).toHaveLength(2);
    fireEvent.click(within(columns[1]).getByRole("button", { name: /^Open citation 2/ }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(2));
  });
});
