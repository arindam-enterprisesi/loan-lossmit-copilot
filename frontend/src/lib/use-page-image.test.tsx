import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ getPageImage: vi.fn() }));
import { getPageImage } from "./api";
import { usePageImage } from "./use-page-image";

const mocked = vi.mocked(getPageImage);

// Braces matter: a beforeEach that returns a function is treated as a cleanup step by Vitest.
beforeEach(() => {
  mocked.mockReset();
});

describe("usePageImage", () => {
  it("asks for the page's link and returns it", async () => {
    mocked.mockResolvedValue({ url: "https://s3.test/p1?sig=a" });
    const { result } = renderHook(() => usePageImage("c1", "d1", 1));
    expect(result.current.url).toBeUndefined(); // nothing until the answer arrives
    await waitFor(() => expect(result.current.url).toBe("https://s3.test/p1?sig=a"));
    expect(mocked).toHaveBeenCalledWith("c1", "d1", 1);
  });

  it("has no image when the backend has none", async () => {
    mocked.mockResolvedValue(undefined);
    const { result } = renderHook(() => usePageImage("c1", "d1", 1));
    await waitFor(() => expect(mocked).toHaveBeenCalled());
    expect(result.current.url).toBeUndefined();
  });

  it("has no image when asking fails", async () => {
    mocked.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => usePageImage("c1", "d1", 1));
    await waitFor(() => expect(mocked).toHaveBeenCalled());
    expect(result.current.url).toBeUndefined();
  });

  it("asks for a fresh link once when the image fails to load (expired link)", async () => {
    mocked
      .mockResolvedValueOnce({ url: "https://s3.test/p1?sig=old" })
      .mockResolvedValueOnce({ url: "https://s3.test/p1?sig=fresh" });
    const { result } = renderHook(() => usePageImage("c1", "d1", 1));
    await waitFor(() => expect(result.current.url).toContain("sig=old"));

    act(() => result.current.onImageError());
    await waitFor(() => expect(result.current.url).toContain("sig=fresh"));
    expect(mocked).toHaveBeenCalledTimes(2);
  });

  it("gives up after one fresh link fails too, instead of looping", async () => {
    mocked.mockResolvedValue({ url: "https://s3.test/p1?sig=bad" });
    const { result } = renderHook(() => usePageImage("c1", "d1", 1));
    await waitFor(() => expect(result.current.url).toBeDefined());

    act(() => result.current.onImageError()); // first failure: ask again
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.url).toBeDefined());

    act(() => result.current.onImageError()); // second failure: stop
    expect(result.current.url).toBeUndefined();
    await new Promise((r) => setTimeout(r, 50));
    expect(mocked).toHaveBeenCalledTimes(2); // no third ask
  });

  it("allows another retry later once an image has loaded fine", async () => {
    mocked.mockResolvedValue({ url: "https://s3.test/p1" });
    const { result } = renderHook(() => usePageImage("c1", "d1", 1));
    await waitFor(() => expect(result.current.url).toBeDefined());

    act(() => result.current.onImageError());
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
    act(() => result.current.onImageLoad()); // the fresh link worked
    act(() => result.current.onImageError()); // it expires again later
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(3));
  });

  it("shows nothing for a new page until its own link arrives", async () => {
    mocked.mockImplementation(async (_c, _d, page) => ({ url: `https://s3.test/p${page}` }));
    const { result, rerender } = renderHook(({ page }) => usePageImage("c1", "d1", page), {
      initialProps: { page: 1 },
    });
    await waitFor(() => expect(result.current.url).toBe("https://s3.test/p1"));

    rerender({ page: 3 });
    expect(result.current.url).toBeUndefined(); // the page 1 link is not shown for page 3
    await waitFor(() => expect(result.current.url).toBe("https://s3.test/p3"));
  });
});
