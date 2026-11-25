// Derives the six runbook stages, their state and measured duration from
// the dashboard snapshot. Durations come from real timestamps; a stage that
// has not happened yet gets a small fixed weight on the route strip.
import { parseTime } from "./format";
import type { Cdc, Control, Cutover, Migration, Source, TargetName, Validation } from "./types";

export type StageState = "done" | "now" | "todo" | "failed";

export interface Stage {
  key: string;
  name: string;
  state: StageState;
  seconds: number | null;
  note: string;
}

export type PrimaryAction = "start" | "validate" | "cutover" | "rollback" | null;

interface Inputs {
  /** True while the API has never answered: nothing about the run is known. */
  unknown?: boolean;
  source: Source | null;
  migration: Migration | null;
  cdc: Cdc | null;
  validation: Validation | null;
  control: Control | null;
  cutover: Cutover | null;
  now: number;
}

function between(a: string | null | undefined, b: string | null | undefined, now: number): number | null {
  const start = parseTime(a);
  if (start === null) return null;
  const end = parseTime(b) ?? now;
  return Math.max(0, (end - start) / 1000);
}

export function runTargets(migration: Migration | null): TargetName[] {
  const raw = migration?.run?.targets ?? "";
  return raw.split(",").filter(Boolean) as TargetName[];
}

const STAGE_NAMES: [string, string][] = [
  ["capture", "Capture"],
  ["load", "Full load"],
  ["catchup", "Catch-up"],
  ["validate", "Validate"],
  ["drain", "Freeze + drain"],
  ["cutover", "Cut over"],
];

export function deriveRunbook({ unknown, source, migration, cdc, validation, control, cutover, now }: Inputs) {
  if (unknown) {
    return {
      stages: STAGE_NAMES.map(([key, name]): Stage => ({ key, name, state: "todo", seconds: null, note: "no data" })),
      primary: null as PrimaryAction,
      current: null,
      targets: [] as TargetName[],
      cutoverStarted: false,
    };
  }
  const run = migration?.run ?? null;
  const targets = runTargets(migration);
  const events = cutover?.events ?? [];
  const cutoverStatus = control?.cutover_status ?? "not_started";
  const rolledBack = cutoverStatus === "rolled_back" || cutoverStatus === "not_started";
  const eventAt = (step: string, status: string) =>
    events.find((e) => e.step === step && e.status === status)?.created_at ?? null;

  const loadDone = run?.status === "full_load_completed";
  const loadFailed = !!run && ["failed", "cancelled", "interrupted"].includes(run.status);
  const loadNow = !!run && ["preparing", "full_load"].includes(run.status);

  const states = targets.map((t) => cdc?.targets[t]?.state ?? null);
  const allInSync = targets.length > 0 && states.every((s) => s === "in_sync");
  const inSyncCount = states.filter((s) => s === "in_sync").length;

  const validatedThisRun = !!validation && !!run && validation.migration_run_id === run.id;
  const validationPassed = validatedThisRun && validation!.status === "passed";

  const freezeStart = rolledBack ? null : eventAt("freezing", "running");
  const drainDone = rolledBack ? null : eventAt("draining", "done");
  const cutoverDone = rolledBack ? null : eventAt("completed", "done");
  const cutoverFailed = !rolledBack && cutoverStatus === "failed";
  const inCutover = ["freezing", "draining", "validating", "constraints"].includes(cutoverStatus);

  const stages: Stage[] = [
    {
      key: "capture",
      name: "Capture",
      state: source?.slot.exists ? "done" : "now",
      seconds: null,
      note: source?.slot.exists ? (source.slot.active ? "CDC slot streaming" : "CDC slot idle") : "waiting for CDC slot",
    },
    {
      key: "load",
      name: "Full load",
      state: !run ? "todo" : loadDone ? "done" : loadFailed ? "failed" : loadNow ? "now" : "todo",
      seconds: run ? between(run.started_at, run.full_load_completed_at, now) : null,
      note: !run ? "not started" : loadFailed ? run.status : `${run.workers} worker${run.workers === 1 ? "" : "s"}`,
    },
    {
      key: "catchup",
      name: "Catch-up",
      state: !loadDone ? "todo" : allInSync ? "done" : "now",
      seconds: loadDone
        ? between(run!.full_load_completed_at, validation?.started_at && validatedThisRun ? validation.started_at : freezeStart, now)
        : null,
      note: loadDone ? `${inSyncCount} of ${targets.length} in sync` : "after full load",
    },
    {
      key: "validate",
      name: "Validate",
      state: validatedThisRun ? (validationPassed ? "done" : "failed") : loadDone && allInSync && !inCutover ? "now" : "todo",
      seconds: validatedThisRun ? between(validation!.started_at, validation!.completed_at, now) : null,
      note: validatedThisRun ? `${validation!.passed_checks}/${validation!.total_checks} checks` : "counts · FKs · sums",
    },
    {
      key: "drain",
      name: "Freeze + drain",
      state: drainDone ? "done" : ["freezing", "draining"].includes(cutoverStatus) ? "now" : "todo",
      seconds: freezeStart ? between(freezeStart, drainDone, now) : null,
      note: drainDone ? "watermark on all shards" : control?.writes_frozen ? "writes frozen" : "writes live",
    },
    {
      key: "cutover",
      name: "Cut over",
      state: cutoverDone ? "done" : cutoverFailed ? "failed" : ["validating", "constraints"].includes(cutoverStatus) ? "now" : "todo",
      seconds: drainDone ? between(drainDone, cutoverDone, now) : null,
      note: cutoverDone ? "ready to switch" : cutoverFailed ? "failed, roll back" : "FKs + final checks",
    },
  ];

  let primary: PrimaryAction = null;
  if (migration?.active || cutover?.active) primary = null;
  else if (!run || loadFailed) primary = "start";
  // A completed cutover needs no action: yellow would recommend undoing it.
  else if (cutoverDone) primary = null;
  else if (cutoverFailed) primary = "rollback";
  else if (loadDone && !validatedThisRun) primary = "validate";
  else if (loadDone) primary = "cutover";

  const current = stages.find((s) => s.state === "now") ?? null;
  return { stages, primary, current, targets, cutoverStarted: !rolledBack };
}
