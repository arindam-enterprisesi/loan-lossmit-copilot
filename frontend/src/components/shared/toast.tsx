"use client";

import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ToastOptions {
  /** Shown as a "Try again" button. Runs the same action again. */
  retry?: () => void | Promise<void>;
}

interface ToastApi {
  /** An action failed but the screen is still fine. Stays until dismissed or retried. */
  error: (message: string, options?: ToastOptions) => void;
  /** A short confirmation. Goes away by itself. */
  success: (message: string) => void;
}

interface ToastItem {
  id: number;
  kind: "error" | "success";
  message: string;
  retry?: ToastOptions["retry"];
}

/** Without a provider (a test, or a page outside the app shell) toasts are quietly dropped. */
const NO_TOASTS: ToastApi = { error: () => {}, success: () => {} };
const ToastContext = createContext<ToastApi>(NO_TOASTS);

/** `const toast = useToast(); toast.error("Could not save.", { retry: save })`. */
export const useToast = (): ToastApi => useContext(ToastContext);

const SUCCESS_MS = 4000;
const MAX_TOASTS = 4;

function ToastCard({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  useEffect(() => {
    if (toast.kind !== "success") return;
    const timer = setTimeout(() => onDismiss(toast.id), SUCCESS_MS);
    return () => clearTimeout(timer);
  }, [toast.id, toast.kind, onDismiss]);

  const isError = toast.kind === "error";
  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "pointer-events-auto flex items-start gap-3 rounded-xl border bg-card px-4 py-3 text-sm text-navy shadow-lg",
        isError ? "border-danger/50" : "border-teal/50",
      )}
    >
      <span className="min-w-0 flex-1 break-words">{toast.message}</span>
      {toast.retry ? (
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            onDismiss(toast.id);
            // A failing retry raises its own toast, so the rejection is not handled here.
            void Promise.resolve(toast.retry?.()).catch(() => {});
          }}
        >
          Try again
        </Button>
      ) : null}
      <button
        type="button"
        aria-label="Dismiss message"
        className="text-muted-foreground hover:text-navy"
        onClick={() => onDismiss(toast.id)}
      >
        <X className="size-4" />
      </button>
    </div>
  );
}

/** Mount once, near the top of the app. Shows failures and confirmations at the bottom right. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((current) => current.filter((t) => t.id !== id)), []);

  const push = useCallback((kind: ToastItem["kind"], message: string, retry?: ToastOptions["retry"]) => {
    setItems((current) => {
      // The same message twice in a row is one toast, not a stack.
      if (current.some((t) => t.kind === kind && t.message === message)) return current;
      return [...current, { id: nextId.current++, kind, message, retry }].slice(-MAX_TOASTS);
    });
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      error: (message, options) => push("error", message, options?.retry),
      success: (message) => push("success", message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2">
        {items.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
