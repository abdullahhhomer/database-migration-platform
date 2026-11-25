"""
Migration run orchestrator ("our DMS": full-load-and-cdc).

A run:
  1. requires the CDC replication slot to exist, so every change committed
     from now on is captured (the CDC appliers replay from the run start);
  2. resets the selected targets;
  3. creates one job per (table, target) and runs them on a thread pool
     of `workers` (1 = sequential, N = parallel) -- compare the timings;
  4. when a target's jobs are done, its CDC applier starts replaying.
"""

import datetime as dt
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import configured_targets, default_workers
from app.control import fetch_all_dicts, fetch_one_dict, latest_run, set_control
from app.migration.reader import get_db_connection
from app.migration.service import create_job, run_job
from app.targets import get_target


log = logging.getLogger("orchestrator")

CDC_SLOT = os.getenv("CDC_SLOT", "migration_cdc_slot")

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


class MigrationError(Exception):
    pass


def is_active() -> bool:
    return _thread is not None and _thread.is_alive()


def cdc_slot_exists() -> bool:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_replication_slots WHERE slot_name = %s",
                (CDC_SLOT,),
            )
            return cursor.fetchone()[0] > 0
    finally:
        connection.close()


def _set_run(run_id: int, **fields) -> None:
    assignments = ", ".join(f"{k} = %s" for k in fields)
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE migration_runs SET {assignments} WHERE id = %s",
                    (*fields.values(), run_id),
                )
    finally:
        connection.close()


def mark_interrupted_runs() -> None:
    """Called at backend start: runs left 'running' by a crash become resumable."""
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE migration_runs SET status = 'interrupted' "
                    "WHERE status IN ('preparing', 'full_load')"
                )
                cursor.execute(
                    "UPDATE migration_jobs SET status = 'pending' WHERE status = 'running'"
                )
    finally:
        connection.close()


def _create_run(targets: list[str], workers: int) -> dict:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COALESCE(MAX(events_published), 0) FROM cdc_status WHERE target = 'producer'"
                )
                producer_events = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO migration_runs (status, targets, workers, start_lsn, producer_events_at_start)
                    VALUES ('preparing', %s, %s, pg_current_wal_lsn(), %s)
                    RETURNING *
                    """,
                    (",".join(targets), workers, producer_events),
                )
                return fetch_one_dict(cursor)
    finally:
        connection.close()


FENCE_TIMEOUT_SECONDS = int(os.getenv("APPLIER_FENCE_TIMEOUT_SECONDS", "90"))
STALE_APPLIER_SECONDS = 30


def _await_applier_fence(run_id: int, targets: list[str]) -> None:
    """
    Handshake before targets are reset: every live CDC applier must have seen
    this run (it then reports 'waiting_for_full_load' for it) and so has
    stopped applying the previous run's changes. An applier that has not
    reported for STALE_APPLIER_SECONDS is treated as down and does not block.
    """
    deadline = time.time() + FENCE_TIMEOUT_SECONDS
    pending = list(targets)
    while time.time() < deadline:
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT target, run_id, state,
                           EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at)) AS age
                    FROM cdc_status WHERE target = ANY(%s)
                    """,
                    (targets,),
                )
                rows = {r["target"]: r for r in fetch_all_dicts(cursor)}
        finally:
            connection.close()

        pending = [
            t for t in targets
            if t in rows
            and float(rows[t]["age"] or 0) < STALE_APPLIER_SECONDS
            and not (rows[t]["run_id"] == run_id and rows[t]["state"] in ("waiting_for_full_load", "not_configured", "idle"))
        ]
        if not pending:
            return
        time.sleep(1)
    log.warning("CDC appliers did not acknowledge run %s in time: %s; continuing", run_id, ", ".join(pending))


def _execute_run(run: dict, targets: list[str], workers: int, reset: bool, resume: bool) -> None:
    run_id = run["id"]
    try:
        # 0. Fence: no applier may still be writing the previous run's changes.
        _await_applier_fence(run_id, targets)

        # 1. Prepare targets (in parallel: they are independent systems).
        if not resume:
            with ThreadPoolExecutor(max_workers=len(targets)) as pool:
                futures = {pool.submit(_prepare_target, t, reset): t for t in targets}
                for future in as_completed(futures):
                    future.result()

            jobs = []
            for target_name in targets:
                target = get_target(target_name)
                for table in target.load_units():
                    jobs.append(create_job(run_id, table, target_name, target.batch_size))

            connection = get_db_connection()
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE migration_runs SET total_rows = "
                            "(SELECT COALESCE(SUM(total_rows), 0) FROM migration_jobs WHERE run_id = %s) "
                            "WHERE id = %s",
                            (run_id, run_id),
                        )
            finally:
                connection.close()
        else:
            jobs = _run_jobs(run_id, statuses=("pending", "running", "failed"))

        _set_run(run_id, status="full_load")

        # 2. Interleave targets so parallel workers spread across systems.
        jobs.sort(key=lambda j: (_table_rank(j["table_name"]), j["target"]))

        errors = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job") as pool:
            futures = [pool.submit(run_job, job, None, _stop.is_set) for job in jobs]
            for future in as_completed(futures):
                try:
                    result = future.result()
                    log.info("Job finished: %s", result)
                except Exception as error:
                    log.exception("Job failed")
                    errors.append(str(error))

        if _stop.is_set():
            _set_run(run_id, status="cancelled")
        elif errors:
            _set_run(run_id, status="failed", error_message="; ".join(errors)[:2000])
        else:
            _set_run(run_id, status="full_load_completed", full_load_completed_at=dt.datetime.now(dt.timezone.utc))

    except Exception as error:
        log.exception("Run %s failed", run_id)
        _set_run(run_id, status="failed", error_message=f"{type(error).__name__}: {error}"[:2000])


