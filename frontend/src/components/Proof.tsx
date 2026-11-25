import { Check, Minus, X } from "lucide-react";
import { TARGETS, clock, words } from "../format";
import type { CheckResult, Cutover, Readiness, TargetName, Validation } from "../types";
import { Empty, NowTag, Panel, StatusTag, useHeldChange } from "./common";

const CHECKS: { type: string; label: string; what: string }[] = [
  { type: "count", label: "Row counts", what: "7 tables" },
  { type: "referential_integrity", label: "Foreign keys", what: "6 relationships" },
  { type: "checksum", label: "Money checksums", what: "SUM of amounts" },
  { type: "duplicates", label: "Duplicate keys", what: "Delta has no PK" },
  { type: "sample", label: "Sampled rows", what: "field by field" },
];

function Cell({ results }: { results: CheckResult[] }) {
  if (!results.length) {
    return (
      <td className="proof-cell is-na">
        <Minus size={14} aria-hidden />
        <span>engine enforced</span>
      </td>
    );
  }
  const passed = results.filter((r) => r.status === "passed").length;
  const allOk = passed === results.length;
  return (
    <td className={`proof-cell ${allOk ? "is-ok" : "is-bad"}`}>
      {allOk ? <Check size={15} aria-hidden /> : <X size={15} aria-hidden />}
      <span className="fig">
        {passed}/{results.length}
      </span>
    </td>
  );
}

export function ProofPanel({ validation, targets }: { validation: Validation | null; targets: TargetName[] }) {
  const lit = useHeldChange("validation", validation?.run_id ?? null);
  const shown = (validation?.targets ?? "").split(",").filter(Boolean) as TargetName[];
  const columns = shown.length ? shown : targets;
  const failures = (validation?.results ?? []).filter((r) => r.status !== "passed");

  return (
    <Panel
      title="Proof"
      className={`proof ${lit ? "is-lit" : ""}`}
      meta={
        validation ? (
          <>
            {lit ? <NowTag /> : null}
            <StatusTag state={validation.status} label={`${validation.passed_checks}/${validation.total_checks} passed`} />
          </>
        ) : null
      }
    >
      {validation ? (
        <>
          <p className="proof-context">
            Validation #{validation.run_id} at {clock(validation.completed_at)} against a{" "}
            <b>{validation.writes_frozen ? "frozen" : "live"}</b> source
            {validation.writes_frozen ? "." : ": in-flight changes can still differ."}
          </p>
          <div className="proof-scroll">
          <table className="proof-grid">
            <thead>
              <tr>
                <th scope="col">Check</th>
                {columns.map((t) => (
                  <th scope="col" key={t}>
                    {TARGETS[t]?.label ?? t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CHECKS.map((check) => (
                <tr key={check.type}>
                  <th scope="row">
                    {check.label}
                    <span className="proof-what">{check.what}</span>
                  </th>
                  {columns.map((t) => (
                    <Cell
                      key={t}
                      results={validation.results.filter((r) => r.target === t && r.check_type === check.type)}
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          {failures.length ? (
            <ul className="failures">
              {failures.slice(0, 6).map((f, i) => (
                <li key={i}>
                  <b>{TARGETS[f.target]?.label ?? f.target}</b> · {f.check_name}: source <span className="fig">{f.source_value ?? "–"}</span>,
                  target <span className="fig">{f.target_value ?? "–"}</span>
                  {f.details ? <span className="failure-detail"> {f.details}</span> : null}
                </li>
              ))}
              {failures.length > 6 ? <li>+{failures.length - 6} more</li> : null}
            </ul>
          ) : null}
        </>
      ) : (
        <Empty>
          Validate compares every target with the source: row counts, foreign keys, money checksums, duplicate keys and
          200 sampled rows per table, field by field.
        </Empty>
      )}
    </Panel>
  );
}

export function ReadinessPanel({ readiness, cutover }: { readiness: Readiness | null; cutover: Cutover | null }) {
  const ready = readiness?.status === "ready";
  const lit = useHeldChange("readiness", readiness?.status ?? null);
  const events = cutover?.events ?? [];

  return (
    <Panel
      title="Cutover"
      className={`readiness ${lit ? "is-lit" : ""}`}
      meta={
        readiness ? (
          <>
            {lit ? <NowTag /> : null}
            <StatusTag state={ready ? "ready" : "not_ready"} label={ready ? "Ready to cut over" : "Not ready"} />
          </>
        ) : null
      }
    >
      <ul className="conditions">
        {(readiness?.conditions ?? []).map((c) => (
          <li key={c.name} className={c.ok ? "is-ok" : "is-no"}>
            {c.ok ? <Check size={15} aria-label="met" /> : <X size={15} aria-label="not met" />}
            <span className="cond-name">{c.name}</span>
            <span className="cond-detail">{c.detail}</span>
          </li>
        ))}
      </ul>

      <h3 className="sub-head">Runbook log</h3>
      {events.length ? (
        <ol className="log">
          {events.map((e, i) => (
            <li key={i} className={`log-${e.status}`}>
              <span className="fig log-time">{clock(e.created_at)}</span>
              <span className="log-step">{words(e.step)}</span>
              <span className="log-msg">{e.message}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">
          Start cutover freezes writes, sends a watermark through every Kinesis shard, waits until all targets have applied
          it, validates again and enforces foreign keys on SQL Server.
        </p>
      )}
    </Panel>
  );
}
