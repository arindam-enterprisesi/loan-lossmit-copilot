import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button } from "./button";
import { Input } from "./input";

// Browser extensions (autofill and form helpers) add attributes such as fdprocessedid to inputs and
// buttons before React loads. React then reports a mismatch that is not a bug in our code. The shared
// Input and Button ignore it so the sign-in page, and every other form, stays quiet.

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Server-render the element, let an "extension" add an attribute, then hydrate. Returns any mismatch message. */
async function hydrateAfterExtension(element: React.ReactElement, selector: string): Promise<string[]> {
  const container = document.createElement("div");
  container.innerHTML = renderToString(element);
  document.body.appendChild(container);
  container.querySelector(selector)!.setAttribute("fdprocessedid", "ccz43");

  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  await act(async () => {
    hydrateRoot(container, element, { onRecoverableError: () => {} });
  });
  const messages = errors.mock.calls.map((c) => String(c[0]));
  errors.mockRestore();
  container.remove();
  return messages.filter((m) => m.includes("hydrated but some attributes"));
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("extension-added attributes", () => {
  it("do not cause a hydration warning on Input", async () => {
    expect(await hydrateAfterExtension(<Input name="username" />, "input")).toEqual([]);
  });

  it("do not cause a hydration warning on Button", async () => {
    expect(await hydrateAfterExtension(<Button type="submit">Sign in</Button>, "button")).toEqual([]);
  });

  it("still hydrate to a working control", async () => {
    const container = document.createElement("div");
    container.innerHTML = renderToString(<Input name="username" defaultValue="underwriter" />);
    document.body.appendChild(container);
    await act(async () => {
      hydrateRoot(container, <Input name="username" defaultValue="underwriter" />, { onRecoverableError: () => {} });
    });
    expect(container.querySelector("input")).toHaveValue("underwriter");
  });
});
