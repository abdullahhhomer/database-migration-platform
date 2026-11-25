import { motion } from "motion/react";
import { TARGETS, clock, compact, duration, num } from "../format";
import type { Job, Migration } from "../types";
import { Empty, NowTag, Panel, StatusTag, useHeldChange } from "./common";

const RANK: Record<Job["status"], number> = { failed: 0, running: 1, pending: 2, completed: 3 };

/** Gate-board order: failures first, then running by progress, waiting, then landed (newest first). */
function rank(jobs: Job[]): Job[] {
  return [...jobs].sort((a, b) => {
    if (RANK[a.status] !== RANK[b.status]) return RANK[a.status] - RANK[b.status];
    if (a.status === "running") return b.percent - a.percent;
    if (a.status === "completed") return (b.completed_at ?? "").localeCompare(a.completed_at ?? "");
    return a.id - b.id;
  });
}

function JobRow({ job }: { job: Job }) {
  const lit = useHeldChange(`job-${job.id}`, job.status);
  return (
    <motion.tr
      layout="position"
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className={`${lit ? "is-lit" : ""} row-${job.status}`}
      title={job.error_message ?? undefined}
    >
      <td>
        <span className="cell-status">
          <StatusTag state={job.status === "completed" ? "done" : job.status} label={job.status === "completed" ? "Landed" : undefined} />
          {lit ? <NowTag /> : null}
        </span>
      </td>
      <td className="t-table">{job.table_name}</td>
      <td className="t-target">{TARGETS[job.target]?.label ?? job.target}</td>
      <td className="t-progress">
        <div className="t-progress-in">
          <div className="meter meter-thin" aria-hidden>
            <span style={{ width: `${Math.min(100, job.percent)}%` }} />
          </div>
          <span className="fig">{job.percent.toFixed(0)}%</span>
        </div>
      </td>
      <td className="num fig">
        {num(job.migrated_rows)}
        <span className="of"> / {compact(job.total_rows)}</span>
      </td>
      <td className="num fig">{num(job.rows_per_second)}</td>
      <td className="num fig">{duration(job.seconds)}</td>
      <td className="num fig">{job.completed_at ? clock(job.completed_at) : "–"}</td>
    </motion.tr>
  );
}

export function GateBoard({ migration }: { migration: Migration | null }) {
  const jobs = rank(migration?.jobs ?? []);
  const landed = jobs.filter((j) => j.status === "completed").length;
  const timing = migration?.timing;

  return (
    <Panel
      title="Gate board · full-load jobs"
      className="board"
      meta={
        jobs.length ? (
          <span className="fig">
            {landed}/{jobs.length} landed · {compact(timing?.rows_migrated)} rows · {timing?.rows_per_second ? `${compact(timing.rows_per_second)}/s` : "–"}
          </span>
        ) : null
      }
    >
      {jobs.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Table</th>
                <th scope="col">Target</th>
                <th scope="col">Progress</th>
                <th scope="col" className="num">Rows</th>
                <th scope="col" className="num">Rows/s</th>
                <th scope="col" className="num">Time</th>
                <th scope="col" className="num">Landed</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>
          Every table × target pair becomes one job here. Running jobs rise to the top, landed jobs drop below in the order
          they finished, and a job that changes state stays lit for a moment.
        </Empty>
      )}
      {migration?.run?.error_message ? <p className="board-error">{migration.run.error_message}</p> : null}
    </Panel>
  );
}
