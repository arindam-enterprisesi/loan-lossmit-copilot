import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/underwriting" }));

import type { SessionUser } from "@/lib/session";
import { AppSidebar } from "./app-sidebar";

const user = (role: SessionUser["role"], name = "Una Underwriter"): SessionUser => ({ id: "u1", name, role });
const switcher = () => screen.queryByRole("group", { name: "Switch copilot" });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  router.replace.mockClear();
  router.refresh.mockClear();
  fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
  vi.stubGlobal("fetch", fetchMock);
});

describe("AppSidebar with the demo data (nobody signed in)", () => {
  it("shows both copilots and no sign-out", () => {
    render(<AppSidebar pillar="underwriting" />);
    expect(within(switcher()!).getAllByRole("link")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});

describe("AppSidebar with someone signed in", () => {
  it("shows who it is and their role", () => {
    render(<AppSidebar pillar="underwriting" user={user("underwriter", "Una Underwriter")} />);
    expect(screen.getByText("Una Underwriter")).toBeInTheDocument();
    expect(screen.getByText("Underwriter")).toBeInTheDocument();
  });

  it("an underwriter has nothing to switch to, so the switcher is not shown", () => {
    render(<AppSidebar pillar="underwriting" user={user("underwriter")} />);
    expect(switcher()).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Document intelligence/ })).toBeInTheDocument(); // the menu is still there
  });

  it("a loss mitigation specialist has nothing to switch to either", () => {
    render(<AppSidebar pillar="loss_mitigation" user={user("lm_specialist", "Lee Specialist")} />);
    expect(switcher()).not.toBeInTheDocument();
    expect(screen.getByText("Loss mitigation specialist")).toBeInTheDocument();
  });

  it("an administrator can switch between both", () => {
    render(<AppSidebar pillar="underwriting" user={user("admin", "Ann Admin")} />);
    expect(within(switcher()!).getAllByRole("link")).toHaveLength(2);
    expect(screen.getByText("Administrator")).toBeInTheDocument();
  });
});

describe("Sign out", () => {
  it("tells the server, then shows the sign-in page", async () => {
    render(<AppSidebar pillar="underwriting" user={user("underwriter")} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("button", { name: "Signing out…" })).toBeDisabled();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/session/logout");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("still shows the sign-in page when the server cannot be reached", async () => {
    fetchMock.mockRejectedValue(new TypeError("network"));
    render(<AppSidebar pillar="underwriting" user={user("underwriter")} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});
