import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PillarError from "./error";

describe("the page error screen", () => {
  it("says what went wrong and tries again", () => {
    const reset = vi.fn();
    render(<PillarError error={new Error("The server could not be reached. Is the backend running?")} reset={reset} />);
    expect(screen.getByRole("heading", { name: "This page could not load" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Is the backend running");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("has a plain message when the error has none", () => {
    render(<PillarError error={new Error("")} reset={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The server could not load this page. Check that the backend is running");
  });

  it("swaps the generic message a production build puts in place of the real one", () => {
    const hidden = "An error occurred in the Server Components render. The specific message is omitted in production builds.";
    render(<PillarError error={new Error(hidden)} reset={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Check that the backend is running");
    expect(screen.queryByText(/Server Components render/)).not.toBeInTheDocument();
  });
});
