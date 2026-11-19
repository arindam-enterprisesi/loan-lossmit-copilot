"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getPageImage, type PageImage } from "./api";

/**
 * Loads the picture link for one page and handles expiry. Presigned links stop working after a few
 * minutes, so when the browser reports the image failed, ask for a fresh link once. If the fresh link
 * fails too, give up and show no image rather than looping.
 */
export function usePageImage(caseId: string, documentId: string, page: number) {
  const key = `${caseId}/${documentId}/${page}`;
  const [tick, setTick] = useState(0); // goes up to ask for a fresh link
  const [state, setState] = useState<{ key: string; image?: PageImage }>({ key: "" });
  const retries = useRef({ key, count: 0 });

  useEffect(() => {
    let cancelled = false;
    getPageImage(caseId, documentId, page)
      .then((image) => {
        if (!cancelled) setState({ key, image });
      })
      .catch(() => {
        if (!cancelled) setState({ key, image: undefined });
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, documentId, page, key, tick]);

  /** The browser could not load the image: try one fresh link, then give up. */
  const onImageError = useCallback(() => {
    if (retries.current.key !== key) retries.current = { key, count: 0 };
    if (retries.current.count >= 1) {
      setState({ key, image: undefined });
      return;
    }
    retries.current.count += 1;
    setTick((t) => t + 1);
  }, [key]);

  /** The image loaded fine, so a later expiry may try again. */
  const onImageLoad = useCallback(() => {
    retries.current = { key, count: 0 };
  }, [key]);

  // An answer for a different page is stale: show nothing until the right one arrives.
  return { url: state.key === key ? state.image?.url : undefined, onImageError, onImageLoad };
}
