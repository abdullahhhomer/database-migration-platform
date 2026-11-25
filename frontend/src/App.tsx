import { useEffect, useMemo, useState } from "react";
import { MotionConfig } from "motion/react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { api, useConfig, useDashboard } from "./api";
import { deriveRunbook } from "./runbook";
import { errorOf, ok } from "./types";
import type { Cdc, Control, Cutover, HistoryRun, Landing, Migration, Readiness, Source, TargetName, Validation } from "./types";
import { TopBar, type ActionName } from "./components/TopBar";
import { RunPass } from "./components/RunPass";
import { GateBoard } from "./components/GateBoard";
import { ProofPanel, ReadinessPanel } from "./components/Proof";
import { History, Infrastructure, Timeline } from "./components/Lower";

const ACTIONS: Record<ActionName, { path: string; done: string; body?: (s: Setup) => unknown }> = {
  start: {
    path: "/api/migration/start",
    done: "Migration started. Full load is running while CDC buffers every change in Kinesis.",
    body: (s) => ({ targets: s.targets, workers: s.workers, reset: true }),
  },
  resume: { path: "/api/migration/resume", done: "Resuming the run from its last checkpoints." },
  cancel: { path: "/api/migration/cancel", done: "Cancelling after the current batches finish." },
  validate: { path: "/api/validation/run", done: "Validation finished. The proof panel shows every check." },
  cutover: { path: "/api/cutover/start", done: "Cutover runbook started: freeze, drain, validate, enforce." },
  rollback: { path: "/api/cutover/rollback", done: "Rolled back. Writes are live again and CDC keeps the targets in sync." },
};

interface Setup {
  targets: TargetName[];
  workers: number;
}

export function App() {
  const { data, error, updatedAt, refresh } = useDashboard();
  const config = useConfig();
  const [setup, setSetup] = useState<Setup>({ targets: [], workers: 4 });
  const [busy, setBusy] = useState<ActionName | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);

  useEffect(() => {
    if (config) setSetup({ targets: config.targets_default, workers: config.workers_default });
  }, [config]);

  const control = ok<Control>(data?.control);
  const source = ok<Source>(data?.source);
  const migration = ok<Migration>(data?.migration);
  const cdc = ok<Cdc>(data?.cdc);
  const validation = ok<Validation>(data?.validation ?? null);
  const readiness = ok<Readiness>(data?.readiness);
  const cutover = ok<Cutover>(data?.cutover);
  const landing = ok<Landing>(data?.landing);
  const history = ok<HistoryRun[]>(data?.history) ?? [];

  // Never answered: nothing is known. Answered before, failing now: stale.
  const unknown = !!error && !data;
  const stale = !!error && !!data;

  const runbook = useMemo(
    () => deriveRunbook({ unknown, source, migration, cdc, validation, control, cutover, now: Date.now() }),
    [data, unknown], // every derived input comes from this one snapshot
  );

  const sectionErrors = data
    ? (["source", "migration", "cdc", "landing", "readiness"] as const)
        .map((k) => errorOf(data[k]) && `${k}: ${errorOf(data[k])}`)
        .filter(Boolean)
    : [];

  async function act(name: ActionName) {
    const spec = ACTIONS[name];
    setBusy(name);
    setNotice(null);
    try {
      await api(spec.path, { method: "POST", body: spec.body ? JSON.stringify(spec.body(setup)) : undefined });
      setNotice({ text: spec.done, tone: "ok" });
      await refresh();
    } catch (e) {
      setNotice({ text: (e as Error).message, tone: "bad" });
    } finally {
      setBusy(null);
    }
  }

  const run = migration?.run;
  const canResume = !!run && ["interrupted", "failed", "cancelled"].includes(run.status);

  return (
    <MotionConfig reducedMotion="user">
      <TopBar
        available={config?.targets_available ?? ["databricks", "sqlserver", "mongodb"]}
        selected={setup.targets}
        onToggleTarget={(t) =>
          setSetup((s) => ({
            ...s,
            targets: s.targets.includes(t) ? s.targets.filter((x) => x !== t) : [...s.targets, t],
          }))
        }
        workers={setup.workers}
        onWorkers={(n) => setSetup((s) => ({ ...s, workers: n }))}
        primary={runbook.primary}
        busy={busy}
        runActive={!!migration?.active}
        cutoverActive={!!cutover?.active}
        canResume={canResume}
        unknown={unknown || stale}
        writesFrozen={!!control?.writes_frozen}
        writesPerSecond={source?.writes_per_second ?? null}
        onAction={act}
      />

      <main className="page">
        {unknown ? (
          <div className="notice notice-bad" role="alert">
            <AlertTriangle size={16} aria-hidden />
            Migration API unreachable ({error}). Nothing below is known until it answers: is <code>docker compose up</code> running?
          </div>
        ) : null}
        {stale ? (
          <div className="notice notice-bad" role="alert">
            <AlertTriangle size={16} aria-hidden />
            Connection to the migration API lost ({error}). Showing the last data received
            {updatedAt ? ` at ${updatedAt.toLocaleTimeString("en-GB")}` : ""}; controls are disabled until it answers.
          </div>
        ) : null}
        {notice ? (
          <div className={`notice notice-${notice.tone}`} role="status">
            {notice.tone === "ok" ? <CheckCircle2 size={16} aria-hidden /> : <AlertTriangle size={16} aria-hidden />}
            {notice.text}
          </div>
        ) : null}
        {sectionErrors.length ? (
          <div className="notice notice-bad" role="alert">
            <AlertTriangle size={16} aria-hidden />
            {sectionErrors.join(" · ")}
          </div>
        ) : null}

        <RunPass
          unknown={unknown}
          migration={migration}
          stages={runbook.stages}
          targets={runbook.targets}
          cdcTargets={cdc?.targets ?? {}}
        />

        <div className="work">
          <GateBoard migration={migration} />
          {/* Once a cutover has started its runbook is the story; it leads the column. */}
          <div className={`side ${runbook.cutoverStarted ? "cutover-first" : ""}`}>
            <ProofPanel validation={validation} targets={runbook.targets} />
            <ReadinessPanel readiness={readiness} cutover={cutover} />
          </div>
        </div>

        <div className="lower">
          <Timeline migration={migration} />
          <History runs={history} />
          <Infrastructure source={source} cdc={cdc} landing={landing} />
        </div>
      </main>

      <footer className="footer">
        <span>Migration Control Room · built by Abdullah Omer</span>
        <span>
          Live data from the migration API, refreshed every 2 s{updatedAt ? ` · last update ${updatedAt.toLocaleTimeString("en-GB")}` : ""}
        </span>
        <span>S3, Kinesis, DynamoDB and Secrets Manager are mocked with moto; Databricks is a real workspace</span>
      </footer>
    </MotionConfig>
  );
}
