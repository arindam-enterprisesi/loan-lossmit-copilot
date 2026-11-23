import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { toIncomeAnalysis } from "@/lib/income-real";
import { realDanielIncome, SAMPLE_CANDIDATE_LABEL, SAMPLE_CASE_ID } from "@/lib/income-real-sample";
import { mockCases } from "@/mocks/data";

// The workspace is shown with the real answer by replacing the API layer.
vi.mock("@/lib/api", () => ({
  USE_MOCKS: true,
  getLatestIncome: vi.fn(),
  runIncomeAnalysis: vi.fn(),
  getJob: vi.fn(),
  setIncomeComponent: vi.fn(),
}));
import { getLatestIncome } from "@/lib/api";
import { IncomeFlagCard } from "./income-flag-card";
import { IncomeTable } from "./income-table";
import { IncomeWorkspace } from "./income-workspace";

const latest = vi.mocked(getLatestIncome);
beforeEach(() => {
  latest.mockReset();
});

const real = () => toIncomeAnalysis(realDanielIncome(), SAMPLE_CASE_ID);

describe("IncomeTable with the real answer", () => {
  const setup = (a = real()) => render(<IncomeTable analysis={a} pillarSlug="underwriting" />);

  it("shows a Working button on the monthly amount, which has working, and none on the plain amounts", () => {
    setup();
    const base = within(screen.getByTestId(`component-${real().components[0].id}`));
    expect(base.getByRole("button", { name: "Show working for Base pay (Cedar Valley Manufacturing), monthly" })).toBeInTheDocument();
    expect(base.queryByRole("button", { name: /current period/ })).not.toBeInTheDocument();
    expect(base.queryByRole("button", { name: /year to date/ })).not.toBeInTheDocument();
    expect(base.getByText("2,760.00")).toBeInTheDocument(); // the amount itself is still shown
    expect(base.getByText("52,440.00")).toBeInTheDocument();
  });

  it("shows a dash for an amount the backend did not send", () => {
    setup();
    const bonus = within(screen.getByTestId(`component-${real().components[2].id}`));
    expect(bonus.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("shows the candidate with the backend's own label, and its working", () => {
    setup();
    const row = within(screen.getByTestId("candidate-row"));
    expect(row.getByText("5,980.00")).toBeInTheDocument();
    expect(row.getByText(SAMPLE_CANDIDATE_LABEL)).toBeInTheDocument();
    expect(row.getByRole("button", { name: "Show working for Candidate monthly income" })).toBeInTheDocument();
  });

  it("shows why overtime is left out, in the backend's words", () => {
    setup();
    const overtime = within(screen.getByTestId(`component-${real().components[1].id}`));
    expect(overtime.getByText("Left out")).toBeInTheDocument();
    expect(overtime.getByText("Documented history covers 2026 only. 24 months are needed to count it.")).toBeInTheDocument();
  });

  it("shows a dash, and no working button, for a candidate the backend could not work out", () => {
    const raw = realDanielIncome();
    raw.candidate_monthly_income = null;
    raw.candidate = null;
    setup(toIncomeAnalysis(raw, SAMPLE_CASE_ID));
    const row = within(screen.getByTestId("candidate-row"));
    expect(row.getByText("—")).toBeInTheDocument();
    expect(row.queryByRole("button", { name: /Show working/ })).not.toBeInTheDocument();
  });
});

describe("IncomeFlagCard with the real answer", () => {
  it("shows the sentence, the backend's working, and links the evidence to the pay stub", () => {
    const flag = real().flags[2];
    render(<IncomeFlagCard flag={{ ...flag, evidence: real().flags[0].evidence }} caseId={SAMPLE_CASE_ID} pillarSlug="underwriting" />);
    expect(screen.getByText("Year-to-date overtime averages 233.19 per pay period, against 204.93 this period (difference 28.26).")).toBeInTheDocument();
    expect(screen.getByText("4,217.43 / 18.09 periods = 233.19")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overtime ytd" })).toHaveAttribute("href", expect.stringContaining(`/underwriting/document-intelligence/${SAMPLE_CASE_ID}/`));
    expect(screen.queryByLabelText("Suggested explanation")).not.toBeInTheDocument();
  });

  it("says when a flag has been dealt with, and nothing for an open one", () => {
    const flag = real().flags[0];
    const { rerender } = render(<IncomeFlagCard flag={{ ...flag, status: "resolved" }} caseId={SAMPLE_CASE_ID} pillarSlug="underwriting" />);
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    rerender(<IncomeFlagCard flag={{ ...flag, status: "overridden" }} caseId={SAMPLE_CASE_ID} pillarSlug="underwriting" />);
    expect(screen.getByText("Overridden")).toBeInTheDocument();
    rerender(<IncomeFlagCard flag={{ ...flag, status: "open" }} caseId={SAMPLE_CASE_ID} pillarSlug="underwriting" />);
    expect(screen.queryByText("Resolved")).not.toBeInTheDocument();
    expect(screen.queryByText("Overridden")).not.toBeInTheDocument();
  });
});

describe("IncomeWorkspace with the real answer", () => {
  const renderScreen = () => render(<IncomeWorkspace cases={mockCases.slice(0, 1)} pillarSlug="underwriting" />);

  it("shows the candidate, the checks and the trend that the backend sent as flags, and the flags as flags", async () => {
    latest.mockResolvedValue(real());
    renderScreen();
    expect(await within(await screen.findByTestId("candidate-row")).findByText("5,980.00")).toBeInTheDocument();
    expect(screen.getByText("Illustrative method")).toBeInTheDocument();
    expect(screen.getByText(/income-method@2026-11-19\.1 · run/)).toBeInTheDocument();
    expect(screen.getByTestId("check-INC-CHK-03:explained")).toBeInTheDocument();
    expect(screen.getByText("Gross pay rose 5.49% from 2024 (70,431.80) to 2025 (74,298.60).")).toBeInTheDocument();
    expect(screen.getAllByRole("article", { name: "Flag INC-W101" })).toHaveLength(2);
  });

  it("says plainly that possible explanations have not been generated, instead of leaving the flags bare", async () => {
    latest.mockResolvedValue(real());
    renderScreen();
    expect(await screen.findByTestId("explanations-note")).toHaveTextContent("Possible explanations have not been generated for these flags yet.");
  });

  it("shows the explanations, marked possible, once the backend sends them, and no note", async () => {
    const raw = realDanielIncome();
    raw.explanations = ["Overtime was paid for nine months, so the history is short."];
    raw.explanations_note = "";
    latest.mockResolvedValue(toIncomeAnalysis(raw, SAMPLE_CASE_ID));
    renderScreen();
    const section = await screen.findByRole("region", { name: "Possible explanations" });
    expect(within(section).getByText("possible — to be confirmed")).toBeInTheDocument();
    expect(within(section).getByText("Overtime was paid for nine months, so the history is short.")).toBeInTheDocument();
    expect(screen.queryByTestId("explanations-note")).not.toBeInTheDocument();
  });

  it("shows the backend's note as it is when it is not the usual one", async () => {
    const raw = realDanielIncome();
    raw.explanations_note = "explanation service unavailable";
    latest.mockResolvedValue(toIncomeAnalysis(raw, SAMPLE_CASE_ID));
    renderScreen();
    expect(await screen.findByTestId("explanations-note")).toHaveTextContent("explanation service unavailable");
  });

  it("shows no note when nothing is flagged", async () => {
    const raw = realDanielIncome();
    raw.flags = [];
    latest.mockResolvedValue(toIncomeAnalysis(raw, SAMPLE_CASE_ID));
    renderScreen();
    await screen.findByText("Nothing flagged.");
    expect(screen.queryByTestId("explanations-note")).not.toBeInTheDocument();
  });

  it("a 404 before the first run is still the normal empty state", async () => {
    latest.mockRejectedValue(new ApiError(404, "No income analysis has been run for this case"));
    renderScreen();
    expect(await screen.findByText(/No income analysis yet for/)).toBeInTheDocument();
  });
});
