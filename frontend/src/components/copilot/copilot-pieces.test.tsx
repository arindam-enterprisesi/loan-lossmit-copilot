import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentRun, Condition, Finding, SignOff } from "@/lib/copilot-types";
import { AgentSteps } from "./agent-steps";
import { ConditionsPanel } from "./conditions-panel";
import { ConflictCallout } from "./conflict-callout";
import { EvidenceLinks } from "./evidence-links";
import { FindingsList } from "./findings-list";
import { ReportNotices } from "./report-notices";
import { SignOffBar } from "./sign-off-bar";

const run = (agent: AgentRun["agent"], status: AgentRun["status"], over: Partial<AgentRun> = {}): AgentRun => ({
  agent,
  attempt: 1,
  status,
  summary: null,
  error: null,
  started_at: null,
  finished_at: null,
  ...over,
});

describe("AgentSteps", () => {
  it("lists the Researcher, Writer and Critic in order, each with its status", () => {
    render(<AgentSteps runs={[run("researcher", "done", { summary: "Looked things up." }), run("writer", "running")]} onRerun={vi.fn()} />);
    const steps = within(screen.getByRole("list", { name: "Agent progress" })).getAllByRole("listitem");
    expect(steps.map((s) => s.getAttribute("data-testid"))).toEqual(["agent-researcher", "agent-writer", "agent-critic"]);
    expect(within(steps[0]).getByText("Done")).toBeInTheDocument();
    expect(within(steps[0]).getByText("Looked things up.")).toBeInTheDocument();
    expect(within(steps[1]).getByText("Running")).toBeInTheDocument();
    expect(within(steps[2]).getByText("Waiting")).toBeInTheDocument(); // no row yet: waiting
  });

  it("says what each agent is for", () => {
    render(<AgentSteps runs={[]} onRerun={vi.fn()} />);
    expect(screen.getByText("Looks up the guidance that applies")).toBeInTheDocument();
    expect(screen.getByText("Drafts the report from the stored results")).toBeInTheDocument();
    expect(screen.getByText("Checks the draft against the evidence")).toBeInTheDocument();
  });

  it("offers Re-run only on a failed agent, with the reason it failed", () => {
    render(<AgentSteps runs={[run("researcher", "done"), run("writer", "done"), run("critic", "failed", { error: "The Critic did not answer in time." })]} onRerun={vi.fn()} />);
    expect(screen.getAllByRole("button", { name: /Re-run/ })).toHaveLength(1);
    const critic = within(screen.getByTestId("agent-critic"));
    expect(critic.getByText("Failed")).toBeInTheDocument();
    expect(critic.getByRole("alert")).toHaveTextContent("The Critic did not answer in time.");
    expect(critic.getByRole("button", { name: "Re-run the Critic" })).toBeEnabled();
  });

  it("re-runs that agent alone when Re-run is pressed", async () => {
    const onRerun = vi.fn().mockResolvedValue(undefined);
    render(<AgentSteps runs={[run("critic", "failed")]} onRerun={onRerun} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-run the Critic" }));
    await waitFor(() => expect(onRerun).toHaveBeenCalledWith("critic"));
    expect(onRerun).toHaveBeenCalledTimes(1);
  });

  it("is ready to try again after a re-run fails", async () => {
    const onRerun = vi.fn().mockRejectedValue(new Error("Re-running an agent is not available on this backend yet."));
    render(<AgentSteps runs={[run("critic", "failed")]} onRerun={onRerun} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-run the Critic" }));
    await waitFor(() => expect(onRerun).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "Re-run the Critic" })).toBeEnabled());
  });

  it("shows which attempt it is after a re-run", () => {
    render(<AgentSteps runs={[run("critic", "done", { attempt: 2 })]} onRerun={vi.fn()} />);
    expect(within(screen.getByTestId("agent-critic")).getByText("Attempt 2")).toBeInTheDocument();
    expect(within(screen.getByTestId("agent-writer")).queryByText(/Attempt/)).not.toBeInTheDocument();
  });
});

