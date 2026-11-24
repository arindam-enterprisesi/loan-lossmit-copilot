import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/shared/toast";
import { ApiError } from "@/lib/api-error";
import { recommendationAt, startRun } from "@/mocks/copilot";
import { ANGELA_CASE_ID, mockCases } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getLatestLmRecommendation: vi.fn(),
  runLmRecommendation: vi.fn(),
  rerunLmAgent: vi.fn(),
  overrideLmCondition: vi.fn(),
  addLmAnnotation: vi.fn(),
  signOffLm: vi.fn(),
  getGuidelinePassage: vi.fn(),
  getJob: vi.fn(),
}));
import { addLmAnnotation, getLatestLmRecommendation, overrideLmCondition, rerunLmAgent, runLmRecommendation, signOffLm } from "@/lib/api";
import { RecommendationWorkspace } from "./recommendation-workspace";

const latest = vi.mocked(getLatestLmRecommendation);
const start = vi.mocked(runLmRecommendation);
const rerun = vi.mocked(rerunLmAgent);
const override = vi.mocked(overrideLmCondition);
const signOff = vi.mocked(signOffLm);
const annotate = vi.mocked(addLmAnnotation);

const NOW = Date.now();
const finished = (criticFails = false) => recommendationAt(startRun("lm", ANGELA_CASE_ID, 0, criticFails), NOW);
/** The agents are still working, but the rules and the lender view are already there. */
const working = () => recommendationAt(startRun("lm", ANGELA_CASE_ID, NOW, false), NOW);

beforeEach(() => {
  for (const m of [latest, start, rerun, override, signOff, annotate]) m.mockReset();
});

const renderScreen = () =>
  render(
    <ToastProvider>
      <RecommendationWorkspace cases={mockCases.filter((c) => c.id === ANGELA_CASE_ID)} />
    </ToastProvider>,
  );

describe("RecommendationWorkspace while loading", () => {
  it("shows skeletons until the answer comes, and not the 'not run yet' message", () => {
    latest.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the recommendation" })).toBeInTheDocument();
    expect(screen.queryByText(/No recommendation yet/)).not.toBeInTheDocument();
  });
});

describe("RecommendationWorkspace when something goes wrong", () => {
  it("treats a 404 before the first run as normal", async () => {
    latest.mockRejectedValue(new ApiError(404, "No recommendation yet"));
    renderScreen();
    expect(await screen.findByText(/No recommendation yet for/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when it cannot be loaded, and Try again loads it", async () => {
    latest.mockRejectedValueOnce(new ApiError(503, "Storage is down")).mockResolvedValue(finished());
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage is down");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("lender-advantage")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("when starting fails, says the agents are still to come, and Try again starts again", async () => {
    latest.mockRejectedValue(new ApiError(404, "No recommendation yet"));
    start
      .mockRejectedValueOnce(new ApiError(404, "Starting the recommendation is not available on this backend yet: the agents are still to come."))
      .mockResolvedValue(undefined);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run recommendation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not available on this backend yet");
    latest.mockResolvedValue(working());
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(start).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("lender-advantage")).toBeInTheDocument();
  });

  it("shows the rules' results while the agents work, even though there is no report yet", async () => {
    latest.mockResolvedValue(working());
    renderScreen();
    expect(await screen.findByTestId("option-loan_modification")).toHaveAttribute("data-status", "met");
    expect(screen.getByText("Writing the report")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign off review" })).not.toBeInTheDocument();
  });

  it("when an override fails, the window stays open with the message and what was typed", async () => {
    latest.mockResolvedValue(finished());
    override.mockRejectedValue(new ApiError(422, "This condition follows from the options before it and cannot be overridden."));
    renderScreen();
    await screen.findByTestId("option-forbearance");
    fireEvent.click(screen.getByRole("button", { name: "Show conditions for Forbearance" }));
    fireEvent.click(screen.getByRole("button", { name: "Override Hardship temporary (confirmed)" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "met" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "keep this" } });
    fireEvent.click(screen.getByRole("button", { name: "Save override" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("cannot be overridden");
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("keep this");
    expect(screen.getByTestId("option-forbearance")).toHaveAttribute("data-status", "not_met"); // nothing changed
  });

  it("shows the recomputed answer the backend sends after an override, replacing what was there", async () => {
    const before = finished();
    const after = structuredClone(before);
    const forb = after.waterfall.find((o) => o.option === "forbearance")!;
    forb.status = "met";
    forb.overridden = true;
    forb.conditions[0].effective_status = "met";
    forb.conditions[0].override = { status: "met", reason: "Employer confirmed", by: "u-1", at: "2026-11-24T10:00:00Z" };
    for (const o of after.waterfall.filter((x) => x.order_no > 2)) o.status = "not_reached";
    latest.mockResolvedValue(before);
    override.mockResolvedValue(after);
    renderScreen();
    await screen.findByTestId("option-forbearance");
    fireEvent.click(screen.getByRole("button", { name: "Show conditions for Forbearance" }));
    fireEvent.click(screen.getByRole("button", { name: "Override Hardship temporary (confirmed)" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "met" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer confirmed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save override" }));
    await waitFor(() => expect(screen.getByTestId("option-forbearance")).toHaveAttribute("data-status", "met"));
    expect(override).toHaveBeenCalledWith(ANGELA_CASE_ID, "forbearance.hardship_temporary", { status: "met", reason: "Employer confirmed" });
    expect(screen.getByTestId("option-loan_modification")).toHaveAttribute("data-status", "not_reached");
  });

  it("when adding a note fails, the message sits in the note box and what was typed is kept", async () => {
    latest.mockResolvedValue(finished());
    annotate.mockRejectedValue(new ApiError(404, "Adding a note is not available on this backend yet."));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Add a note on Lender view" }));
    fireEvent.change(screen.getByLabelText("Note on Lender view"), { target: { value: "keep this note" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Adding a note is not available on this backend yet.");
    expect(screen.getByLabelText("Note on Lender view")).toHaveValue("keep this note");
  });

  it("when the sign-off fails, the message sits in the sign-off bar", async () => {
    latest.mockResolvedValue(finished());
    signOff.mockRejectedValue(new ApiError(403, "Your role cannot review this report"));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Sign off review" }));
    expect(await screen.findByText("Your role cannot review this report")).toBeInTheDocument();
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
    expect(rerun).toHaveBeenLastCalledWith(ANGELA_CASE_ID, "critic");
  });
});
