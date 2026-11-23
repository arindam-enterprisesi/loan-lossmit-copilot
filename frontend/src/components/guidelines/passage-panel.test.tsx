import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import type { GuidelinePassage } from "@/lib/guidelines-types";
import { MOCK_PASSAGES } from "@/mocks/guidelines";

// The panel reads a passage from the backend only when the answer did not carry it.
vi.mock("@/lib/api", () => ({ USE_MOCKS: true, getGuidelinePassage: vi.fn() }));
import { getGuidelinePassage } from "@/lib/api";
import { PassagePanel } from "./passage-panel";

const read = vi.mocked(getGuidelinePassage);
beforeEach(() => {
  read.mockReset();
});

const fannie = MOCK_PASSAGES[0];
const overlay = MOCK_PASSAGES[2];
const regx = MOCK_PASSAGES.find((p) => p.id.startsWith("reg-x"))!;

const setup = (props: Partial<Parameters<typeof PassagePanel>[0]> = {}) =>
  render(<PassagePanel open onOpenChange={vi.fn()} passageId={fannie.id} passage={fannie} {...props} />);

describe("PassagePanel: the passage an answer carried", () => {
  it("shows the passage, its document, section, page, version and the Authoritative label", () => {
    setup();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(fannie.text)).toBeInTheDocument();
    expect(screen.getByText("Authoritative")).toBeInTheDocument();
    const details = screen.getByText("Document").closest("dl")!;
    expect(details).toHaveTextContent("Fannie Mae Selling Guide");
    expect(details).toHaveTextContent("B3-3.1-01 Overtime and bonus income");
    expect(details).toHaveTextContent("412");
    expect(details).toHaveTextContent("2026-09-02");
    expect(read).not.toHaveBeenCalled(); // nothing to fetch
  });

  it("shows the Illustrative label for the lender overlay", () => {
    setup({ passageId: overlay.id, passage: overlay });
    expect(screen.getByText("Illustrative")).toBeInTheDocument();
    expect(screen.queryByText("Authoritative")).not.toBeInTheDocument();
  });

  it("shows the notice that the excerpt is a demo, in a note", () => {
    setup();
    expect(screen.getByRole("note")).toHaveTextContent("Mock excerpt written for the demo, not the publisher's text.");
  });

  it("says 'Not given' for a page the source does not have (a regulation has none)", () => {
    setup({ passageId: regx.id, passage: regx });
    expect(screen.getByText("Page").nextElementSibling).toHaveTextContent("Not given");
  });

  it("shows the version, whether a number or an 'as of' date", () => {
    setup({ passageId: regx.id, passage: regx });
    expect(screen.getByText("Version as of 2026-09-01")).toBeInTheDocument();
  });

  it("has no note when the passage carries none", () => {
    setup({ passage: { ...fannie, notice: null } });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("is not shown while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("PassagePanel: a passage read from the backend by its ID", () => {
  const lean = { passage: undefined as GuidelinePassage | undefined };

  it("shows a loading state, then the passage", async () => {
    let finish!: (p: GuidelinePassage) => void;
    read.mockReturnValue(new Promise<GuidelinePassage>((resolve) => (finish = resolve)));
    setup(lean);
    expect(screen.getByRole("status", { name: "Loading the passage" })).toBeInTheDocument();
    expect(read).toHaveBeenCalledWith(fannie.id);
    finish(fannie);
    expect(await screen.findByText(fannie.text)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading the passage" })).not.toBeInTheDocument();
  });

  it("says so with Try again when it cannot be read, and Try again reads it", async () => {
    read.mockRejectedValueOnce(new ApiError(500, "Server error"));
    read.mockResolvedValue(fannie);
    setup(lean);
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(fannie.text)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a passage that does not exist is a 404 message", async () => {
    read.mockImplementation(async () => {
      throw new ApiError(404, "Passage not found");
    });
    setup(lean);
    expect(await screen.findByRole("alert")).toHaveTextContent("Passage not found");
  });

  it("does not read anything while closed, or when there is no ID", () => {
    setup({ ...lean, open: false });
    setup({ ...lean, passageId: null });
    expect(read).not.toHaveBeenCalled();
  });

  it("reads the new passage when another citation is opened", async () => {
    read.mockResolvedValueOnce(fannie).mockResolvedValueOnce(overlay);
    const { rerender } = setup(lean);
    await screen.findByText(fannie.text);
    rerender(<PassagePanel open onOpenChange={vi.fn()} passageId={overlay.id} />);
    await waitFor(() => expect(read).toHaveBeenLastCalledWith(overlay.id));
    expect(await screen.findByText(overlay.text)).toBeInTheDocument();
  });
});
