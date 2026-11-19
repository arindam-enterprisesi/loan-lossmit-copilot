import { describe, expect, it } from "vitest";
import {
  certaintyTone,
  checkFiles,
  DOCUMENT_TYPES,
  docTypeLabel,
  hasOpenFlags,
  sortFlaggedFirst,
} from "./documents";
import type { Field } from "./types";

const field = (name: string, over: Partial<Field> = {}): Field => ({
  name,
  value: "x",
  original_value: "x",
  certainty: "high",
  flags: [],
  review_status: "unreviewed",
  version: 1,
  ...over,
});

const flag = { code: "DI-CHK-02", severity: "error" as const, message: "m" };

describe("checkFiles", () => {
  it("accepts PDF, PNG and JPEG and rejects the rest", () => {
    const files = [
      new File(["a"], "a.pdf", { type: "application/pdf" }),
      new File(["b"], "b.png", { type: "image/png" }),
      new File(["c"], "c.jpg", { type: "image/jpeg" }),
      new File(["d"], "d.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      }),
    ];
    const { accepted, rejected } = checkFiles(files);
    expect(accepted.map((f) => f.name)).toEqual(["a.pdf", "b.png", "c.jpg"]);
    expect(rejected).toHaveLength(1);
    expect(rejected[0].name).toBe("d.docx");
  });
});

describe("field ordering", () => {
  it("puts fields with open flags first and keeps the rest in order", () => {
    const sorted = sortFlaggedFirst([
      field("a"),
      field("b", { flags: [flag] }),
      field("c"),
      field("d", { flags: [flag] }),
    ]);
    expect(sorted.map((f) => f.name)).toEqual(["b", "d", "a", "c"]);
  });

  it("a flag no longer counts as open once a person has reviewed the field", () => {
    expect(hasOpenFlags(field("a", { flags: [flag] }))).toBe(true);
    expect(hasOpenFlags(field("a", { flags: [flag], review_status: "confirmed" }))).toBe(false);
    expect(hasOpenFlags(field("a"))).toBe(false);
  });
});

describe("labels", () => {
  it("has a readable label for every selectable type", () => {
    for (const t of DOCUMENT_TYPES) expect(docTypeLabel(t)).toBeTruthy();
    expect(docTypeLabel("w2")).toBe("W-2");
    expect(docTypeLabel(null)).toBe("Not set");
  });

  it("never offers 'unrecognized' as a choice", () => {
    expect(DOCUMENT_TYPES).not.toContain("unrecognized");
  });

  it("maps certainty to tone", () => {
    expect(certaintyTone("high")).toBe("success");
    expect(certaintyTone("low")).toBe("danger");
  });
});
