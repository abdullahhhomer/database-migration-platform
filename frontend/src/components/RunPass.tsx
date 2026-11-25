import { Check, X } from "lucide-react";
import { TARGETS, clock, compact, duration, num } from "../format";
import type { Stage } from "../runbook";
import type { CdcTarget, Job, Migration, TargetName } from "../types";
import { NowTag, StatusTag, useHeldChange } from "./common";

const MIN_STAGE_WEIGHT = 0.06;

function Route({ stages }: { stages: Stage[] }) {
  const measured = stages.reduce((sum, s) => sum + (s.seconds ?? 0), 0) || 1;
  return (
    <ol className="route" aria-label="Runbook stages">
      {stages.map((stage, i) => {
        const weight = Math.max(MIN_STAGE_WEIGHT, (stage.seconds ?? 0) / measured);
        return (
          <li
            key={stage.key}
            className={`stop stop-${stage.state}`}
            style={{ flexGrow: weight }}
            aria-current={stage.state === "now" ? "step" : undefined}
          >
            <span className="stop-index fig">{i + 1}</span>
            <span className="stop-name">{stage.name}</span>
            <span className="stop-state">
              {stage.state === "done" ? <Check size={13} aria-hidden /> : null}
              {stage.state === "failed" ? <X size={13} aria-hidden /> : null}
              {stage.state === "now" ? "Now" : stage.state === "todo" ? "Next" : stage.state === "failed" ? "Failed" : "Done"}
            </span>
            <span className="stop-figure fig">{stage.seconds !== null ? duration(stage.seconds) : "—"}</span>
            <span className="stop-note">{stage.note}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Segment({
  name,
  status,
  jobs,
  loading,
}: {
  name: TargetName;
  status: CdcTarget | undefined;
  jobs: Job[];
  loading: boolean;
}) {
  const info = TARGETS[name];
  const loaded = jobs.reduce((s, j) => s + j.migrated_rows, 0);
  const total = jobs.reduce((s, j) => s + j.total_rows, 0);
  const done = jobs.filter((j) => j.status === "completed").length;
  const failed = jobs.some((j) => j.status === "failed");
  const percent = total ? Math.min(100, (100 * loaded) / total) : 0;

  const fullLoadOpen = loading || (jobs.length > 0 && done < jobs.length);
  const state = failed ? "failed" : fullLoadOpen ? (status?.state === "error" ? "error" : "loading") : status?.state ?? "idle";
  const lit = useHeldChange(`seg-${name}`, state);

  return (
    <article className={`segment ${lit ? "is-lit" : ""}`} aria-label={`${info.label} target`}>
      <header className="segment-head">
        <div>
          <h3>{info.label}</h3>
          <p>{info.role}</p>
        </div>
        <div className="segment-tags">
          {lit ? <NowTag /> : null}
          <StatusTag state={state} label={state === "loading" ? "Full load" : undefined} />
        </div>
      </header>

      {fullLoadOpen ? (
        <>
          <div className="segment-figure">
            <span className="big fig">{percent.toFixed(0)}%</span>
            <span className="caption">
              {compact(loaded)} of {compact(total)} rows · {done}/{jobs.length} tables
            </span>
          </div>
          <div className="meter" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${percent}%` }} />
          </div>
          <p className="segment-foot">
            CDC: {num(status?.backlog)} changes buffered in Kinesis until this load finishes
          </p>
        </>
      ) : (
        <>
          <div className="segment-figure">
            <span className="big fig">{num(status?.backlog)}</span>
            <span className="caption">changes behind the source</span>
          </div>
          <dl className="segment-facts">
            <div>
              <dt>Lag</dt>
              <dd className="fig">{status?.seconds_behind !== null && status?.seconds_behind !== undefined ? duration(status.seconds_behind) : "–"}</dd>
            </div>
            <div>
              <dt>Applied</dt>
              <dd className="fig">{num(status?.events_applied)}</dd>
            </div>
            <div>
              <dt>Rate</dt>
              <dd className="fig">{num(status?.events_per_second, 1)}/s</dd>
            </div>
            <div>
              <dt>Last LSN</dt>
              <dd className="fig">{status?.last_applied_lsn ?? "–"}</dd>
            </div>
          </dl>
          {status?.message ? <p className="segment-foot is-alert">{status.message}</p> : null}
        </>
      )}
    </article>
  );
}

export function RunPass({
  unknown = false,
  migration,
  stages,
  targets,
  cdcTargets,
}: {
  unknown?: boolean;
  migration: Migration | null;
  stages: Stage[];
  targets: TargetName[];
  cdcTargets: Partial<Record<TargetName, CdcTarget>>;
}) {
  const run = migration?.run ?? null;
  const timing = migration?.timing ?? null;
  const loading = !!run && ["preparing", "full_load"].includes(run.status);

  return (
    <section className="pass" aria-label="Migration run">
      <div className="stub">
        <span className="stub-label">Run</span>
        <span className="stub-number fig">{run ? `#${run.id}` : "—"}</span>
        {unknown ? <StatusTag state="idle" label="No data" /> : <StatusTag state={run?.status ?? "not_started"} />}
        <dl className="stub-facts">
          <div>
            <dt>Workers</dt>
            <dd className="fig">{run?.workers ?? "–"}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd className="fig">{clock(run?.started_at)}</dd>
          </div>
          <div>
            <dt>Full load</dt>
            <dd className="fig">{duration(timing?.elapsed_seconds)}</dd>
          </div>
          <div>
            <dt>Rows</dt>
            <dd className="fig">{compact(timing?.rows_migrated)}</dd>
          </div>
          <div>
            <dt>Throughput</dt>
            <dd className="fig">{timing?.rows_per_second ? `${compact(timing.rows_per_second)}/s` : "–"}</dd>
          </div>
        </dl>
      </div>

      <div className="perforation" aria-hidden />

      <div className="pass-body">
        <Route stages={stages} />
        {targets.length ? (
          <div className="segments" style={{ gridTemplateColumns: `repeat(${targets.length}, minmax(0, 1fr))` }}>
            {targets.map((t) => (
              <Segment
                key={t}
                name={t}
                status={cdcTargets[t]}
                jobs={(migration?.jobs ?? []).filter((j) => j.target === t)}
                loading={loading}
              />
            ))}
          </div>
        ) : unknown ? (
          <p className="pass-empty">Waiting for the migration API. The run, its targets and CDC state appear as soon as it answers.</p>
        ) : (
          <p className="pass-empty">
            No run yet. Choose targets and workers above, then <b>Start migration</b>: CDC is already capturing changes, so
            nothing written during the copy is lost.
          </p>
        )}
      </div>
    </section>
  );
}
