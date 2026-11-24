import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import type { AuditEvent, AuditPage } from "@/lib/audit-types";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases } from "@/mocks/data";

// The mock trail always answers well, so loading, paging and failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({ USE_MOCKS: true, listCaseAudit: vi.fn() }));
import { listCaseAudit } from "@/lib/api";
import { HitlWorkspace } from "./hitl-workspace";

const list = vi.mocked(listCaseAudit);

const ev = (id: number, over: Partial<AuditEvent> = {}): AuditEvent => ({
  id,
  at: "2026-11-24T10:30:00Z",
  actor_name: "demo.reviewer",
  role: "underwriter",
  action: "field.corrected",
  entity_type: "field",
  entity_id: null,
  before: null,
  after: null,
  reason: null,
  ...over,
});
const page = (items: AuditEvent[], next_before: number | null = null): AuditPage => ({ items, next_before });

beforeEach(() => {
  list.mockReset();
});

const renderScreen = (cases = mockCases) => render(<HitlWorkspace cases={cases} />);
const rows = () => screen.getAllByTestId(/^audit-/);

describe("HitlWorkspace while loading", () => {
  it("shows a table skeleton until the answer comes, and not the empty message", () => {
    list.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(screen.getByRole("status", { name: "Loading the actions" })).toBeInTheDocument();
    expect(screen.queryByText(/No review actions yet/)).not.toBeInTheDocument();
  });
});

describe("HitlWorkspace with actions", () => {
  it("lists each action newest first with when, who, what and why", async () => {
    list.mockResolvedValue(
      page([
        ev(3, { action: "report.signed_off", entity_type: "report", reason: "Looks complete", at: "2026-11-24T12:00:00Z" }),
        ev(2, { action: "underwriting.condition_rejected", entity_type: "condition", reason: "Not needed", actor_name: "A. Reviewer" }),
        ev(1, { action: "field.corrected", before: { value: "2083.61" }, after: { value: "2033.61" }, reason: "Printed net pay was wrong" }),
      ]),
    );
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    expect(rows().map((r) => r.getAttribute("data-testid"))).toEqual(["audit-3", "audit-2", "audit-1"]);
    const first = within(rows()[0]);
    expect(first.getByText("24 Nov 2026, 12:00 UTC")).toBeInTheDocument();
    expect(first.getByText("Review signed off")).toBeInTheDocument();
    expect(first.getByText("Report")).toBeInTheDocument();
    expect(first.getByText("Looks complete")).toBeInTheDocument();
    expect(within(rows()[1]).getByText("A. Reviewer")).toBeInTheDocument();
    expect(screen.getByText("3 actions shown. That is all of them.")).toBeInTheDocument();
  });

  it("opens 'What changed' to show the value before and after", async () => {
    list.mockResolvedValue(page([ev(1, { before: { value: "2083.61" }, after: { value: "2033.61" } })]));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    const row = within(rows()[0]);
    expect(row.getByText("What changed")).toBeInTheDocument();
    expect(row.getByText("2083.61")).toBeInTheDocument();
    expect(row.getByText("2033.61")).toBeInTheDocument();
  });

  it("shows a missing reason as a dash and a system step as System", async () => {
    list.mockResolvedValue(page([ev(1, { actor_name: null, role: "system", action: "document.classified", reason: null })]));
    renderScreen();
    fireEvent.change(await screen.findByLabelText("Show"), { target: { value: "all" } });
    await waitFor(() => expect(within(rows()[0]).getAllByText("System")).toHaveLength(2)); // as the actor, and as the role
    expect(within(rows()[0]).getByText("—")).toBeInTheDocument();
  });
});

describe("HitlWorkspace review actions and automatic steps", () => {
  it("hides the system's automatic steps by default, and shows them when asked", async () => {
    list.mockResolvedValue(
      page([
        ev(3, { action: "report.signed_off", entity_type: "report" }),
        ev(2, { action: "document.extracted", entity_type: "document", actor_name: null, role: "system" }),
        ev(1, { action: "income.analysed", entity_type: "analysis_run", actor_name: null, role: "system" }),
      ]),
    );
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    expect(rows()).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "all" } });
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(within(screen.getByRole("table")).getByText("Values extracted")).toBeInTheDocument();
  });

  it("only offers review actions in the Action filter until all activity is chosen", async () => {
    list.mockResolvedValue(page([ev(1)]));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    const options = () => within(screen.getByLabelText("Action")).getAllByRole("option").map((o) => o.textContent);
    expect(options()).toContain("Value corrected");
    expect(options()).not.toContain("Values extracted");
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "all" } });
    expect(options()).toContain("Values extracted");
  });

  it("keeps reading older pages when a page holds only automatic steps, so the person is not shown a blank", async () => {
    list
      .mockResolvedValueOnce(page([ev(5, { action: "document.extracted", actor_name: null, role: "system" })], 5))
      .mockResolvedValueOnce(page([ev(4, { action: "field.confirmed", reason: null })], null));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    expect(rows()).toHaveLength(1);
    expect(list).toHaveBeenCalledTimes(2);
    expect(list.mock.calls[1][1]).toMatchObject({ before: 5 });
  });
});

