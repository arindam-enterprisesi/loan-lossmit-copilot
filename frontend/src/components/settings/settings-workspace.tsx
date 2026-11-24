"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorNotice } from "@/components/shared/error-notice";
import { FlagChip } from "@/components/shared/flag-chip";
import { TableSkeleton } from "@/components/shared/skeletons";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getSettings } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import { LABEL_TEXT, LABEL_TONE, sortedTasks, taskPurpose } from "@/lib/settings";
import type { Settings } from "@/lib/settings-types";

/**
 * The settings in force, read from the backend: which model does each task, and the version and label of every
 * settings file. Read-only: changing one is a change to a file with a new version, not something done on this screen.
 */
export function SettingsWorkspace() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [notYet, setNotYet] = useState<string | null>(null);
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);

  const load = useCallback(async () => {
    setSettings(null);
    setNotYet(null);
    setError(null);
    try {
      setSettings(await getSettings());
    } catch (e) {
      // A backend without this endpoint is not a fault to retry: say what is missing.
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) setNotYet(e.message);
      else setError({ message: e instanceof Error ? e.message : "The settings could not be loaded.", retry: () => void load() });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorNotice message={error.message} onRetry={error.retry} />;
  if (notYet) {
    return (
      <EmptyState title="Settings are not available yet">
        {notYet} The model and configuration settings live in the backend&apos;s files, and its API does not list them yet.
      </EmptyState>
    );
  }
  if (!settings) return <TableSkeleton rows={6} columns={3} label="Loading the settings" />;

  const { llm, config } = settings;
  return (
    <div className="space-y-8">
      <p role="note" className="rounded-lg border border-gold/50 bg-gold/10 px-3 py-2 text-sm text-navy">
        Read-only. Every setting here is an illustrative sample unless it says authoritative: none is a lender&apos;s or an investor&apos;s actual requirement.
        A change is made in the backend&apos;s settings files and gets a new version.
      </p>

      <section aria-labelledby="models-heading" className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="models-heading" className="text-lg">
            Model for each task
          </h2>
          <FlagChip tone={LABEL_TONE[llm.label]}>{LABEL_TEXT[llm.label]}</FlagChip>
          <span className="text-xs text-muted-foreground">Version {llm.version}</span>
        </div>
        <p className="text-sm text-muted-foreground">
          Default provider: <span className="font-semibold text-navy">{llm.default_provider}</span>. A task uses it unless its own row says otherwise. Every result
          records the provider and model that produced it.
        </p>
        <div className="rounded-xl border bg-card">
          <Table>
            <TableCaption className="sr-only">Provider and model for each task</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Task</TableHead>
                <TableHead scope="col">What it does</TableHead>
                <TableHead scope="col">Provider</TableHead>
                <TableHead scope="col">Model</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedTasks(llm.tasks).map((t) => (
                <TableRow key={t.task} data-testid={`task-${t.task}`}>
                  <TableHead scope="row" className="font-mono text-xs font-semibold text-navy">{t.task}</TableHead>
                  <TableCell className="text-navy">{taskPurpose(t.task)}</TableCell>
                  <TableCell className="text-navy">{t.provider}</TableCell>
                  <TableCell className="font-mono text-xs text-navy">{t.model}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {llm.tasks.length === 0 ? <p className="text-sm text-muted-foreground">No task is listed.</p> : null}
        {llm.embeddings ? (
          <p className="text-sm text-muted-foreground">
            Search vectors: <span className="font-semibold text-navy">{llm.embeddings.provider}</span>, model{" "}
            <span className="font-mono text-xs text-navy">{llm.embeddings.model}</span>.
          </p>
        ) : null}

        <details className="text-sm">
          <summary className="cursor-pointer select-none font-semibold text-navy">Providers that can be switched to</summary>
          <ul aria-label="Providers" className="mt-2 space-y-1 text-muted-foreground">
            {llm.providers.map((p) => (
              <li key={p.name}>
                <span className="font-semibold text-navy">{p.name}</span> · <span className="font-mono text-xs">{p.model}</span>
                {p.name === llm.default_provider ? " · default" : ""}
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section aria-labelledby="versions-heading" className="space-y-3">
        <h2 id="versions-heading" className="text-lg">
          Configuration versions
        </h2>
        <div className="rounded-xl border bg-card">
          <Table>
            <TableCaption className="sr-only">Version and label of each settings file</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Settings</TableHead>
                <TableHead scope="col">Used for</TableHead>
                <TableHead scope="col">Version</TableHead>
                <TableHead scope="col">Label</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {config.map((c) => (
                <TableRow key={c.name} data-testid={`config-${c.name}`}>
                  <TableHead scope="row" className="font-semibold text-navy">{c.name}</TableHead>
                  <TableCell className="text-navy">{c.used_for}</TableCell>
                  <TableCell className="tabular-nums text-navy">{c.version}</TableCell>
                  <TableCell>
                    <FlagChip tone={LABEL_TONE[c.label]}>{LABEL_TEXT[c.label]}</FlagChip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {config.length === 0 ? <p className="text-sm text-muted-foreground">No settings file is listed.</p> : null}
      </section>
    </div>
  );
}
