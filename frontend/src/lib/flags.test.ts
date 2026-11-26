import { describe, expect, it } from "vitest";
import type { Flag } from "@/lib/types";
import { flagGroupLabel, flagGroupTitle, groupFlags } from "./flags";

const flag = (code: string, message: string, severity: Flag["severity"] = "warning"): Flag => ({
  code,
  severity,
  message,
});

describe("groupFlags", () => {
  it("returns nothing for no flags", () => {
    expect(groupFlags([])).toEqual([]);
  });

  it("keeps flags with different codes apart, in the order they came", () => {
    const groups = groupFlags([flag("DI-CHK-02", "Net pay differs"), flag("DI-W604", "Tax year wasn't found")]);
    expect(groups.map((g) => g.code)).toEqual(["DI-CHK-02", "DI-W604"]);
    expect(groups.every((g) => g.count === 1)).toBe(true);
  });

  it("merges flags that share a code, keeping every message (the real W-2 raises DI-W604 five times)", () => {
    const groups = groupFlags([
      flag("DI-W604", "Tax year wasn't found in this document."),
      flag("DI-W604", "Employee wasn't found in this document."),
      flag("DI-W604", "Box 5, Medicare wages wasn't found in this document."),
      flag("DI-W604", "Employer wasn't found in this document."),
      flag("DI-W604", "Box 1, wages wasn't found in this document."),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].count).toBe(5);
    expect(groups[0].messages).toHaveLength(5);
    expect(groups[0].messages[2]).toBe("Box 5, Medicare wages wasn't found in this document.");
  });

  it("keeps the most serious severity of a merged group", () => {
    expect(groupFlags([flag("X", "a", "info"), flag("X", "b", "error"), flag("X", "c", "warning")])[0].severity).toBe("error");
    expect(groupFlags([flag("X", "a", "warning"), flag("X", "b", "info")])[0].severity).toBe("warning");
  });
});

describe("flagGroupLabel and flagGroupTitle", () => {
  it("shows the code alone for one flag and the count for several", () => {
    expect(flagGroupLabel(groupFlags([flag("DI-CHK-02", "a")])[0])).toBe("DI-CHK-02");
    expect(flagGroupLabel(groupFlags([flag("DI-W604", "a"), flag("DI-W604", "b")])[0])).toBe("DI-W604 ×2");
  });

  it("lists each message on its own line", () => {
    expect(flagGroupTitle(groupFlags([flag("DI-W604", "first"), flag("DI-W604", "second")])[0])).toBe("first\nsecond");
  });
});
