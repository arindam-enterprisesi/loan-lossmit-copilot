"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { PILLARS, PILLAR_SLUG, navHref } from "@/lib/nav";
import type { Pillar } from "@/lib/types";

/** Left navigation as on the PRD screens: product title, copilot switcher, menu with active state. */
export function AppSidebar({ pillar }: { pillar: Pillar }) {
  const pathname = usePathname();
  const config = PILLARS[pillar];

  return (
    <nav
      aria-label={`${config.title} navigation`}
      className="flex w-64 shrink-0 flex-col gap-4 border-r bg-sidebar px-3 py-5"
    >
      <div className="px-2">
        <div className="font-heading text-base font-bold text-teal">{config.title}</div>
        <div className="mt-0.5 text-[11px] uppercase tracking-wider text-muted-foreground">
          Synthetic data only
        </div>
      </div>

      <div role="group" aria-label="Switch copilot" className="grid grid-cols-2 gap-1 rounded-lg bg-accent p-1">
        {(Object.keys(PILLARS) as Pillar[]).map((key) => (
          <Link
            key={key}
            href={`/${PILLAR_SLUG[key]}`}
            aria-current={key === pillar ? "true" : undefined}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold transition-colors",
              key === pillar ? "bg-teal text-white shadow-sm" : "text-navy hover:bg-white/70",
            )}
          >
            {(() => {
              const Icon = PILLARS[key].icon;
              return <Icon className="size-3.5" />;
            })()}
            {PILLARS[key].shortTitle}
          </Link>
        ))}
      </div>

      <ul className="flex flex-col gap-0.5">
        {config.nav.map((item) => {
          const href = navHref(pillar, item.slug);
          const active = item.slug === "" ? pathname === href : pathname.startsWith(href);
          const Icon = item.icon;
          return (
            <li key={item.slug || "dashboard"}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-teal font-semibold text-white"
                    : "text-navy hover:bg-accent",
                )}
              >
                <Icon className="size-4 shrink-0" />
                <span className="truncate">{item.label}</span>
                {item.status === "soon" ? (
                  <span
                    className={cn(
                      "ml-auto text-[10px] uppercase tracking-wide",
                      active ? "text-white/70" : "text-muted-foreground",
                    )}
                  >
                    soon
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
