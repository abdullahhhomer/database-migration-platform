"""
Source-to-target validation across every migration target.

Checks per target:
  count                  row count per table
  referential_integrity  orphaned foreign keys per relationship
  checksum               SUM of money columns (catches truncation/rounding)
  duplicates             duplicate primary keys (Delta Lake does not enforce PKs)
  sample                 N random source rows compared field by field

Source metrics are read in one REPEATABLE READ snapshot. While the source is
live (writes not frozen), differences can simply be changes still in flight;
the cutover runbook freezes writes and drains CDC before its final validation.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import psycopg2.extensions

from app.config import configured_targets
from app.control import fetch_all_dicts, fetch_one_dict, get_control, latest_run, run_targets
from app.migration.reader import get_db_connection
from app.migration.schema import BUSINESS_TABLES, MONEY_COLUMNS, RELATIONSHIPS
from app.migration.type_mapping import normalize_for_compare
from app.targets import get_target


log = logging.getLogger("validation")

SAMPLE_SIZE = int(os.getenv("VALIDATION_SAMPLE_SIZE", "200"))

# Kept for backwards compatibility with earlier imports.
TABLES = BUSINESS_TABLES


# --- source snapshot ---------------------------------------------------------
def collect_source_metrics(sample_size: int) -> dict:
    connection = get_db_connection()
    connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_REPEATABLE_READ)
    try:
        with connection.cursor() as cursor:
            counts = {}
            for table in BUSINESS_TABLES:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = cursor.fetchone()[0]

            sums = {}
            for table, column in MONEY_COLUMNS.items():
                cursor.execute(f'SELECT SUM("{column}") FROM "{table}"')
                sums[table] = cursor.fetchone()[0]

            orphans = {}
            for child, fk, parent, key in RELATIONSHIPS:
                cursor.execute(
                    f'SELECT COUNT(*) FROM "{child}" c LEFT JOIN "{parent}" p '
                    f'ON c."{fk}" = p."{key}" WHERE c."{fk}" IS NOT NULL AND p."{key}" IS NULL'
                )
                orphans[(child, fk)] = cursor.fetchone()[0]

            samples = {}
            for table in BUSINESS_TABLES:
                cursor.execute(
                    f'SELECT * FROM "{table}" WHERE id IN '
                    f'(SELECT id FROM "{table}" ORDER BY random() LIMIT %s)',
                    (sample_size,),
                )
                samples[table] = {r["id"]: r for r in fetch_all_dicts(cursor)}

        connection.rollback()
        return {"counts": counts, "sums": sums, "orphans": orphans, "samples": samples}
    finally:
        connection.close()


# --- per-target checks -------------------------------------------------------
def _result(target, check_type, name, table, source, target_value, passed, details=""):
    numeric = isinstance(source, int) and isinstance(target_value, int)
    return {
        "target": target,
        "check_type": check_type,
        "check_name": name,
        "table_name": table,
        "source_count": source if numeric else None,
        "target_count": target_value if numeric else None,
        "count_difference": (source - target_value) if numeric else None,
        "source_value": None if source is None else str(source),
        "target_value": None if target_value is None else str(target_value),
        "status": "passed" if passed else "failed",
        "details": details or None,
    }


def compare_rows(source_rows: dict, target_rows: dict) -> tuple[int, list[str]]:
    mismatches = 0
    examples = []
    for pk, source in source_rows.items():
        target = target_rows.get(pk)
        if target is None:
            mismatches += 1
            if len(examples) < 3:
                examples.append(f"id {pk}: missing")
            continue
        for column, value in source.items():
            left = normalize_for_compare(value)
            right = normalize_for_compare(target.get(column))
            if left != right:
                mismatches += 1
                if len(examples) < 3:
                    examples.append(f"id {pk}.{column}: {left!r} != {right!r}")
                break
    return mismatches, examples


def validate_target(name: str, source: dict, live_note: str) -> list[dict]:
    results = []
    target = get_target(name)
    try:
        for table in BUSINESS_TABLES:
            expected = source["counts"][table]
            actual = target.count(table)
            results.append(_result(
                name, "count", f"{table} row count", table, expected, actual,
                expected == actual, live_note if expected != actual else "",
            ))

        for child, fk, parent, key in RELATIONSHIPS:
            expected = source["orphans"][(child, fk)]
            actual = target.orphans(child, fk, parent, key)
            results.append(_result(
                name, "referential_integrity", f"{child}.{fk} -> {parent}.{key}",
                child, expected, actual, actual == 0 and expected == 0,
            ))

        for table, column in MONEY_COLUMNS.items():
            expected = source["sums"][table]
            actual = target.sum_column(table, column)
            passed = normalize_for_compare(expected) == normalize_for_compare(actual)
            results.append(_result(
                name, "checksum", f"SUM({table}.{column})", table, expected, actual,
                passed, live_note if not passed else "",
            ))

        for table in BUSINESS_TABLES:
            duplicates = target.duplicate_ids(table)
            if duplicates is not None:
                results.append(_result(
                    name, "duplicates", f"{table} duplicate ids", table, 0, duplicates,
                    duplicates == 0,
                ))

        for table in BUSINESS_TABLES:
            rows = source["samples"][table]
            target_rows = target.fetch_rows(table, list(rows))
            mismatches, examples = compare_rows(rows, target_rows)
            results.append(_result(
                name, "sample", f"{table} sampled rows", table, len(rows),
                len(rows) - mismatches, mismatches == 0,
                "; ".join(examples) + (f" {live_note}" if mismatches else ""),
            ))

    except Exception as error:
        log.exception("Validation of %s failed", name)
        results.append(_result(
            name, "connectivity", f"{name} reachable", None, None, None, False,
            f"{type(error).__name__}: {error}"[:500],
        ))
    finally:
        target.close()

    return results


# --- persistence -------------------------------------------------------------
def create_validation_run(targets: list[str], writes_frozen: bool, migration_run_id) -> int:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO validation_runs (status, targets, writes_frozen, migration_run_id)
                    VALUES ('running', %s, %s, %s) RETURNING id
                    """,
                    (",".join(targets), writes_frozen, migration_run_id),
                )
                return cursor.fetchone()[0]
    finally:
        connection.close()


