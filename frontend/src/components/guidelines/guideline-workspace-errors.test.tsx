import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/shared/toast";
import { ApiError } from "@/lib/api-error";
import { buildGuidelineAnswer } from "@/mocks/guidelines";
import { mockCases } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  askGuideline: vi.fn(),
  sendGuidelineFeedback: vi.fn(),
  getGuidelinePassage: vi.fn(),
}));
import { askGuideline, sendGuidelineFeedback } from "@/lib/api";
import { GuidelineWorkspace } from "./guideline-workspace";

const ask = vi.mocked(askGuideline);
const feedback = vi.mocked(sendGuidelineFeedback);

const QUESTION = "How is overtime income evaluated?";
const answer = () => buildGuidelineAnswer({ question: QUESTION, source_set: "all", case_id: null }, "g1", "2026-11-23T09:00:00.000Z");

beforeEach(() => {
  ask.mockReset();
  feedback.mockReset();
});

const renderScreen = () =>
  render(
    <ToastProvider>
      <GuidelineWorkspace cases={mockCases} />
    </ToastProvider>,
  );
const type = (text: string) => fireEvent.change(screen.getByLabelText("Your question"), { target: { value: text } });
const send = () => fireEvent.click(screen.getByRole("button", { name: "Ask" }));

describe("GuidelineWorkspace while an answer is on its way", () => {
  it("shows the question and a placeholder, and locks the controls until it arrives", async () => {
    let finish!: (a: ReturnType<typeof answer>) => void;
    ask.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderScreen();
    type(QUESTION);
    send();

    expect(await screen.findByRole("status", { name: "Looking for passages" })).toBeInTheDocument();
    expect(screen.getByText(QUESTION, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Asking…" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Attach case" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Guidelines" })).toBeDisabled();

    finish(answer());
    expect(await screen.findByRole("article", { name: "Answer" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Looking for passages" })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Guidelines" })).toBeEnabled();
  });

  it("does not send a second question while one is on its way", async () => {
    ask.mockReturnValue(new Promise(() => {}));
    renderScreen();
    type(QUESTION);
    send();
    await screen.findByRole("status", { name: "Looking for passages" });
    fireEvent.keyDown(screen.getByLabelText("Your question"), { key: "Enter" });
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("sends what was chosen: the question, the source set, and no case unless one is attached", async () => {
    ask.mockResolvedValue(answer());
    renderScreen();
    fireEvent.click(screen.getByRole("radio", { name: "Guidelines" }));
    type("  " + QUESTION + "  ");
    send();
    await waitFor(() => expect(ask).toHaveBeenCalledWith(QUESTION, "guidelines", null));
  });

  it("sends the case when one is attached", async () => {
    ask.mockResolvedValue(answer());
    renderScreen();
    fireEvent.click(screen.getByRole("switch", { name: "Attach case" }));
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: mockCases[1].id } });
    type(QUESTION);
    send();
    await waitFor(() => expect(ask).toHaveBeenCalledWith(QUESTION, "all", mockCases[1].id));
  });
});

describe("GuidelineWorkspace when a question fails", () => {
  it("shows the message with Try again, and keeps the question in the box", async () => {
    ask.mockRejectedValue(new ApiError(503, "The service is busy"));
    renderScreen();
    type(QUESTION);
    send();
    expect(await screen.findByRole("alert")).toHaveTextContent("The service is busy");
    expect(screen.getByLabelText("Your question")).toHaveValue(QUESTION);
    expect(screen.queryByRole("article", { name: "Answer" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
  });

  it("Try again sends the same question, and the message goes away", async () => {
    ask.mockRejectedValueOnce(new ApiError(503, "The service is busy"));
    ask.mockResolvedValue(answer());
    renderScreen();
    type(QUESTION);
    send();
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("article", { name: "Answer" })).toBeInTheDocument();
    expect(ask).toHaveBeenCalledTimes(2);
    expect(ask.mock.calls[1]).toEqual(ask.mock.calls[0]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("");
  });

  it("says plainly when the backend has no question endpoint yet", async () => {
    ask.mockRejectedValue(new ApiError(404, "The guideline assistant is not available on this backend yet: the question endpoint is still to come."));
    renderScreen();
    type(QUESTION);
    send();
    expect(await screen.findByRole("alert")).toHaveTextContent("not available on this backend yet");
  });

  it("an answer that fails its own checks is not shown as an answer", async () => {
    ask.mockResolvedValue({ ...answer(), passages: [] });
    renderScreen();
    type(QUESTION);
    send();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be checked against its sources");
    expect(screen.queryByText(/Fannie Mae asks for a two-year history/)).not.toBeInTheDocument();
  });
});

describe("GuidelineWorkspace when feedback fails", () => {
  const withAnswer = async () => {
    ask.mockResolvedValue(answer());
    renderScreen();
    type(QUESTION);
    send();
    await screen.findByRole("article", { name: "Answer" });
  };

  it("shows the message with Try again, and the rating is not recorded", async () => {
    feedback.mockRejectedValue(new ApiError(503, "Could not save"));
    await withAnswer();
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(screen.queryByText("Recorded: Helpful")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "false");
  });

  it("Try again records the same rating", async () => {
    feedback.mockRejectedValueOnce(new ApiError(503, "Could not save"));
    feedback.mockResolvedValue(undefined);
    await withAnswer();
    fireEvent.click(screen.getByRole("button", { name: "Wrongly cited" }));
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Recorded: Wrongly cited")).toBeInTheDocument();
    expect(feedback).toHaveBeenCalledTimes(2);
    expect(feedback).toHaveBeenLastCalledWith("g1", "wrongly_cited");
  });
});
