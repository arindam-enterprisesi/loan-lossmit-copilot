import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./toast";

function Harness({ retry }: { retry?: () => void | Promise<void> }) {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.error("Could not save the change.", { retry })}>fail</button>
      <button onClick={() => toast.error("Another problem.")}>fail without retry</button>
      <button onClick={() => toast.success("Saved.")}>succeed</button>
    </div>
  );
}

const renderHarness = (retry?: () => void | Promise<void>) =>
  render(
    <ToastProvider>
      <Harness retry={retry} />
    </ToastProvider>,
  );

afterEach(() => vi.useRealTimers());

describe("toasts", () => {
  it("shows a failure as an alert with the message", () => {
    renderHarness();
    fireEvent.click(screen.getByText("fail"));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save the change.");
  });

  it("offers Try again only when there is something to try again, and runs it once", () => {
    const retry = vi.fn();
    renderHarness(retry);
    fireEvent.click(screen.getByText("fail without retry"));
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("fail"));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Could not save the change.")).not.toBeInTheDocument(); // the retry takes the message away
  });

  it("does not break when the retry itself fails", async () => {
    renderHarness(() => Promise.reject(new Error("still down")));
    fireEvent.click(screen.getByText("fail"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    });
    expect(screen.queryByText("Could not save the change.")).not.toBeInTheDocument();
  });

  it("Dismiss takes a message away without running anything", () => {
    const retry = vi.fn();
    renderHarness(retry);
    fireEvent.click(screen.getByText("fail"));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss message" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(retry).not.toHaveBeenCalled();
  });

  it("shows the same failure once, not as a stack", () => {
    renderHarness();
    fireEvent.click(screen.getByText("fail"));
    fireEvent.click(screen.getByText("fail"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("keeps the newest four when many failures pile up", () => {
    function Many() {
      const toast = useToast();
      return <button onClick={() => [1, 2, 3, 4, 5, 6].forEach((n) => toast.error(`Problem ${n}`))}>many</button>;
    }
    render(
      <ToastProvider>
        <Many />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("many"));
    expect(screen.getAllByRole("alert")).toHaveLength(4);
    expect(screen.queryByText("Problem 1")).not.toBeInTheDocument();
    expect(screen.getByText("Problem 6")).toBeInTheDocument();
  });

  it("a confirmation is a status, not an alert, and goes away by itself", () => {
    vi.useFakeTimers();
    renderHarness();
    fireEvent.click(screen.getByText("succeed"));
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(4100);
    });
    expect(screen.queryByText("Saved.")).not.toBeInTheDocument();
  });

  it("a failure stays until someone deals with it", () => {
    vi.useFakeTimers();
    renderHarness();
    fireEvent.click(screen.getByText("fail"));
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("is harmless outside a provider: the call does nothing and nothing crashes", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("fail"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
