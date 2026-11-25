import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { buildCompleteness } from "@/mocks/completeness";
import { ANGELA_CASE_ID } from "@/mocks/data";

// The mock backend always answers well, so failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({
  getLatestCompleteness: vi.fn(),
  runCompleteness: vi.fn(),
  overrideCompletenessItem: vi.fn(),
}));
import { getLatestCompleteness, overrideCompletenessItem, runCompleteness } from "@/lib/api";
import { CompletenessPanel } from "./completeness-panel";

const latest = vi.mocked(getLatestCompleteness);
const run = vi.mocked(runCompleteness);
const override = vi.mocked(overrideCompletenessItem);

beforeEach(() => {
  latest.mockReset();
  run.mockReset();
  override.mockReset();
});

const angelaResult = () =>
  buildCompleteness(ANGELA_CASE_ID, "pillar2-hardship@1", "2026-11-20T09:00:00.000Z", "c1");
const renderPanel = () =>
  render(<CompletenessPanel caseId={ANGELA_CASE_ID} pillarSlug="loss-mitigation" section="document-intake" />);

describe("CompletenessPanel when something goes wrong", () => {
  it("treats a 404 before the first run as normal, not as an error", async () => {
    latest.mockRejectedValue(new ApiError(404, "No result yet"));
    renderPanel();
    expect(await screen.findByText(/No completeness result yet/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when the latest result cannot be loaded", async () => {
    latest.mockRejectedValue(new ApiError(500, "Server error"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
  });

  it("shows the message and lets the user try again when the run fails", async () => {
    latest.mockRejectedValue(new ApiError(404, "none"));
    run.mockRejectedValue(new ApiError(422, "Unknown checklist"));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Run checklist" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown checklist");
    expect(screen.getByRole("button", { name: "Run checklist" })).toBeEnabled();
    expect(run).toHaveBeenCalledWith(ANGELA_CASE_ID, "pillar2-hardship@1");
  });

  it("keeps the window open with the backend's message when an override is refused, and changes nothing", async () => {
    latest.mockResolvedValue(angelaResult());
    override.mockRejectedValue(new ApiError(422, "A reason is required"));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Override Bank statements covering 2 months" }));
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Statement requested" } });
    fireEvent.click(screen.getByRole("button", { name: "Override item" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required");
    expect(override).toHaveBeenCalledWith(ANGELA_CASE_ID, "bank_statement_2026-08", "Statement requested");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Statement requested");
    expect(screen.getByText("Incomplete")).toBeInTheDocument();
  });
});
