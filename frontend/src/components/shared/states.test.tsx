import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "./empty-state";
import { ErrorNotice } from "./error-notice";
import { CardsSkeleton, SplitSkeleton, TableSkeleton } from "./skeletons";

describe("ErrorNotice", () => {
  it("says what went wrong as an alert", () => {
    render(<ErrorNotice message="Server error" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Server error");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers Try again when there is a step to repeat, and runs it", () => {
    const onRetry = vi.fn();
    render(<ErrorNotice message="Server error" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("can name the retry button differently", () => {
    render(<ErrorNotice message="Changed" onRetry={() => {}} retryLabel="Reload" />);
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("shows a title, what to do next, and an action", () => {
    render(
      <EmptyState title="No documents yet" action={<button>Upload</button>}>
        Upload a file above.
      </EmptyState>,
    );
    expect(screen.getByText("No documents yet")).toBeInTheDocument();
    expect(screen.getByText("Upload a file above.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });

  it("works with only the sentence", () => {
    render(<EmptyState>Nothing here.</EmptyState>);
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
  });
});

describe("loading skeletons", () => {
  it("a table skeleton is announced as loading, with a header row and the rows asked for", () => {
    const { container } = render(<TableSkeleton rows={3} columns={5} label="Loading documents" />);
    expect(screen.getByRole("status", { name: "Loading documents" })).toBeInTheDocument();
    expect(screen.getByText("Loading documents…")).toHaveClass("sr-only");
    expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(5 + 3 * 5);
  });

  it("a cards skeleton has one card per count", () => {
    const { container } = render(<CardsSkeleton count={2} label="Loading flags" />);
    expect(screen.getByRole("status", { name: "Loading flags" })).toBeInTheDocument();
    expect(container.querySelectorAll(".rounded-xl")).toHaveLength(2);
  });

  it("a split skeleton stands in for a page beside a list", () => {
    render(<SplitSkeleton label="Loading the document" />);
    expect(screen.getByRole("status", { name: "Loading the document" })).toBeInTheDocument();
  });
});