def _prepare_target(name: str, reset: bool) -> None:
    target = get_target(name)
    try:
        target.prepare(reset=reset)
    finally:
        target.close()


def _table_rank(table: str) -> int:
    order = ["order_items", "orders", "payments", "shipments", "customers", "returns", "products"]
    # Largest tables first so the long jobs start early.
    return order.index(table) if table in order else len(order)


def _run_jobs(run_id: int, statuses: tuple | None = None) -> list[dict]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            if statuses:
                cursor.execute(
                    "SELECT * FROM migration_jobs WHERE run_id = %s AND status = ANY(%s) ORDER BY id",
                    (run_id, list(statuses)),
                )
            else:
                cursor.execute("SELECT * FROM migration_jobs WHERE run_id = %s ORDER BY id", (run_id,))
            return fetch_all_dicts(cursor)
    finally:
        connection.close()


def start_run(targets: list[str] | None = None, workers: int | None = None, reset: bool = True) -> dict:
    global _thread
    targets = [t for t in (targets or configured_targets())]
    workers = max(1, min(int(workers or default_workers()), 16))

    if not targets:
        raise MigrationError("No targets selected")

    with _lock:
        if is_active():
            raise MigrationError("A migration run is already in progress")
        if not cdc_slot_exists():
            raise MigrationError(
                f"CDC replication slot '{CDC_SLOT}' does not exist yet. Start the "
                "cdc-worker first so no change made during the copy is lost."
            )

        # A new run starts from a live, unfrozen source.
        set_control(writes_frozen=False, cutover_status="not_started")

        run = _create_run(targets, workers)
        _stop.clear()
        _thread = threading.Thread(
            target=_execute_run, args=(run, targets, workers, reset, False),
            name=f"run-{run['id']}", daemon=True,
        )
        _thread.start()
        return run


def resume_run() -> dict:
    global _thread
    with _lock:
        if is_active():
            raise MigrationError("A migration run is already in progress")
        run = latest_run()
        if not run or run["status"] not in ("interrupted", "failed", "cancelled"):
            raise MigrationError("There is no interrupted, failed or cancelled run to resume")

        targets = [t for t in run["targets"].split(",") if t]
        _set_run(run["id"], status="full_load", error_message=None)
        _stop.clear()
        _thread = threading.Thread(
            target=_execute_run, args=(run, targets, run["workers"], False, True),
            name=f"run-{run['id']}-resume", daemon=True,
        )
        _thread.start()
        return {**run, "status": "full_load"}


def cancel_run() -> dict:
    if not is_active():
        raise MigrationError("No migration run is in progress")
    _stop.set()
    return {"status": "cancelling"}


def run_status(run_id: int | None = None) -> dict:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            if run_id:
                cursor.execute("SELECT * FROM migration_runs WHERE id = %s", (run_id,))
            else:
                cursor.execute("SELECT * FROM migration_runs ORDER BY id DESC LIMIT 1")
            run = fetch_one_dict(cursor)
            if not run:
                return {"run": None, "jobs": [], "timing": None}

            cursor.execute(
                """
                SELECT id, table_name, target, status, total_rows, migrated_rows,
                       batch_size, started_at, completed_at, error_message,
                       EXTRACT(EPOCH FROM (COALESCE(completed_at, LOCALTIMESTAMP) - started_at)) AS seconds
                FROM migration_jobs WHERE run_id = %s ORDER BY id
                """,
                (run["id"],),
            )
            jobs = fetch_all_dicts(cursor)
    finally:
        connection.close()

    for job in jobs:
        seconds = float(job["seconds"]) if job["seconds"] is not None else None
        job["seconds"] = round(seconds, 2) if seconds is not None else None
        job["rows_per_second"] = (
            round(job["migrated_rows"] / seconds) if seconds and seconds > 0 else None
        )
        job["percent"] = (
            round(100 * job["migrated_rows"] / job["total_rows"], 1) if job["total_rows"] else 100.0
        )

    end = run["full_load_completed_at"] or dt.datetime.now(dt.timezone.utc)
    elapsed = (end - run["started_at"]).total_seconds()
    migrated = sum(j["migrated_rows"] for j in jobs)

    return {
        "run": run,
        "active": is_active(),
        "jobs": jobs,
        "timing": {
            "workers": run["workers"],
            "elapsed_seconds": round(elapsed, 1),
            "rows_migrated": migrated,
            "rows_total": run["total_rows"],
            "rows_per_second": round(migrated / elapsed) if elapsed > 0 else None,
        },
    }


def run_history(limit: int = 10) -> list[dict]:
    """Past runs with their timing, to compare sequential vs parallel."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.id, r.status, r.targets, r.workers, r.started_at,
                       r.full_load_completed_at, r.total_rows,
                       EXTRACT(EPOCH FROM (r.full_load_completed_at - r.started_at)) AS seconds,
                       (SELECT COALESCE(SUM(migrated_rows), 0) FROM migration_jobs j WHERE j.run_id = r.id) AS migrated_rows
                FROM migration_runs r
                ORDER BY r.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            runs = fetch_all_dicts(cursor)
    finally:
        connection.close()

    for r in runs:
        # SUM() over BIGINT comes back from Postgres as NUMERIC (Decimal).
        r["migrated_rows"] = int(r["migrated_rows"] or 0)
        seconds = float(r["seconds"]) if r["seconds"] is not None else None
        r["seconds"] = round(seconds, 1) if seconds is not None else None
        r["rows_per_second"] = round(r["migrated_rows"] / seconds) if seconds else None
    return runs
