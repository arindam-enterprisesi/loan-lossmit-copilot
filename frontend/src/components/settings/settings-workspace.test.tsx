import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { canSeeSettings, LABEL_TEXT, sortedTasks, taskPurpose } from "@/lib/settings";
import { toSettings, type RealSettings } from "@/lib/settings-real";
import type { Settings } from "@/lib/settings-types";
import { mockSettings } from "@/mocks/settings";

// The mock answers well, so loading and failures are staged by replacing the API layer.
vi.mock("@/lib/api", () => ({ USE_MOCKS: true, getSettings: vi.fn() }));
import { getSettings } from "@/lib/api";
import { SettingsWorkspace } from "./settings-workspace";

const get = vi.mocked(getSettings);
beforeEach(() => {
  get.mockReset();
});

describe("SettingsWorkspace", () => {
  it("shows skeletons while loading", () => {
    get.mockReturnValue(new Promise(() => {}));
    render(<SettingsWorkspace />);
    expect(screen.getByRole("status", { name: "Loading the settings" })).toBeInTheDocument();
  });

  it("says it is read-only and that the values are illustrative samples", async () => {
    get.mockResolvedValue(structuredClone(mockSettings));
    render(<SettingsWorkspace />);
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/Read-only/);
    expect(note).toHaveTextContent(/illustrative sample/);
    expect(screen.queryByRole("button")).not.toBeInTheDocument(); // nothing here changes a setting
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("lists the provider and model for each task, with what the task does", async () => {
    get.mockResolvedValue(structuredClone(mockSettings));
    render(<SettingsWorkspace />);
    const classify = within(await screen.findByTestId("task-classify"));
    expect(classify.getByText("Finds each document's type")).toBeInTheDocument();
    expect(classify.getByText("anthropic")).toBeInTheDocument();
    expect(classify.getByText("claude-opus-5-5")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^task-/)).toHaveLength(6);
    expect(screen.getByText(/Default provider:/).textContent).toContain("anthropic");
    expect(screen.getByText("text-embedding-3-small")).toBeInTheDocument();
  });

  it("lists the version and the illustrative label of every settings file", async () => {
    get.mockResolvedValue(structuredClone(mockSettings));
    render(<SettingsWorkspace />);
    await screen.findByTestId("config-thresholds.yaml");
    expect(screen.getAllByTestId(/^config-/)).toHaveLength(mockSettings.config.length);
    const thresholds = within(screen.getByTestId("config-thresholds.yaml"));
    expect(thresholds.getByText("2026-11-24.1")).toBeInTheDocument();
    expect(thresholds.getByText("Illustrative")).toBeInTheDocument();
    expect(within(screen.getByTestId("config-Sample Investor A rule set")).getByText("Illustrative")).toBeInTheDocument();
  });

  it("shows an authoritative label as authoritative, not as illustrative", async () => {
    const settings: Settings = structuredClone(mockSettings);
    settings.config[1] = { ...settings.config[1], label: "authoritative" };
    get.mockResolvedValue(settings);
    render(<SettingsWorkspace />);
    expect(within(await screen.findByTestId("config-thresholds.yaml")).getByText("Authoritative")).toBeInTheDocument();
  });

  it("lists the providers that can be switched to, marking the default", async () => {
    get.mockResolvedValue(structuredClone(mockSettings));
    render(<SettingsWorkspace />);
    await screen.findByTestId("task-classify");
    fireEvent.click(screen.getByText("Providers that can be switched to"));
    const items = within(screen.getByRole("list", { name: "Providers" })).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("anthropic · claude-opus-5-5 · default");
  });

  it("says plainly when a backend has no settings endpoint yet, with no Try again", async () => {
    get.mockRejectedValue(new ApiError(404, "The settings endpoint is not available on this backend yet."));
    render(<SettingsWorkspace />);
    expect(await screen.findByText("Settings are not available yet")).toBeInTheDocument();
    expect(screen.getByText(/The settings endpoint is not available on this backend yet\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("shows an error with Try again for any other failure, and loads on the second try", async () => {
    get.mockRejectedValueOnce(new ApiError(500, "Server error")).mockResolvedValue(structuredClone(mockSettings));
    render(<SettingsWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByTestId("task-classify");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows a task it does not know by its own name, and an empty list as nothing listed", async () => {
    const settings: Settings = structuredClone(mockSettings);
    settings.llm.tasks = [{ task: "new_task", provider: "gemini", model: "gemini-flash-latest" }];
    settings.config = [];
    get.mockResolvedValue(settings);
    render(<SettingsWorkspace />);
    expect(within(await screen.findByTestId("task-new_task")).getByText("New task")).toBeInTheDocument();
    expect(screen.getByText("No settings file is listed.")).toBeInTheDocument();
  });

  it("never shows the words a person alone may decide with", async () => {
    get.mockResolvedValue(structuredClone(mockSettings));
    render(<SettingsWorkspace />);
    await screen.findByTestId("task-classify");
    expect(document.body.textContent).not.toMatch(/approv|deny|denied|eligib|qualif|\boffer/i);
  });
});

describe("settings helpers", () => {
  it("explain a task, and fall back to its name", () => {
    expect(taskPurpose("hardship")).toBe("Reads the hardship letter");
    expect(taskPurpose("some_new_task")).toBe("Some new task");
  });

  it("order tasks by name", () => {
    expect(sortedTasks([{ task: "b", provider: "p", model: "m" }, { task: "a", provider: "p", model: "m" }]).map((t) => t.task)).toEqual(["a", "b"]);
  });

  it("let an administrator, or the demo with nobody signed in, see the settings, and no one else", () => {
    expect(canSeeSettings("admin")).toBe(true);
    expect(canSeeSettings(null)).toBe(true);
    expect(canSeeSettings("underwriter")).toBe(false);
    expect(canSeeSettings("lm_specialist")).toBe(false);
    expect(canSeeSettings("none")).toBe(false);
  });

  it("label settings in words", () => {
    expect(LABEL_TEXT).toEqual({ illustrative: "Illustrative", authoritative: "Authoritative" });
  });
});

describe("the real answer", () => {
  const real: RealSettings = {
    llm: {
      version: "2026-11-19.1",
      label: "illustrative",
      default_provider: "anthropic",
      providers: { anthropic: { model: "claude-opus-5-5" }, gemini: { model: "gemini-flash-latest" } },
      tasks: { classify: { provider: "anthropic", model: "claude-opus-5-5" }, hardship: { provider: "gemini", model: "gemini-flash-latest" } },
    },
    config: [{ name: "thresholds.yaml", used_for: "Review levels", version: "2026-11-24.1", label: "illustrative" }],
  };

  it("turns the maps into lists and changes no value", () => {
    const settings = toSettings(real);
    expect(settings.llm.tasks).toEqual([
      { task: "classify", provider: "anthropic", model: "claude-opus-5-5" },
      { task: "hardship", provider: "gemini", model: "gemini-flash-latest" },
    ]);
    expect(settings.llm.providers).toEqual([
      { name: "anthropic", model: "claude-opus-5-5" },
      { name: "gemini", model: "gemini-flash-latest" },
    ]);
    expect(settings.llm.embeddings).toBeNull();
    expect(settings.config).toEqual(real.config);
  });
});

describe("getSettings", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });
  const loadApi = async (useMocks: "true" | "false") => {
    vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", useMocks);
    vi.resetModules();
    vi.doUnmock("@/lib/api");
    return vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  };

  it("with demo data returns the mock", async () => {
    const { getSettings: real } = await loadApi("true");
    expect((await real()).llm.tasks.length).toBe(mockSettings.llm.tasks.length);
  });

  it("in real mode GETs /settings, and says plainly when the endpoint does not exist", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: "Not Found" }), { status: 404, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const { getSettings: real } = await loadApi("false");
    await expect(real()).rejects.toThrow("The settings endpoint is not available on this backend yet.");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/settings");
  });

  it("in real mode translates a real answer", async () => {
    const body = {
      llm: { version: "v", label: "illustrative", default_provider: "anthropic", providers: { anthropic: { model: "m" } }, tasks: { classify: { provider: "anthropic", model: "m" } } },
      config: [],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })));
    const { getSettings: real } = await loadApi("false");
    expect((await real()).llm.tasks).toEqual([{ task: "classify", provider: "anthropic", model: "m" }]);
  });
});
