import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { ANGELA_CASE_ID, mockCases } from "@/mocks/data";
import { buildAngelaHardship } from "@/mocks/hardship";

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

const renderScreen = () => render(<HardshipWorkspace cases={mockCases.filter((c) => c.id === ANGELA_CASE_ID)} pillarSlug="loss-mitigation" />);

describe("HardshipWorkspace when something goes wrong", () => {
  it("treats a 404 before the first run as normal, not as an error", async () => {
    latest.mockRejectedValue(new ApiError(404, "No assessment yet"));
    renderScreen();
    expect(await screen.findByText(/No hardship analysis yet for/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when the latest result cannot be loaded", async () => {
    latest.mockRejectedValue(new ApiError(500, "Server error"));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
  });

  it("shows an error and re-enables Run when the run cannot start", async () => {
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockRejectedValue(new ApiError(503, "The service is busy"));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The service is busy");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
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
