"""
Cutover runbook.

  1. freeze    stop application writes (the transaction generator pauses)
  2. drain     write a heartbeat token; wait until every CDC applier has seen
               it on every Kinesis shard -> all earlier changes are applied
  3. validate  full validation of every target against the quiet source
  4. enforce   add foreign keys WITH CHECK on SQL Server
  5. decide    'completed' (ready to switch the application) or 'failed'

Rollback unfreezes writes and removes the SQL Server constraints, so CDC can
continue and the cutover can be retried later.
"""

import logging
import os
import threading
import time
import uuid

from app.control import (
    fetch_all_dicts,
    get_control,
    latest_run,
    log_cutover_event,
    run_targets,
    set_control,
)
from app.migration.reader import get_db_connection
from app.targets import get_target
from app.validation.validator import run_validation


log = logging.getLogger("cutover")

DRAIN_TIMEOUT_SECONDS = int(os.getenv("CUTOVER_DRAIN_TIMEOUT_SECONDS", "900"))
SETTLE_SECONDS = 3

_lock = threading.Lock()
_thread: threading.Thread | None = None


class CutoverError(Exception):
    pass


def is_active() -> bool:
    return _thread is not None and _thread.is_alive()


def _step(step: str, status: str, message: str = "") -> None:
    log.info("[%s] %s %s", step, status, message)
    log_cutover_event(step, status, message)
    if status == "running":
        set_control(cutover_status=step)


def _write_heartbeat(token: str) -> None:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO cdc_heartbeat (token) VALUES (%s)", (token,))
    finally:
        connection.close()


def _heartbeats(targets: list[str]) -> dict[str, str | None]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT target, last_heartbeat FROM cdc_status WHERE target = ANY(%s)",
                (targets,),
            )
            seen = {r["target"]: r["last_heartbeat"] for r in fetch_all_dicts(cursor)}
    finally:
        connection.close()
    return {t: seen.get(t) for t in targets}


def _runbook(targets: list[str]) -> None:
    try:
        _step("freezing", "running", "Pausing application writes")
        set_control(writes_frozen=True)
        time.sleep(SETTLE_SECONDS)   # let in-flight transactions commit
        _step("freezing", "done", "Writes frozen")

        token = uuid.uuid4().hex
        set_control(heartbeat_token=token)
        _step("draining", "running", f"Waiting for watermark {token[:8]} on all targets")
        _write_heartbeat(token)

        deadline = time.time() + DRAIN_TIMEOUT_SECONDS
        while True:
            seen = _heartbeats(targets)
            pending = [t for t, value in seen.items() if value != token]
            if not pending:
                break
            if time.time() > deadline:
                raise CutoverError(f"CDC did not drain within {DRAIN_TIMEOUT_SECONDS}s: {', '.join(pending)}")
            time.sleep(1)
        _step("draining", "done", "All CDC appliers caught up")

        _step("validating", "running", "Validating every target against the frozen source")
        result = run_validation(targets)
        _step(
            "validating", "done" if result["status"] == "passed" else "failed",
            f"validation #{result['run_id']}: {result['passed_checks']}/{result['total_checks']} checks passed",
        )
        if result["status"] != "passed":
            raise CutoverError("Validation failed; inspect the failed checks, fix, and retry")

        if "sqlserver" in targets:
            _step("constraints", "running", "Adding foreign keys WITH CHECK on SQL Server")
            target = get_target("sqlserver")
            try:
                target.add_constraints()
            finally:
                target.close()
            _step("constraints", "done", "Foreign keys enforced")

        set_control(cutover_status="completed")
        _step("completed", "done", "Ready: point the application at the new systems")

    except Exception as error:
        log.exception("Cutover failed")
        set_control(cutover_status="failed")
        _step("failed", "failed", f"{type(error).__name__}: {error}"[:500])


def start_cutover() -> dict:
    global _thread
    with _lock:
        if is_active():
            raise CutoverError("A cutover is already in progress")
        run = latest_run()
        if not run or run["status"] != "full_load_completed":
            raise CutoverError("The full load of the current migration run has not completed")
        targets = run_targets(run)

        connection = get_db_connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM cutover_events")
        finally:
            connection.close()

        _thread = threading.Thread(target=_runbook, args=(targets,), name="cutover", daemon=True)
        _thread.start()
        return {"status": "started", "targets": targets}


def rollback_cutover() -> dict:
    if is_active():
        raise CutoverError("Wait for the running cutover step to finish before rolling back")

    run = latest_run()
    if run and "sqlserver" in run_targets(run):
        target = get_target("sqlserver")
        try:
            target.drop_constraints()
        except Exception as error:
            log.warning("Could not drop SQL Server constraints: %s", error)
        finally:
            target.close()

    set_control(writes_frozen=False, cutover_status="rolled_back")
    log_cutover_event("rollback", "done", "Writes unfrozen; CDC keeps the targets in sync")
    return {"status": "rolled_back"}


def cutover_status() -> dict:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT step, status, message, created_at FROM cutover_events ORDER BY id")
            events = fetch_all_dicts(cursor)
    finally:
        connection.close()
    control = get_control()
    return {
        "active": is_active(),
        "cutover_status": control.get("cutover_status"),
        "writes_frozen": control.get("writes_frozen"),
        "events": events,
    }
