import { cn } from "@/lib/utils";

interface StatCardProps {
  /** Big number or figure, already formatted by the backend or counted by the page. */
  value: string | number;
  label: string;
  /** Small grey line under the label, e.g. the formula or a context note. */
  hint?: string;
  className?: string;
}

/** KPI tile as on the PRD "sample data" slide: big teal figure, bold label, grey hint. */
export function StatCard({ value, label, hint, className }: StatCardProps) {
  return (
    <div className={cn("rounded-xl border bg-panel p-5", className)}>
      <div className="font-heading text-3xl font-bold text-teal">{value}</div>
      <div className="mt-1 text-sm font-semibold text-navy">{label}</div>
      {hint ? <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}
