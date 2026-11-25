import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/shared/toast";
import { ApiError } from "@/lib/api-error";
import { startRun, underwritingAt } from "@/mocks/copilot";
import { DANIEL_CASE_ID, mockCases } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getLatestUnderwritingReport: vi.fn(),
  runUnderwritingReport: vi.fn(),
  rerunUnderwritingAgent: vi.fn(),
  decideUnderwritingCondition: vi.fn(),
  addUnderwritingCondition: vi.fn(),
  signOffUnderwriting: vi.fn(),
  getGuidelinePassage: vi.fn(),
  getJob: vi.fn(),
}));
import {
  addUnderwritingCondition,
  decideUnderwritingCondition,
  getLatestUnderwritingReport,
  rerunUnderwritingAgent,
  runUnderwritingReport,
  signOffUnderwriting,
} from "@/lib/api";
import { UnderwritingCopilotWorkspace } from "./underwriting-copilot-workspace";

const latest = vi.mocked(getLatestUnderwritingReport);
const start = vi.mocked(runUnderwritingReport);
const rerun = vi.mocked(rerunUnderwritingAgent);
const decide = vi.mocked(decideUnderwritingCondition);
const add = vi.mocked(addUnderwritingCondition);
const signOff = vi.mocked(signOffUnderwriting);

const NOW = Date.now();
/** A finished report, as the backend would answer it. */
const finished = (criticFails = false) => underwritingAt(startRun("underwriting", DANIEL_CASE_ID, 0, criticFails), NOW);
/** The same run a moment after it started: the agents are still working. */
const working = () => underwritingAt(startRun("underwriting", DANIEL_CASE_ID, NOW, false), NOW);

beforeEach(() => {
  for (const m of [latest, start, rerun, decide, add, signOff]) m.mockReset();
});

const renderScreen = () =>
  render(
    <ToastProvider>
      <UnderwritingCopilotWorkspace cases={mockCases.filter((c) => c.id === DANIEL_CASE_ID)} pillarSlug="underwriting" />
    </ToastProvider>,
  );

describe("UnderwritingCopilotWorkspace while loading", () => {
  it("shows skeletons until the answer comes, and not the 'not run yet' message", () => {
    latest.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the underwriting report" })).toBeInTheDocument();
    expect(screen.queryByText(/No underwriting report yet/)).not.toBeInTheDocument();
  });
});

describe("UnderwritingCopilotWorkspace when something goes wrong", () => {
  it("treats a 404 before the first run as normal, not an error", async () => {
    latest.mockRejectedValue(new ApiError(404, "No report yet"));
    renderScreen();
    expect(await screen.findByText(/No underwriting report yet for/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when the report cannot be loaded, and Try again loads it", async () => {
    latest.mockRejectedValueOnce(new ApiError(500, "Server error")).mockResolvedValue(finished());
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Case snapshot" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("when starting fails, says why and Try again starts again", async () => {
    latest.mockRejectedValue(new ApiError(404, "No report yet"));
    start.mockRejectedValueOnce(new ApiError(404, "Starting the underwriting copilot is not available on this backend yet: the agents are still to come.")).mockResolvedValue(undefined);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run copilot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not available on this backend yet");
    latest.mockResolvedValue(working());
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(start).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("list", { name: "Agent progress" })).toBeInTheDocument();
  });

  it("waits out a 404 straight after starting, then shows the agents and the report", async () => {
    latest.mockRejectedValueOnce(new ApiError(404, "No report yet")); // the first look, before any run
    start.mockResolvedValue(undefined);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run copilot" }));
    latest.mockRejectedValueOnce(new ApiError(404, "Nothing written yet")).mockResolvedValueOnce(working()).mockResolvedValue(finished());
    expect(await screen.findByRole("heading", { name: "Case snapshot" }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  }, 15000);

  it("shows an error when checking the agents' progress fails", async () => {
    latest.mockRejectedValueOnce(new ApiError(404, "No report yet"));
    start.mockResolvedValue(undefined);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run copilot" }));
    latest.mockRejectedValue(new ApiError(500, "Could not read the run"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not read the run");
    expect(screen.getByRole("button", { name: "Run copilot" })).toBeEnabled(); // not stuck
  });

  it("when accepting a condition fails, the screen stays as it was and a message offers Try again", async () => {
    latest.mockResolvedValue(finished());
    decide.mockRejectedValueOnce(new ApiError(409, "The agents are still working.")).mockResolvedValue(finished());
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Accept condition 1" }));
    expect(await screen.findByText("The agents are still working.")).toBeInTheDocument();
    expect(screen.getAllByText("Not reviewed")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(decide).toHaveBeenCalledTimes(2));
    expect(decide).toHaveBeenLastCalledWith(DANIEL_CASE_ID, "uwc-1", { decision: "accepted" });
  });

  it("when a rejection fails, the window stays open with the message and what was typed", async () => {
    latest.mockResolvedValue(finished());
    decide.mockRejectedValue(new ApiError(422, "A rejection needs a reason."));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Reject condition 2" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "keep this" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject condition" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("A rejection needs a reason.");
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("keep this");
  });

  it("when adding a condition fails, the window stays open", async () => {
    latest.mockResolvedValue(finished());
    add.mockRejectedValue(new ApiError(422, "A condition needs text."));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Add condition" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "x" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add condition" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("A condition needs text.");
  });

  it("when the sign-off fails, the message sits in the sign-off bar and the note is kept", async () => {
    const reviewed = finished();
    reviewed.conditions = reviewed.conditions.map((c) => ({ ...c, decision: "accepted" as const })); // sign-off waits for a decision on each
    latest.mockResolvedValue(reviewed);
    signOff.mockRejectedValue(new ApiError(403, "Your role cannot review this report"));
    renderScreen();
    await screen.findByRole("heading", { name: "Sign off review" });
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "keep me" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    expect(await screen.findByText("Your role cannot review this report")).toBeInTheDocument();
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("keep me");
  });

  it("when re-running the Critic fails, a message offers Try again and the Critic stays failed", async () => {
    latest.mockResolvedValue(finished(true));
    rerun.mockRejectedValueOnce(new ApiError(404, "Re-running an agent is not available on this backend yet: the agents are still to come.")).mockResolvedValue(undefined);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Re-run the Critic" }));
    expect(await screen.findByText(/Re-running an agent is not available on this backend yet/)).toBeInTheDocument();
    expect(within(screen.getByTestId("agent-critic")).getByText("Failed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledTimes(2));
    expect(rerun).toHaveBeenLastCalledWith(DANIEL_CASE_ID, "critic");
  });

  it("shows the answer as the backend gave it after a decision, replacing what was there", async () => {
    const before = finished();
    const after = structuredClone(before);
    after.conditions[0] = { ...after.conditions[0], decision: "accepted", decided_by: "u-1", decided_at: "2026-11-24T10:00:00Z" };
    latest.mockResolvedValue(before);
    decide.mockResolvedValue(after);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Accept condition 1" }));
    await waitFor(() => expect(within(screen.getByTestId("condition-uwc-1")).getByText("Accepted")).toBeInTheDocument());
    expect(screen.getByText("Accepted by u-1 on 24 Nov 2026")).toBeInTheDocument();
  });
});
