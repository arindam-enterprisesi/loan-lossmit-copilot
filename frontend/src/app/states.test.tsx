import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HitlWorkspace } from "@/components/hitl/hitl-workspace";
import { NoCases } from "@/components/shared/no-cases";
import NotFound from "./not-found";
import PillarLoading from "./[pillar]/loading";

describe("the states every screen falls back on", () => {
  it("says there are no cases, and what makes them appear, instead of a blank page", () => {
    render(<NoCases />);
    expect(screen.getByText("No cases yet")).toBeInTheDocument();
    expect(screen.getByText(/Cases appear once one has been created/)).toBeInTheDocument();
  });

  it("a screen that works on one case shows it when there is no case, and does not wait on a skeleton", () => {
    render(<HitlWorkspace cases={[]} />);
    expect(screen.getByText("No cases yet")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("a page that is loading shows its shape and says it is loading", () => {
    render(<PillarLoading />);
    expect(screen.getByRole("status", { name: "Loading the page" })).toBeInTheDocument();
  });

  it("an address that is not a screen says so and links back to both copilots", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { name: "This page does not exist" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Loan Processing" })).toHaveAttribute("href", "/underwriting");
    expect(screen.getByRole("link", { name: "Loss Mitigation" })).toHaveAttribute("href", "/loss-mitigation");
  });
});
