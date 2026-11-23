import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { LoginForm } from "./login-form";

const ok = (role: string) =>
  new Response(JSON.stringify({ user: { id: "u1", name: "Una", role } }), { status: 200, headers: { "Content-Type": "application/json" } });
const fail = (status: number, message: string) =>
  new Response(JSON.stringify({ code: "x", message }), { status, headers: { "Content-Type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  router.replace.mockClear();
  router.refresh.mockClear();
  fetchMock = vi.fn().mockResolvedValue(ok("underwriter"));
  vi.stubGlobal("fetch", fetchMock);
});

const fill = (username: string, password: string) => {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
};
const submit = () => fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

describe("LoginForm", () => {
  it("has a username box, a password box that hides what is typed, and a Sign in button that waits for both", () => {
    render(<LoginForm />);
    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "underwriter" } });
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("a blank (spaces only) username does not count", () => {
    render(<LoginForm />);
    fill("   ", "pw");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });

  it("fills the username from the demo user buttons, and never fills the password", () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Use the Loss mitigation specialist username" }));
    expect(screen.getByLabelText("Username")).toHaveValue("lm_specialist");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Use the Administrator username" }));
    expect(screen.getByLabelText("Username")).toHaveValue("admin");
  });

  it("sends the credentials to this app's own sign-in address, not the backend", async () => {
    render(<LoginForm />);
    fill(" underwriter ", "pw");
    submit();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/session/login");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ username: "underwriter", password: "pw" });
  });

  it("goes to the person's own pillar after signing in", async () => {
    fetchMock.mockResolvedValue(ok("lm_specialist"));
    render(<LoginForm />);
    fill("lm_specialist", "pw");
    submit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/loss-mitigation"));
    expect(router.refresh).toHaveBeenCalled();
  });

  it("goes to where they were going when that is inside the app", async () => {
    render(<LoginForm next="/underwriting/income-analysis" />);
    fill("underwriter", "pw");
    submit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/underwriting/income-analysis"));
  });

  it("ignores a 'next' address that points anywhere else", async () => {
    render(<LoginForm next="https://evil.example/phish" />);
    fill("underwriter", "pw");
    submit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/underwriting"));
  });

  it("shows the server's message and keeps what was typed when the password is wrong", async () => {
    fetchMock.mockResolvedValue(fail(401, "Incorrect username or password."));
    render(<LoginForm />);
    fill("underwriter", "wrong");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password.");
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Username")).toHaveValue("underwriter");
    expect(screen.getByLabelText("Password")).toHaveValue("wrong");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled(); // can try again
  });

  it("says so when the backend cannot be reached", async () => {
    fetchMock.mockResolvedValue(fail(502, "The server could not be reached. Is the backend running?"));
    render(<LoginForm />);
    fill("underwriter", "pw");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Is the backend running");
  });

  it("says so when this app's own address cannot be reached, and when the answer is not readable", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    render(<LoginForm />);
    fill("underwriter", "pw");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be reached");

    fetchMock.mockResolvedValueOnce(new Response("<html>", { status: 500 }));
    submit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("500"));
  });

  it("clears an old message when trying again", async () => {
    fetchMock.mockResolvedValueOnce(fail(401, "Incorrect username or password.")).mockResolvedValue(ok("underwriter"));
    render(<LoginForm />);
    fill("underwriter", "wrong");
    submit();
    await screen.findByRole("alert");
    submit();
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not send twice while it is waiting", async () => {
    let finish!: (r: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (finish = resolve)));
    render(<LoginForm />);
    fill("underwriter", "pw");
    submit();
    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    finish(ok("underwriter"));
    await waitFor(() => expect(router.replace).toHaveBeenCalledTimes(1));
  });

  it("says when the session has ended", () => {
    render(<LoginForm expired />);
    expect(screen.getByRole("status")).toHaveTextContent("Your session ended");
  });

  it("does not say it normally", () => {
    render(<LoginForm />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
