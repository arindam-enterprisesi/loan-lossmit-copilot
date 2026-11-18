import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlagChip, severityTone } from "./flag-chip";
import { DocStatusChip } from "./doc-status-chip";

describe("severityTone", () => {
  it("maps contract severities to tones", () => {
    expect(severityTone("error")).toBe("danger");
    expect(severityTone("warning")).toBe("warning");
    expect(severityTone("info")).toBe("info");
  });
});

describe("FlagChip", () => {
  it("shows its text and applies the tone colour", () => {
    render(<FlagChip tone="danger">DI-CHK-02</FlagChip>);
    const chip = screen.getByText("DI-CHK-02");
    expect(chip).toBeInTheDocument();
    expect(chip.className).toContain("text-danger");
  });

  it("uses a different colour for a different tone", () => {
    render(<FlagChip tone="success">Reviewed</FlagChip>);
    expect(screen.getByText("Reviewed").className).toContain("text-success");
  });
});

describe("DocStatusChip", () => {
  it("shows the readable status and a tone that matches it", () => {
    render(<DocStatusChip status="needs_review" />);
    expect(screen.getByText("Needs review").className).toContain("text-danger");
  });
});