describe("HitlWorkspace filters", () => {
  it("sends the chosen action and entity to the API, and reads again", async () => {
    list.mockResolvedValue(page([ev(1)]));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "field.corrected" } });
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(DANIEL_CASE_ID, expect.objectContaining({ action: "field.corrected" })));
    fireEvent.change(screen.getByLabelText("What it was done to"), { target: { value: "field" } });
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(DANIEL_CASE_ID, expect.objectContaining({ action: "field.corrected", entity_type: "field" })));
  });

  it("says nothing matches when a filter finds nothing, and Clear filters brings the list back", async () => {
    list.mockImplementation(async (_id, q) => (q?.action ? page([]) : page([ev(1)])));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "report.signed_off" } });
    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await screen.findAllByTestId(/^audit-/);
    expect(screen.queryByText("Nothing matches")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("reads the other case when the case is changed", async () => {
    list.mockResolvedValue(page([ev(1)]));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(ANGELA_CASE_ID, expect.anything()));
  });

  it("ignores a slow answer for the case that was left", async () => {
    let finishFirst: (p: AuditPage) => void = () => {};
    list.mockImplementationOnce(() => new Promise((resolve) => (finishFirst = resolve)));
    list.mockResolvedValueOnce(page([ev(20, { reason: "From Angela's case" })]));
    renderScreen();
    fireEvent.change(await screen.findByLabelText("Case"), { target: { value: ANGELA_CASE_ID } });
    await screen.findByText("From Angela's case");
    finishFirst(page([ev(10, { reason: "From Daniel's case" })]));
    await waitFor(() => expect(screen.queryByText("From Daniel's case")).not.toBeInTheDocument());
    expect(screen.getByText("From Angela's case")).toBeInTheDocument();
  });
});

describe("HitlWorkspace paging", () => {
  it("loads older actions when there are more, and stops offering it at the end", async () => {
    list.mockResolvedValueOnce(page([ev(3), ev(2)], 2)).mockResolvedValueOnce(page([ev(1)], null));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    expect(screen.getByText("2 actions shown.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load older actions" }));
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(list).toHaveBeenLastCalledWith(DANIEL_CASE_ID, expect.objectContaining({ before: 2 }));
    expect(rows().map((r) => r.getAttribute("data-testid"))).toEqual(["audit-3", "audit-2", "audit-1"]);
    expect(screen.queryByRole("button", { name: "Load older actions" })).not.toBeInTheDocument();
    expect(screen.getByText("3 actions shown. That is all of them.")).toBeInTheDocument();
  });
});

describe("HitlWorkspace when nothing has happened or something goes wrong", () => {
  it("says what to expect when there are no review actions yet", async () => {
    list.mockResolvedValue(page([]));
    renderScreen();
    expect(await screen.findByText("No review actions yet")).toBeInTheDocument();
    expect(screen.getByText(/Each of those appears here as it happens/)).toBeInTheDocument();
  });

  it("shows an error with Try again, and loads the list on a second try", async () => {
    list.mockRejectedValueOnce(new ApiError(500, "Server error")).mockResolvedValue(page([ev(1)]));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    expect(screen.queryByRole("status", { name: "Loading the actions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findAllByTestId(/^audit-/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps what is shown and offers Try again when loading older actions fails", async () => {
    list.mockResolvedValueOnce(page([ev(3)], 3)).mockRejectedValueOnce(new ApiError(503, "Busy")).mockResolvedValueOnce(page([ev(2)], null));
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    fireEvent.click(screen.getByRole("button", { name: "Load older actions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Busy");
    expect(rows()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(rows()).toHaveLength(2));
  });

  it("never shows the words a person alone may decide with", async () => {
    list.mockResolvedValue(
      page([ev(2, { action: "report.signed_off", entity_type: "report" }), ev(1, { action: "lm.condition_overridden", entity_type: "waterfall_condition" })]),
    );
    renderScreen();
    await screen.findAllByTestId(/^audit-/);
    expect(document.body.textContent).not.toMatch(/approv|deny|denied|eligib|qualif|\boffer/i);
  });
});
