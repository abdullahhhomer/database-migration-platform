"""
Full-load job tracking and the per-job copy loop.

A job copies one source table into one target, in keyset batches
(WHERE id > last_id ORDER BY id). After every batch the job's last_id is
checkpointed, so an interrupted job resumes where it stopped: rows past the
checkpoint are removed from the target first, then copying continues.
"""

import datetime as dt

from app.migration.reader import get_db_connection, read_table_batch
from app.migration.schema import source_count
from app.targets import get_target


def _row_to_job(row, names) -> dict:
    return dict(zip(names, row))


def create_job(run_id: int | None, table_name: str, target: str, batch_size: int) -> dict:
    total_rows = source_count(table_name)
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO migration_jobs (
                        run_id, table_name, target, status, batch_size,
                        total_rows, migrated_rows, last_id
                    )
                    VALUES (%s, %s, %s, 'pending', %s, %s, 0, 0)
                    RETURNING *
                    """,
                    (run_id, table_name, target, batch_size, total_rows),
                )
                return _row_to_job(cursor.fetchone(), [d[0] for d in cursor.description])
    finally:
        connection.close()


def get_or_create_job(table_name: str, batch_size: int, target: str = "databricks") -> dict:
    """Legacy single-table API: resumes an unfinished standalone job or creates one."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM migration_jobs
                WHERE table_name = %s
                  AND target = %s
                  AND run_id IS NULL
                  AND status IN ('pending', 'running', 'failed')
                ORDER BY id DESC
                LIMIT 1
                """,
                (table_name, target),
            )
            row = cursor.fetchone()
            if row:
                return _row_to_job(row, [d[0] for d in cursor.description])
    finally:
        connection.close()

    return create_job(None, table_name, target, batch_size)


def mark_job_running(job_id: int) -> None:
    _update(
        job_id,
        "status = 'running', error_message = NULL, "
        "started_at = COALESCE(started_at, CURRENT_TIMESTAMP)",
    )


def update_job(job_id: int, last_id: int, migrated_rows: int) -> None:
    _update(job_id, "last_id = %s, migrated_rows = %s", (last_id, migrated_rows))


def complete_job(job_id: int) -> None:
    _update(job_id, "status = 'completed', completed_at = CURRENT_TIMESTAMP")


def fail_job(job_id: int, error_message: str) -> None:
    _update(job_id, "status = 'failed', error_message = %s", (error_message[:2000],))


def _update(job_id: int, assignments: str, params: tuple = ()) -> None:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE migration_jobs SET {assignments}, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (*params, job_id),
                )
    finally:
        connection.close()


def run_job(job: dict, target=None, should_stop=lambda: False) -> dict:
    """
    Copies one table into one target. Re-entrant: resuming a job first
    removes rows past its checkpoint from the target, then continues.
    """
    owns_target = target is None
    target = target or get_target(job["target"])

    job_id = job["id"]
    table = job["table_name"]
    last_id = int(job["last_id"])
    migrated = int(job["migrated_rows"])
    run_id = job.get("run_id") or 0
    started = dt.datetime.now()

    try:
        mark_job_running(job_id)

        if last_id > 0 or migrated > 0:
            target.truncate_after(table, last_id)

        while True:
            if should_stop():
                fail_job(job_id, "cancelled")
                return {"job_id": job_id, "status": "cancelled"}

            batch = read_table_batch(table, last_id=last_id, batch_size=target.batch_size)
            if batch["count"] == 0:
                complete_job(job_id)
                break

            target.load_batch(table, batch["columns"], batch["rows"], run_id)

            migrated += batch["count"]
            last_id = batch["next_last_id"]
            update_job(job_id, last_id=last_id, migrated_rows=migrated)

        elapsed = (dt.datetime.now() - started).total_seconds()
        return {
            "job_id": job_id,
            "status": "completed",
            "table": table,
            "target": job["target"],
            "migrated_rows": migrated,
            "last_id": last_id,
            "seconds": round(elapsed, 2),
        }

    except Exception as error:
        fail_job(job_id, f"{type(error).__name__}: {error}")
        raise

    finally:
        if owns_target:
            target.close()


def migrate_table(table_name: str, batch_size: int = 1000, target: str = "databricks") -> dict:
    """Legacy endpoint: migrate a single table into a single target."""
    target_impl = get_target(target)
    try:
        target_impl.prepare(reset=False)
        job = get_or_create_job(table_name, batch_size, target)
        return run_job(job, target=target_impl)
    finally:
        target_impl.close()
