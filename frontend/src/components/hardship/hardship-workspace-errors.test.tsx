import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/shared/toast";
import { ApiError } from "@/lib/api-error";
import { ANGELA_CASE_ID, mockCases } from "@/mocks/data";
import { applyConfirmation, buildAngelaHardship } from "@/mocks/hardship";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getLatestHardship: vi.fn(),
  runHardshipAssessment: vi.fn(),
  getJob: vi.fn(),
  confirmProfileItem: vi.fn(),
  adjustBudgetItem: vi.fn(),
}));
import { adjustBudgetItem, confirmProfileItem, getJob, getLatestHardship, runHardshipAssessment } from "@/lib/api";
import { HardshipWorkspace } from "./hardship-workspace";

const latest = vi.mocked(getLatestHardship);
const run = vi.mocked(runHardshipAssessment);
const job = vi.mocked(getJob);
const confirm = vi.mocked(confirmProfileItem);
const adjust = vi.mocked(adjustBudgetItem);

beforeEach(() => {
  latest.mockReset();
  run.mockReset();
  job.mockReset();
  confirm.mockReset();
  adjust.mockReset();
});

const renderScreen = () =>
  render(
    <ToastProvider>
      <HardshipWorkspace cases={mockCases.filter((c) => c.id === ANGELA_CASE_ID)} pillarSlug="loss-mitigation" />
    </ToastProvider>,
  );

describe("HardshipWorkspace while loading", () => {
  it("shows skeletons for the letter, the profile and the checks until the answer comes", () => {
    latest.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the letter" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading the profile" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading the checks" })).toBeInTheDocument();
  });
});

describe("HardshipWorkspace when something goes wrong", () => {
  it("treats a 404 before the first run as normal, not as an error", async () => {
    latest.mockRejectedValue(new ApiError(404, "No assessment yet"));
    renderScreen();
    expect(await screen.findByText(/No hardship analysis yet for/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when the latest result cannot be loaded, and Try again loads it", async () => {
    latest.mockRejectedValueOnce(new ApiError(500, "Server error"));
    latest.mockResolvedValue(buildAngelaHardship("2026-11-20T09:00:00.000Z"));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Hardship profile" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error and re-enables Run when the run cannot start", async () => {
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockRejectedValue(new ApiError(503, "The service is busy"));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The service is busy");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("Try again after a failed start runs the analysis again", async () => {
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockRejectedValueOnce(new ApiError(503, "The service is busy"));
    run.mockResolvedValue({ id: "j1", status: "queued", progress: 0 });
    job.mockResolvedValue({ id: "j1", status: "running", progress: 0.3 });
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows the job's error when the analysis fails, and re-enables Run", async () => {
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockResolvedValue({ id: "j1", status: "queued", progress: 0 });
    job.mockResolvedValue({ id: "j1", status: "failed", progress: 0.5, error: "Letter unreadable" });
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The analysis failed: Letter unreadable");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("shows the message when Confirm fails, and leaves the item not reviewed", async () => {
    latest.mockResolvedValue(buildAngelaHardship("2026-11-20T09:00:00.000Z"));
    confirm.mockRejectedValue(new ApiError(503, "Could not save"));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Confirm Intent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(within(screen.getByRole("article", { name: "Intent" })).getByText("Not reviewed")).toBeInTheDocument();
  });

  it("Try again on a failed Confirm confirms the same item", async () => {
    latest.mockResolvedValue(buildAngelaHardship("2026-11-20T09:00:00.000Z"));
    confirm.mockRejectedValueOnce(new ApiError(503, "Could not save"));
    confirm.mockResolvedValue(
      applyConfirmation(buildAngelaHardship("2026-11-20T09:00:00.000Z"), { key: "intent", action: "confirm" }, "demo.reviewer", "2026-11-20T10:00:00.000Z"),
    );
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Confirm Intent" }));
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
    expect(confirm).toHaveBeenLastCalledWith(ANGELA_CASE_ID, { key: "intent", action: "confirm" });
    expect(await within(screen.getByRole("article", { name: "Intent" })).findByText("Reviewer-confirmed")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the window open with the message when a correction is refused", async () => {
    latest.mockResolvedValue(buildAngelaHardship("2026-11-20T09:00:00.000Z"));
    confirm.mockRejectedValue(new ApiError(422, "A reason is required"));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Correct Duration" }));
    fireEvent.change(screen.getByLabelText("Correct value"), { target: { value: "long_term" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer letter" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(confirm).toHaveBeenCalledWith(ANGELA_CASE_ID, {
      key: "duration",
      action: "correct",
      value: "long_term",
      reason: "Employer letter",
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Employer letter");
    // The window hides the page from assistive technology, so look the card up with hidden: true.
    expect(within(screen.getByRole("article", { name: "Duration", hidden: true })).getByText("Unknown")).toBeInTheDocument();
  });

  it("keeps the window open with the message when an adjustment is refused, and changes nothing", async () => {
    latest.mockResolvedValue(buildAngelaHardship("2026-11-20T09:00:00.000Z"));
    adjust.mockRejectedValue(new ApiError(422, "Enter an amount such as 200.00"));
    renderScreen();
    await screen.findByRole("heading", { name: "Hardship profile" });
    fireEvent.click(screen.getByRole("tab", { name: "Budget" }));
    fireEvent.click(await screen.findByRole("button", { name: "Adjust Other" }));
    fireEvent.change(screen.getByLabelText("Amount counted each month"), { target: { value: "200.00" } });
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "One-off" } });
    fireEvent.click(screen.getByRole("button", { name: "Adjust item" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an amount such as 200.00");
    expect(adjust).toHaveBeenCalledWith(ANGELA_CASE_ID, "other", { amount: "200.00", reason: "One-off" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(screen.getByTestId("measure-surplus")).getByText("-280.00")).toBeInTheDocument();
  });
});