def save_results(run_id: int, results: list[dict]) -> None:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                for r in results:
                    cursor.execute(
                        """
                        INSERT INTO validation_results (
                            run_id, target, check_type, check_name, table_name,
                            source_count, target_count, count_difference,
                            source_value, target_value, status, details
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            run_id, r["target"], r["check_type"], r["check_name"], r["table_name"],
                            r["source_count"], r["target_count"], r["count_difference"],
                            r["source_value"], r["target_value"], r["status"], r["details"],
                        ),
                    )
    finally:
        connection.close()


def complete_validation_run(run_id: int, total: int, passed: int, failed: int) -> None:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE validation_runs
                    SET completed_at = CURRENT_TIMESTAMP, status = %s,
                        total_checks = %s, passed_checks = %s, failed_checks = %s
                    WHERE id = %s
                    """,
                    ("passed" if failed == 0 and total > 0 else "failed", total, passed, failed, run_id),
                )
    finally:
        connection.close()


# --- entry points ------------------------------------------------------------
def run_validation(targets: list[str] | None = None, sample_size: int | None = None) -> dict:
    migration_run = latest_run()
    targets = targets or run_targets(migration_run) or configured_targets()
    frozen = bool(get_control().get("writes_frozen"))
    live_note = "" if frozen else "(source is live: may be changes still in flight)"

    run_id = create_validation_run(targets, frozen, migration_run["id"] if migration_run else None)
    results: list[dict] = []
    try:
        source = collect_source_metrics(sample_size or SAMPLE_SIZE)
        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            for target_results in pool.map(lambda t: validate_target(t, source, live_note), targets):
                results.extend(target_results)
    finally:
        save_results(run_id, results)
        passed = sum(1 for r in results if r["status"] == "passed")
        failed = len(results) - passed
        complete_validation_run(run_id, len(results), passed, failed)

    by_target = {}
    for t in targets:
        checks = [r for r in results if r["target"] == t]
        by_target[t] = {
            "status": "passed" if checks and all(c["status"] == "passed" for c in checks) else "failed",
            "passed": sum(1 for c in checks if c["status"] == "passed"),
            "failed": sum(1 for c in checks if c["status"] != "passed"),
        }

    return {
        "run_id": run_id,
        "status": "passed" if failed == 0 and results else "failed",
        "writes_frozen": frozen,
        "targets": by_target,
        "total_checks": len(results),
        "passed_checks": passed,
        "failed_checks": failed,
        "results": results,
    }


def validate_counts():
    """Backwards-compatible name used by GET /api/validation/counts."""
    return run_validation()


def get_validation_history(limit: int = 50):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id AS run_id, started_at, completed_at, status, targets, writes_frozen,
                       migration_run_id, total_checks, passed_checks, failed_checks
                FROM validation_runs ORDER BY id DESC LIMIT %s
                """,
                (limit,),
            )
            return fetch_all_dicts(cursor)
    finally:
        connection.close()


def get_validation_run(run_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id AS run_id, started_at, completed_at, status, targets, writes_frozen,
                       migration_run_id, total_checks, passed_checks, failed_checks
                FROM validation_runs WHERE id = %s
                """,
                (run_id,),
            )
            run = fetch_one_dict(cursor)
            if not run:
                return None
            cursor.execute(
                """
                SELECT target, check_type, check_name, table_name, source_count, target_count,
                       count_difference, source_value, target_value, status, details, checked_at
                FROM validation_results WHERE run_id = %s ORDER BY id
                """,
                (run_id,),
            )
            run["results"] = fetch_all_dicts(cursor)
            return run
    finally:
        connection.close()


def latest_validation() -> dict | None:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM validation_runs WHERE status <> 'running' ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
    finally:
        connection.close()
    return get_validation_run(row[0]) if row else None