describe("EvidenceLinks", () => {
  it("links a calculation to the screen that shows it, and a document to its review screen with the lines", () => {
    render(
      <EvidenceLinks
        refs={[
          { kind: "calculation", id: "dti" },
          { kind: "document", id: "d1", line_ids: ["p1-L31", "p1-L32"] },
          { kind: "calculation", id: "months_since_late_payment" },
        ]}
        caseId="c1"
        pillarSlug="underwriting"
      />,
    );
    expect(screen.getByRole("link", { name: "DTI" })).toHaveAttribute("href", "/underwriting/assets-liabilities");
    expect(screen.getByRole("link", { name: "Document" })).toHaveAttribute("href", "/underwriting/document-intelligence/c1/d1");
    expect(screen.getByText(/lines p1-L31, p1-L32/)).toBeInTheDocument();
    expect(screen.getByText("Months since the late payment")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Months since the late payment" })).not.toBeInTheDocument();
  });

  it("opens a passage from a button when it is given a way to", () => {
    const open = vi.fn();
    render(<EvidenceLinks refs={[{ kind: "passage", id: "p1" }]} caseId="c1" pillarSlug="underwriting" onOpenPassage={open} />);
    fireEvent.click(screen.getByRole("button", { name: "Guideline passage" }));
    expect(open).toHaveBeenCalledWith("p1");
  });

  it("shows a passage as plain words without that, and nothing at all with no references", () => {
    const { container, rerender } = render(<EvidenceLinks refs={[{ kind: "passage", id: "p1" }]} caseId="c1" pillarSlug="underwriting" />);
    expect(screen.getByText("Guideline passage")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    rerender(<EvidenceLinks refs={[]} caseId="c1" pillarSlug="underwriting" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ReportNotices", () => {
  it("says nothing when there is nothing to say", () => {
    const { container } = render(<ReportNotices notice={null} criticMissing={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the seeded notice, that the Critic's check is not available, and anything extra", () => {
    render(<ReportNotices notice="Seeded sample: written by hand." criticMissing extra={["Written before the overrides."]} />);
    const notes = screen.getAllByRole("note");
    expect(notes).toHaveLength(3);
    expect(notes[0]).toHaveTextContent("Seeded sample: written by hand.");
    expect(notes[1]).toHaveTextContent("The Critic's check is not available");
    expect(notes[2]).toHaveTextContent("Written before the overrides.");
  });
});

const finding = (id: string, priority: Finding["priority"], title = id): Finding => ({
  id,
  priority,
  title,
  detail: `${title} detail`,
  evidence: [{ kind: "rule", id: "AL-W106" }],
});

describe("FindingsList", () => {
  it("groups findings by priority, most important first, with a count, and each finding shows its evidence", () => {
    render(
      <FindingsList
        findings={[finding("a", "information"), finding("b", "significant"), finding("c", "significant"), finding("d", "attention")]}
        caseId="c1"
        pillarSlug="underwriting"
      />,
    );
    const groups = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
    expect(groups).toEqual(["Significant findings", "Attention findings", "Information findings"]);
    const significant = within(screen.getByRole("region", { name: "Significant findings" }));
    expect(significant.getByText("2 findings")).toBeInTheDocument();
    expect(significant.getAllByRole("article")).toHaveLength(2);
    expect(within(screen.getByRole("region", { name: "Attention findings" })).getByText("1 finding")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Rule AL-W106" })).toHaveLength(4);
  });

  it("says that priority is the order to review in and not a verdict", () => {
    render(<FindingsList findings={[finding("a", "attention")]} caseId="c1" pillarSlug="underwriting" />);
    expect(screen.getByText(/Priority is the order to review in/)).toBeInTheDocument();
  });

  it("says when there are no findings", () => {
    render(<FindingsList findings={[]} caseId="c1" pillarSlug="underwriting" />);
    expect(screen.getByText("No findings.")).toBeInTheDocument();
  });
});

describe("ConflictCallout", () => {
  it("shows both values of a conflict side by side, the explanation, and where each came from", () => {
    render(
      <ConflictCallout
        caseId="c1"
        pillarSlug="underwriting"
        conflicts={[
          {
            title: "DTI changes with the treatment of overtime",
            detail: "The underwriter decides which income to use.",
            evidence: [{ kind: "calculation", id: "dti" }, { kind: "calculation", id: "dti_with_overtime" }],
            figures: [
              { label: "Overtime and bonus left out", value: "44.70%" },
              { label: "If overtime is counted", value: "41.61%" },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Conflicts between findings" })).toBeInTheDocument();
    const note = within(screen.getByRole("note"));
    expect(note.getByText("44.70%")).toBeInTheDocument();
    expect(note.getByText("41.61%")).toBeInTheDocument();
    expect(note.getByText("Overtime and bonus left out")).toBeInTheDocument();
    expect(note.getByText("The underwriter decides which income to use.")).toBeInTheDocument();
    expect(note.getByRole("link", { name: "DTI with overtime counted" })).toBeInTheDocument();
  });

  it("shows just the words when the sender gave no figures, and nothing when there is no conflict", () => {
    const { container, rerender } = render(
      <ConflictCallout caseId="c1" pillarSlug="underwriting" conflicts={[{ title: "T", detail: "Two readings differ.", evidence: [] }]} />,
    );
    expect(screen.getByText("Two readings differ.")).toBeInTheDocument();
    expect(screen.queryByRole("term")).not.toBeInTheDocument();
    rerender(<ConflictCallout caseId="c1" pillarSlug="underwriting" conflicts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

const signOff = (n: number, over: Partial<SignOff> = {}): SignOff => ({
  id: `s${n}`,
  report_version: n,
  signed_by: "demo.reviewer",
  role: "underwriter",
  signed_at: "2026-11-24T10:00:00Z",
  note: null,
  statement: "Records a review. Not a decision.",
  ...over,
});
const result = (over = {}) => ({ sign_off: signOff(1), report_status: "signed_off" as const, pending_conditions: 0, ...over });

describe("SignOffBar", () => {
  it("is 'Sign off review', with the line that it records a review and is not a decision", () => {
    render(<SignOffBar signOffs={[]} reportStatus="draft" onSignOff={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Sign off review" })).toBeInTheDocument();
    expect(screen.getByText("Records a review. Not a decision.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign off review" })).toBeEnabled();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("sends the trimmed note, then says the review was recorded and clears the note", async () => {
    const onSignOff = vi.fn().mockResolvedValue(result());
    render(<SignOffBar signOffs={[]} reportStatus="in_review" onSignOff={onSignOff} />);
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "  Looks complete  " } });
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    expect(await screen.findByText("Review recorded.")).toBeInTheDocument();
    expect(onSignOff).toHaveBeenCalledWith("Looks complete");
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("");
  });

  it("can sign off with no note", async () => {
    const onSignOff = vi.fn().mockResolvedValue(result());
    render(<SignOffBar signOffs={[]} reportStatus="draft" onSignOff={onSignOff} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    await screen.findByText("Review recorded.");
    expect(onSignOff).toHaveBeenCalledWith("");
  });

  it("says how many conditions were left unreviewed, before and after", async () => {
    const onSignOff = vi.fn().mockResolvedValue(result({ pending_conditions: 2 }));
    render(<SignOffBar signOffs={[]} reportStatus="draft" undecided={2} onSignOff={onSignOff} />);
    expect(screen.getByRole("note")).toHaveTextContent("2 suggested conditions have not been reviewed. You can still sign off");
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    expect(await screen.findByText(/2 suggested conditions were left unreviewed/)).toBeInTheDocument();
  });

  it("says '1 suggested condition has' in the singular, and says nothing when all are reviewed", () => {
    const { rerender } = render(<SignOffBar signOffs={[]} reportStatus="draft" undecided={1} onSignOff={vi.fn()} />);
    expect(screen.getByRole("note")).toHaveTextContent("1 suggested condition has not been reviewed");
    rerender(<SignOffBar signOffs={[]} reportStatus="draft" undecided={0} onSignOff={vi.fn()} />);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("shows a failure where the person is looking, keeps the note, and can try again", async () => {
    const onSignOff = vi.fn().mockRejectedValueOnce(new Error("The agents are still working.")).mockResolvedValueOnce(result());
    render(<SignOffBar signOffs={[]} reportStatus="draft" onSignOff={onSignOff} />);
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "Keep this" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The agents are still working.");
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("Keep this");
    fireEvent.click(screen.getByRole("button", { name: "Sign off review" }));
    expect(await screen.findByText("Review recorded.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lists earlier sign-offs with who, when, which version and the note", () => {
    render(<SignOffBar signOffs={[signOff(1, { note: "First pass" }), signOff(2)]} reportStatus="signed_off" onSignOff={vi.fn()} />);
    const items = within(screen.getByRole("list", { name: "Sign-offs" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("demo.reviewer · 24 Nov 2026 · version 1 · First pass");
    expect(items[1]).toHaveTextContent("version 2");
    expect(screen.getByText("Review signed off")).toBeInTheDocument();
  });

  it("says when the report changed after the last sign-off, and offers another", () => {
    render(<SignOffBar signOffs={[signOff(1)]} reportStatus="in_review" onSignOff={vi.fn()} />);
    expect(screen.getByRole("note")).toHaveTextContent("The report changed after the last sign-off");
    expect(screen.getByRole("button", { name: "Sign off review" })).toBeEnabled();
  });
});

const condition = (n: number, over: Partial<Condition> = {}): Condition => ({
  id: `c${n}`,
  position: n,
  text: `Condition ${n} as the agents wrote it`,
  priority: "attention",
  source: "agent",
  decision: "pending",
  edited_text: null,
  current_text: `Condition ${n} as the agents wrote it`,
  reason: null,
  decided_by: null,
  decided_at: null,
  ...over,
});

const reason = (text: string) => fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: text } });

describe("ConditionsPanel", () => {
  const setup = (conditions: Condition[], over: { onDecide?: ReturnType<typeof vi.fn>; onAdd?: ReturnType<typeof vi.fn> } = {}) => {
    const onDecide = over.onDecide ?? vi.fn().mockResolvedValue(undefined);
    const onAdd = over.onAdd ?? vi.fn().mockResolvedValue(undefined);
    render(<ConditionsPanel conditions={conditions} onDecide={onDecide} onAdd={onAdd} />);
    return { onDecide, onAdd };
  };

  it("lists each condition with its priority and that it has not been reviewed", () => {
    setup([condition(1, { priority: "significant" }), condition(2)]);
    const first = within(screen.getByTestId("condition-c1"));
    expect(first.getByText("Condition 1 as the agents wrote it")).toBeInTheDocument();
    expect(first.getByText("Significant")).toBeInTheDocument();
    expect(first.getByText("Not reviewed")).toBeInTheDocument();
    expect(first.getByRole("button", { name: "Accept condition 1" })).toBeEnabled();
    expect(first.getByRole("button", { name: "Edit condition 1" })).toBeEnabled();
    expect(first.getByRole("button", { name: "Reject condition 1" })).toBeEnabled();
  });

  it("accepts a condition with one click and no reason", async () => {
    const { onDecide } = setup([condition(1)]);
    fireEvent.click(screen.getByRole("button", { name: "Accept condition 1" }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledWith("c1", { decision: "accepted" }));
  });

  it("rejects only with a written reason", async () => {
    const { onDecide } = setup([condition(1)]);
    fireEvent.click(screen.getByRole("button", { name: "Reject condition 1" }));
    const confirm = await screen.findByRole("button", { name: "Reject condition" });
    expect(confirm).toBeDisabled();
    reason("   ");
    expect(confirm).toBeDisabled();
    reason("not required for this file");
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(onDecide).toHaveBeenCalledWith("c1", { decision: "rejected", reason: "not required for this file" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows the agents' words in the window, and edits only with new text and a reason", async () => {
    const { onDecide } = setup([condition(3)]);
    fireEvent.click(screen.getByRole("button", { name: "Edit condition 3" }));
    expect(await screen.findByText("The agents wrote: Condition 3 as the agents wrote it")).toBeInTheDocument();
    const text = screen.getByLabelText("Condition text");
    expect(text).toHaveValue("Condition 3 as the agents wrote it");
    fireEvent.change(text, { target: { value: "Provide the two newest stubs." } });
    const confirm = screen.getByRole("button", { name: "Save edit" });
    expect(confirm).toBeDisabled(); // no reason yet
    reason("Shorter ask");
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(onDecide).toHaveBeenCalledWith("c3", { decision: "edited", edited_text: "Provide the two newest stubs.", reason: "Shorter ask" }),
    );
  });

  it("keeps the window open with the message and what was typed when the change fails", async () => {
    const onDecide = vi.fn().mockRejectedValue(new Error("A rejection needs a reason."));
    setup([condition(1)], { onDecide });
    fireEvent.click(screen.getByRole("button", { name: "Reject condition 1" }));
    await screen.findByRole("dialog");
    reason("keep me");
    fireEvent.click(screen.getByRole("button", { name: "Reject condition" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A rejection needs a reason.");
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("keep me");
  });

  it("shows an edited condition with the reviewer's version, what the agents wrote, the reason, and who and when", () => {
    setup([
      condition(2, {
        decision: "edited",
        edited_text: "Provide the two newest stubs.",
        current_text: "Provide the two newest stubs.",
        reason: "Shorter ask",
        decided_by: "demo.reviewer",
        decided_at: "2026-11-24T10:00:00Z",
      }),
    ]);
    const row = within(screen.getByTestId("condition-c2"));
    expect(row.getByText("Provide the two newest stubs.")).toBeInTheDocument();
    expect(row.getByText(/Condition 2 as the agents wrote it/).textContent).toContain("Written by the agents:");
    expect(row.getByText("Reason: Shorter ask")).toBeInTheDocument();
    expect(row.getByText("Edited by demo.reviewer on 24 Nov 2026")).toBeInTheDocument();
  });

  it("keeps a rejected condition on the list with its reason, and does not offer to reject it again", () => {
    setup([condition(1, { decision: "rejected", reason: "not required for this file", decided_by: "demo.reviewer", decided_at: "2026-11-24T10:00:00Z" })]);
    const row = within(screen.getByTestId("condition-c1"));
    expect(row.getByText("Rejected")).toBeInTheDocument();
    expect(row.getByText("Reason: not required for this file")).toBeInTheDocument();
    expect(row.getByRole("button", { name: "Reject condition 1" })).toBeDisabled();
    expect(row.getByRole("button", { name: "Accept condition 1" })).toBeEnabled(); // a reviewer may change their mind
  });

  it("marks a condition the reviewer wrote themselves", () => {
    setup([condition(7, { source: "user", decision: "accepted" })]);
    expect(within(screen.getByTestId("condition-c7")).getByText("Added by a reviewer")).toBeInTheDocument();
  });

  it("adds a condition of the reviewer's own, with a priority, and only when it has text", async () => {
    const { onAdd } = setup([]);
    expect(screen.getByText("No conditions suggested. You can add your own.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    await screen.findByRole("dialog");
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "Add condition" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "  Provide the gift letter.  " } });
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "significant" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(onAdd).toHaveBeenCalledWith({ text: "Provide the gift letter.", priority: "significant" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the add window open and what was typed when adding fails", async () => {
    const onAdd = vi.fn().mockRejectedValue(new Error("The agents are still working."));
    setup([], { onAdd });
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "My own" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add condition" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The agents are still working.");
    expect(screen.getByLabelText("Condition")).toHaveValue("My own");
  });
});
