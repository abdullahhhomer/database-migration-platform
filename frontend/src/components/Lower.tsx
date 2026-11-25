import { TARGETS, TABLES, bytes, compact, duration, num, parseTime, words } from "../format";
import type { Cdc, HistoryRun, Landing, Migration, Source, TargetName } from "../types";
import { Empty, Fact, Panel, StatusTag } from "./common";

export function Timeline({ migration }: { migration: Migration | null }) {
  const jobs = (migration?.jobs ?? []).filter((j) => j.started_at);
  if (!jobs.length) {
    return (
      <Panel title="Timeline">
        <Empty>Each job's start and finish is drawn here, so parallel and sequential runs look different at a glance.</Empty>
      </Panel>
    );
  }
  const spans = jobs.map((j) => {
    const start = parseTime(j.started_at)!;
    return { j, start, end: start + (j.seconds ?? 0) * 1000 };
  });
  const t0 = Math.min(...spans.map((s) => s.start));
  const t1 = Math.max(...spans.map((s) => s.end), t0 + 1000);
  const width = t1 - t0;
  const targets = [...new Set(jobs.map((j) => j.target))] as TargetName[];

  return (
    <Panel title="Timeline" meta={<span className="fig">{duration(width / 1000)} wall clock</span>}>
      <div className="timeline">
        {targets.map((target) => (
          <div key={target} className="tl-group">
            <h3 className="tl-target">{TARGETS[target].label}</h3>
            {spans
              .filter((s) => s.j.target === target)
              .sort((a, b) => a.start - b.start)
              .map(({ j, start, end }) => (
                <div key={j.id} className="tl-row">
                  <span className="tl-label">{j.table_name}</span>
                  <span className="tl-track">
                    <span
                      className={`tl-bar tl-${j.status}`}
                      style={{
                        left: `${((start - t0) / width) * 100}%`,
                        width: `${Math.max(0.8, ((end - start) / width) * 100)}%`,
                      }}
                      title={`${j.table_name} → ${TARGETS[target].label}: ${duration(j.seconds)}`}
                    />
                  </span>
                  <span className="tl-time fig">{duration(j.seconds)}</span>
                </div>
              ))}
          </div>
        ))}
        <div className="tl-axis fig" aria-hidden>
          <span>0s</span>
          <span>{duration(width / 2000)}</span>
          <span>{duration(width / 1000)}</span>
        </div>
      </div>
    </Panel>
  );
}

export function History({ runs }: { runs: HistoryRun[] }) {
  const finished = runs.filter((r) => r.seconds);
  const slowest = Math.max(1, ...finished.map((r) => r.seconds ?? 0));
  return (
    <Panel title="Run history" meta={<span>full-load time by worker count</span>}>
      {runs.length ? (
        <ol className="history">
          {runs.map((r) => (
            <li key={r.id}>
              <span className="h-run fig">#{r.id}</span>
              <span className="h-workers fig">
                {r.workers} worker{r.workers === 1 ? "" : "s"}
              </span>
              <span className="h-track">
                {r.seconds ? <span className="h-bar" style={{ width: `${(100 * r.seconds) / slowest}%` }} /> : null}
              </span>
              <span className="h-time fig">{r.seconds ? duration(r.seconds) : words(r.status)}</span>
              <span className="h-rate fig">{r.rows_per_second ? `${compact(r.rows_per_second)}/s` : "–"}</span>
            </li>
          ))}
        </ol>
      ) : (
        <Empty>Run once with 1 worker and once with 4: both timings line up here for comparison.</Empty>
      )}
    </Panel>
  );
}

export function Infrastructure({ source, cdc, landing }: { source: Source | null; cdc: Cdc | null; landing: Landing | null }) {
  const producer = cdc?.producer ?? null;
  const perTable = landing?.files_per_table ?? {};
  return (
    <Panel title="Pipeline" meta={<span>AWS services mocked locally with moto</span>}>
      <div className="infra">
        <div className="infra-block">
          <h3>PostgreSQL source</h3>
          <dl className="facts">
            <Fact label="Rows" value={compact(source?.approx_rows)} />
            <Fact label="Writes" value={`${num(source?.writes_per_second, 1)}/s`} />
            <Fact label="WAL unread" value={bytes(source?.slot.lag_bytes)} />
          </dl>
        </div>
        <div className="infra-block">
          <h3>
            Kinesis · cdc-changes <StatusTag state={producer?.state ?? "idle"} />
          </h3>
          <dl className="facts">
            <Fact label="Published" value={compact(producer?.events_published)} />
            <Fact label="This run" value={compact(producer?.since_run_start)} />
            <Fact label="Rate" value={`${num(producer?.events_per_second, 1)}/s`} />
          </dl>
        </div>
        <div className="infra-block">
          <h3>S3 · {landing ? `${landing.bucket}/${landing.prefix}` : "landing zone"}</h3>
          <dl className="facts">
            <Fact label="Parquet files" value={num(landing?.files)} />
            <Fact label="Size" value={bytes(landing?.bytes)} />
            <Fact label="Tables" value={num(Object.keys(perTable).length)} />
          </dl>
          {Object.keys(perTable).length ? (
            <ul className="files">
              {TABLES.filter((t) => perTable[t]).map((t) => (
                <li key={t}>
                  <span>{t}</span>
                  <span className="fig">{perTable[t]}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
