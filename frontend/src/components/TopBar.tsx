import type { ReactNode } from "react";
import { Play, RotateCcw, ShieldCheck, Square, StepForward, Undo2 } from "lucide-react";
import { TARGETS, num } from "../format";
import type { PrimaryAction } from "../runbook";
import type { TargetName } from "../types";

export type ActionName = "start" | "resume" | "cancel" | "validate" | "cutover" | "rollback";

interface Props {
  available: TargetName[];
  selected: TargetName[];
  onToggleTarget: (t: TargetName) => void;
  workers: number;
  onWorkers: (n: number) => void;
  primary: PrimaryAction;
  busy: ActionName | null;
  runActive: boolean;
  cutoverActive: boolean;
  canResume: boolean;
  /** API not answering: source state is unknown and every control is disabled. */
  unknown: boolean;
  writesFrozen: boolean;
  writesPerSecond: number | null;
  onAction: (a: ActionName) => void;
}

const WORKER_OPTIONS = [1, 2, 4, 8];

function Mark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" aria-hidden>
      <rect x="4" y="6" width="24" height="3.5" />
      <rect x="4" y="14.25" width="15" height="3.5" />
      <rect x="23" y="14.25" width="5" height="3.5" />
      <rect x="4" y="22.5" width="8" height="3.5" />
      <rect x="16" y="22.5" width="12" height="3.5" />
    </svg>
  );
}

export function TopBar(p: Props) {
  const locked = p.runActive || p.cutoverActive || p.unknown;
  const btn = (name: ActionName, label: string, icon: ReactNode, disabled: boolean, isPrimary = false) => (
    <button
      type="button"
      className={`btn ${isPrimary && !p.unknown ? "btn-primary" : "btn-quiet"}`}
      disabled={disabled || p.busy !== null || p.unknown}
      aria-busy={p.busy === name}
      onClick={() => p.onAction(name)}
    >
      {icon}
      <span>{p.busy === name ? `${label}…` : label}</span>
    </button>
  );

  return (
    <header className="topbar">
      <div className="topbar-main">
        <div className="brand">
          <Mark />
          <div>
            <h1>Migration Control Room</h1>
            <p>
              Live PostgreSQL → Databricks · SQL Server · MongoDB <span className="sep">/</span> built by Abdullah Omer
            </p>
          </div>
        </div>

        {p.unknown ? (
          <div className="source-chip is-unknown" role="status">
            <span className="pulse" aria-hidden />
            <span className="chip-label">Source unknown</span>
            <span className="fig">– writes/s</span>
          </div>
        ) : (
          <div className={`source-chip ${p.writesFrozen ? "is-frozen" : "is-live"}`} role="status">
            <span className="pulse" aria-hidden />
            <span className="chip-label">{p.writesFrozen ? "Source frozen" : "Source live"}</span>
            <span className="fig">{p.writesFrozen ? "0" : num(p.writesPerSecond, 1)} writes/s</span>
          </div>
        )}
      </div>

      <div className="controlbar">
      <fieldset className="setup" disabled={locked}>
        <legend className="sr-only">Run setup</legend>
        <div className="setup-group" role="group" aria-label="Targets">
          <span className="setup-label">Targets</span>
          {p.available.map((t) => (
            <button
              key={t}
              type="button"
              className="toggle"
              aria-pressed={p.selected.includes(t)}
              onClick={() => p.onToggleTarget(t)}
            >
              {TARGETS[t].label}
            </button>
          ))}
        </div>
        <div className="setup-group" role="radiogroup" aria-label="Parallel workers">
          <span className="setup-label">Workers</span>
          {WORKER_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              className="toggle toggle-num"
              aria-checked={p.workers === n}
              onClick={() => p.onWorkers(n)}
            >
              {n}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="actions">
        {p.runActive
          ? btn("cancel", "Cancel run", <Square size={15} aria-hidden />, false)
          : btn("start", "Start migration", <Play size={15} aria-hidden />, p.cutoverActive || p.selected.length === 0, p.primary === "start")}
        {p.canResume && !p.runActive ? btn("resume", "Resume", <StepForward size={15} aria-hidden />, p.cutoverActive) : null}
        {btn("validate", "Validate", <ShieldCheck size={15} aria-hidden />, locked, p.primary === "validate")}
        {btn("cutover", "Start cutover", <RotateCcw size={15} aria-hidden />, locked, p.primary === "cutover")}
        {btn("rollback", "Roll back", <Undo2 size={15} aria-hidden />, p.cutoverActive, p.primary === "rollback")}
      </div>
      </div>
    </header>
  );
}
