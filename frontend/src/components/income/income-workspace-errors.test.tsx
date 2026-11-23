import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { mockCases } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getLatestIncome: vi.fn(),
  runIncomeAnalysis: vi.fn(),
  getJob: vi.fn(),
  setIncomeComponent: vi.fn(),
}));
import { getJob, getLatestIncome, runIncomeAnalysis, setIncomeComponent } from "@/lib/api";
import { buildDanielIncome } from "@/mocks/income";
import { IncomeWorkspace } from "./income-workspace";

const latest = vi.mocked(getLatestIncome);
const run = vi.mocked(runIncomeAnalysis);
const job = vi.mocked(getJob);
const decide = vi.mocked(setIncomeComponent);

beforeEach(() => {
  latest.mockReset();
  run.mockReset();
  job.mockReset();
  decide.mockReset();
});

const renderScreen = () => render(<IncomeWorkspace cases={mockCases.slice(0, 1)} pillarSlug="underwriting" />);

describe("IncomeWorkspace while loading", () => {
  it("shows a skeleton shaped like the table until the answer comes", () => {
    latest.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the income analysis" })).toBeInTheDocument();
    expect(screen.queryByText(/No income analysis yet/)).not.toBeInTheDocument();
  });
});

describe("IncomeWorkspace when something goes wrong", () => {
  it("treats a 404 before the first run as normal, not as an error", async () => {
    latest.mockRejectedValue(new ApiError(404, "No income analysis yet"));
    renderScreen();
    expect(await screen.findByText(/No income analysis yet for/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when the latest result cannot be loaded, and Try again loads it", async () => {
    latest.mockRejectedValueOnce(new ApiError(500, "Server error"));
    latest.mockResolvedValue(buildDanielIncome("2026-11-20T09:00:00.000Z"));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("candidate-row")).toBeInTheDocument();
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

  it("Try again after a failed run starts the analysis again", async () => {
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
    job.mockResolvedValue({ id: "j1", status: "failed", progress: 0.5, error: "Missing pay stub" });
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The analysis failed: Missing pay stub");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("keeps the dialog open with the backend's message when a decision is refused, and changes nothing", async () => {
    latest.mockResolvedValue(buildDanielIncome("2026-11-20T09:00:00.000Z"));
    decide.mockRejectedValue(new ApiError(422, "A reason is required"));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Include Overtime (1.5x)" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Employer letter" } });
    fireEvent.click(screen.getByRole("button", { name: "Include in candidate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(decide).toHaveBeenCalledWith(expect.any(String), "overtime", { included: true, reason: "Employer letter" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Employer letter");
    expect(screen.getByTestId("candidate-row")).toHaveTextContent("5,980.00");
  });
});
