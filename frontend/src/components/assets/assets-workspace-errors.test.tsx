import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { buildDanielAssets, DANIEL_SCENARIO, type AssetRun } from "@/mocks/assets";
import { DANIEL_CASE_ID, mockCases } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getLoanScenario: vi.fn(),
  putLoanScenario: vi.fn(),
  getLatestAssetAnalysis: vi.fn(),
  runAssetAnalysis: vi.fn(),
  reviewObligation: vi.fn(),
  reviewTransaction: vi.fn(),
  getJob: vi.fn(),
}));
import {
  getJob,
  getLatestAssetAnalysis,
  getLoanScenario,
  putLoanScenario,
  reviewObligation,
  reviewTransaction,
  runAssetAnalysis,
} from "@/lib/api";
import { AssetsWorkspace } from "./assets-workspace";

const scenarioApi = vi.mocked(getLoanScenario);
const saveScenario = vi.mocked(putLoanScenario);
const latest = vi.mocked(getLatestAssetAnalysis);
const run = vi.mocked(runAssetAnalysis);
const job = vi.mocked(getJob);
const decide = vi.mocked(reviewObligation);
const review = vi.mocked(reviewTransaction);

const RUN: AssetRun = { scenario: DANIEL_SCENARIO, candidate_monthly: "5980.00", overtime_monthly: "444.41" };
const analysis = () => buildDanielAssets(RUN, "2026-11-23T09:00:00.000Z");
const saved = { ...DANIEL_SCENARIO, updated_at: "2026-11-23T08:00:00.000Z" };

beforeEach(() => {
  for (const m of [scenarioApi, saveScenario, latest, run, job, decide, review]) m.mockReset();
});

const renderScreen = () => render(<AssetsWorkspace cases={mockCases.filter((c) => c.id === DANIEL_CASE_ID)} pillarSlug="underwriting" />);

describe("AssetsWorkspace while loading", () => {
  it("shows skeletons for the scenario and the tables until the answers come", () => {
    scenarioApi.mockReturnValue(new Promise(() => {}));
    latest.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the loan scenario" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading the asset analysis" })).toBeInTheDocument();
    expect(screen.queryByText(/No asset analysis yet/)).not.toBeInTheDocument();
  });
});

describe("AssetsWorkspace when something goes wrong", () => {
  it("treats a 404 for the scenario and the result as normal: nothing entered, nothing run", async () => {
    scenarioApi.mockRejectedValue(new ApiError(404, "No loan scenario"));
    latest.mockRejectedValue(new ApiError(404, "No analysis"));
    renderScreen();
    expect(await screen.findByText(/No asset analysis yet for/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Save the loan scenario first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeDisabled();
  });

  it("shows an error when the scenario or result cannot be loaded, and Try again loads them", async () => {
    scenarioApi.mockRejectedValueOnce(new ApiError(500, "Server error"));
    latest.mockRejectedValueOnce(new ApiError(404, "none"));
    scenarioApi.mockResolvedValue(saved);
    latest.mockResolvedValue(analysis());
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("figure-dti")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error and re-enables Run when the run cannot start, and Try again runs it again", async () => {
    scenarioApi.mockResolvedValue(saved);
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockRejectedValueOnce(new ApiError(503, "The service is busy"));
    run.mockResolvedValue({ id: "j1", status: "queued", progress: 0 } as never);
    job.mockResolvedValue({ id: "j1", status: "running", progress: 0.3 } as never);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The service is busy");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows the job's error when the analysis fails", async () => {
    scenarioApi.mockResolvedValue(saved);
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockResolvedValue({ id: "j1", status: "queued", progress: 0 } as never);
    job.mockResolvedValue({ id: "j1", status: "failed", progress: 0.5, error: "No bank statements" } as never);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The analysis failed: No bank statements");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("keeps the form's values and shows the message when saving the scenario is refused", async () => {
    scenarioApi.mockResolvedValue(saved);
    latest.mockResolvedValue(analysis());
    saveScenario.mockRejectedValue(new ApiError(422, "Property value must be more than zero"));
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.change(screen.getByLabelText("Funds needed to close"), { target: { value: "40000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Property value must be more than zero");
    expect(screen.getByLabelText("Funds needed to close")).toHaveValue("40000.00");
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // nothing was saved, so no "saved after" note
  });

  it("keeps the window open with the message when a decision is refused, and changes nothing", async () => {
    scenarioApi.mockResolvedValue(saved);
    latest.mockResolvedValue(analysis());
    decide.mockRejectedValue(new ApiError(422, "A reason is required"));
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.click(screen.getByRole("button", { name: "Exclude Northgate Card" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Exclude from DTI" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(decide).toHaveBeenCalledWith(DANIEL_CASE_ID, analysis().obligations[0].id, { counts_toward_dti: false, reason: "x" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("44.70%")).toBeInTheDocument();
  });

  it("keeps the window open with the message when a reclassification is refused", async () => {
    scenarioApi.mockResolvedValue(saved);
    latest.mockResolvedValue(analysis());
    review.mockRejectedValue(new ApiError(422, "Unknown category"));
    renderScreen();
    await screen.findByTestId("figure-dti");
    fireEvent.click(screen.getAllByRole("button", { name: /^Reclassify TARGET T-1124/ })[0]);
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "r" } });
    fireEvent.click(screen.getByRole("button", { name: "Save category" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown category");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
