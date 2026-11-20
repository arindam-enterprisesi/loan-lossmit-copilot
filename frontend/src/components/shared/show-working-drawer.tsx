"use client";

import Link from "next/link";
import { Calculator } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export interface WorkingStep {
  label: string;
  /** Formula exactly as returned by the backend, e.g. "28.00 × 80 hours × 26 periods ÷ 12". */
  formula: string;
  /** Result as formatted by the backend, e.g. "4,853.33". */
  result: string;
  note?: string;
}

/** Where an input came from: a document and line, optionally linked to the page that shows it. */
export interface WorkingEvidence {
  label: string;
  /** e.g. "Page 2, line p2-L7". */
  detail?: string;
  href?: string;
}

interface ShowWorkingDrawerProps {
  title: string;
  steps: WorkingStep[];
  /** The documents and lines the inputs were read from. */
  evidence?: WorkingEvidence[];
  triggerLabel?: string;
  /** Accessible name for the trigger when several drawers share a screen, e.g. "Show working for Base pay, monthly". */
  triggerAriaLabel?: string;
  className?: string;
}

/**
 * "Show working" drawer. It only displays what the backend calculated (value + working). The
 * frontend never computes a figure itself (CLAUDE.md rule 1).
 */
export function ShowWorkingDrawer({
  title,
  steps,
  evidence = [],
  triggerLabel = "Show working",
  triggerAriaLabel,
  className,
}: ShowWorkingDrawerProps) {
  return (
    <Sheet>
      <SheetTrigger
        aria-label={triggerAriaLabel}
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), className)}
      >
        <Calculator className="size-4" />
        {triggerLabel}
      </SheetTrigger>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>Calculated in code, with no AI call.</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-5 px-4 pb-6">
          {steps.map((step) => (
            <div key={step.label}>
              <div className="text-sm font-semibold text-teal">{step.label}</div>
              <div className="mt-1 font-mono text-sm text-navy">
                {step.formula} = <span className="font-bold">{step.result}</span>
              </div>
              {step.note ? (
                <div className="mt-1 text-xs text-muted-foreground">{step.note}</div>
              ) : null}
            </div>
          ))}
          {evidence.length > 0 ? (
            <div>
              <div className="text-sm font-semibold text-teal">Read from</div>
              <ul className="mt-1 space-y-1.5 text-sm">
                {evidence.map((e, i) => (
                  <li key={`${e.label}-${e.detail ?? ""}-${i}`}>
                    {e.href ? (
                      <Link href={e.href} className="font-medium text-navy underline underline-offset-2">
                        {e.label}
                      </Link>
                    ) : (
                      <span className="font-medium text-navy">{e.label}</span>
                    )}
                    {e.detail ? <span className="text-xs text-muted-foreground"> · {e.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
