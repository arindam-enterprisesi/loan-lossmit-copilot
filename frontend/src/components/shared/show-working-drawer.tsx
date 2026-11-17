"use client";

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

interface ShowWorkingDrawerProps {
  title: string;
  steps: WorkingStep[];
  triggerLabel?: string;
  className?: string;
}

/**
 * "Show working" drawer. It only displays what the backend calculated (value + working). The
 * frontend never computes a figure itself (CLAUDE.md rule 1).
 */
export function ShowWorkingDrawer({
  title,
  steps,
  triggerLabel = "Show working",
  className,
}: ShowWorkingDrawerProps) {
  return (
    <Sheet>
      <SheetTrigger className={cn(buttonVariants({ variant: "outline", size: "sm" }), className)}>
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
        </div>
      </SheetContent>
    </Sheet>
  );
}
