"""Aggregated, failure-tolerant snapshot of the whole platform for the UI."""

import datetime as dt
import threading
import time

from app import aws
from app.control import fetch_all_dicts, get_control, latest_run
from app.cutover import cutover_status
from app.migration.landing import landing_stats
from app.migration.orchestrator import CDC_SLOT, run_history, run_status
from app.migration.reader import get_db_connection
from app.migration.schema import BUSINESS_TABLES
from app.validation.readiness import get_migration_readiness
from app.validation.validator import latest_validation


_rate_lock = threading.Lock()
_previous: dict[str, tuple[float, int]] = {}


def _rate(key: str, value: int) -> float | None:
    """Per-second rate of a monotonically increasing counter between polls."""
    now = time.monotonic()
    with _rate_lock:
        previous = _previous.get(key)
        _previous[key] = (now, value)
    if not previous:
        return None
    elapsed = now - previous[0]
    if elapsed <= 0 or value < previous[1]:
        return None
    return round((value - previous[1]) / elapsed, 2)


def _safe(fn):
    try:
        return fn()
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def _source() -> dict:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT relname AS table_name, n_live_tup AS approx_rows,
                       n_tup_ins + n_tup_upd + n_tup_del AS changes
                FROM pg_stat_user_tables WHERE relname = ANY(%s)
                """,
                (BUSINESS_TABLES,),
            )
            tables = fetch_all_dicts(cursor)
            cursor.execute(
                """
                SELECT active,
                       pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)::BIGINT AS lag_bytes
                FROM pg_replication_slots WHERE slot_name = %s
                """,
                (CDC_SLOT,),
            )
            slot = cursor.fetchone()
    finally:
        connection.close()

    total_changes = sum(t["changes"] for t in tables)
    return {
        "tables": sorted(tables, key=lambda t: BUSINESS_TABLES.index(t["table_name"])),
        "approx_rows": sum(t["approx_rows"] for t in tables),
        "writes_per_second": _rate("source_changes", total_changes),
        "slot": {"exists": slot is not None, "active": slot[0] if slot else False,
                 "lag_bytes": slot[1] if slot else None},
    }


def _cdc(run: dict | None) -> dict:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM cdc_status ORDER BY target")
            rows = {r["target"]: r for r in fetch_all_dicts(cursor)}
    finally:
        connection.close()

    producer = rows.pop("producer", None)
    published = producer["events_published"] if producer else 0
    since_run = published - (run["producer_events_at_start"] if run else 0)

    if producer:
        producer["events_per_second"] = _rate("producer", published)
        producer["since_run_start"] = max(0, since_run)

    for name, row in rows.items():
        row["events_per_second"] = _rate(f"applied:{name}", row.get("events_applied") or 0)
        same_run = run and row.get("run_id") == run["id"]
        if row.get("state") == "waiting_for_full_load":
            row["backlog"] = max(0, since_run)
        elif same_run:
            row["backlog"] = max(0, since_run - (row.get("events_seen") or 0))
        else:
            row["backlog"] = None

    return {"producer": producer, "targets": rows}


def _landing(run: dict | None) -> dict:
    stats = landing_stats(run["id"] if run else None)
    stats["endpoint"] = aws.endpoint_url() or "aws"
    return stats


def snapshot() -> dict:
    run = _safe(latest_run)
    run = run if isinstance(run, dict) and "error" not in run else None
    validation = _safe(latest_validation)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "control": _safe(get_control),
        "source": _safe(_source),
        "migration": _safe(run_status),
        "history": _safe(run_history),
        "landing": _safe(lambda: _landing(run)),
        "cdc": _safe(lambda: _cdc(run)),
        "validation": validation,
        "readiness": _safe(get_migration_readiness),
        "cutover": _safe(cutover_status),
    }
