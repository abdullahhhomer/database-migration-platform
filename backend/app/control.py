"""
Control-plane tables in the source Postgres: migration runs, jobs, CDC status,
cutover switches. ensure_control_schema() is idempotent and runs on every
backend/applier start, so databases created before these tables existed are
upgraded in place (init SQL only runs on a brand-new volume).
"""

from app.migration.reader import get_db_connection


CONTROL_DDL = """
CREATE TABLE IF NOT EXISTS migration_runs (
    id BIGSERIAL PRIMARY KEY,
    status VARCHAR(30) NOT NULL DEFAULT 'preparing',
    targets TEXT NOT NULL,
    workers INTEGER NOT NULL DEFAULT 1,
    batch_scale DOUBLE PRECISION NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    full_load_completed_at TIMESTAMPTZ,
    start_lsn PG_LSN,
    producer_events_at_start BIGINT NOT NULL DEFAULT 0,
    total_rows BIGINT NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS migration_jobs (
    id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    batch_size INTEGER NOT NULL DEFAULT 1000,
    total_rows BIGINT NOT NULL DEFAULT 0,
    migrated_rows BIGINT NOT NULL DEFAULT 0,
    last_id BIGINT NOT NULL DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE migration_jobs ADD COLUMN IF NOT EXISTS target VARCHAR(30) NOT NULL DEFAULT 'databricks';
ALTER TABLE migration_jobs ADD COLUMN IF NOT EXISTS run_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_migration_jobs_run ON migration_jobs(run_id);

CREATE TABLE IF NOT EXISTS migration_control (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    writes_frozen BOOLEAN NOT NULL DEFAULT FALSE,
    cutover_status VARCHAR(30) NOT NULL DEFAULT 'not_started',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE migration_control ADD COLUMN IF NOT EXISTS heartbeat_token TEXT;
INSERT INTO migration_control (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS cdc_status (
    target VARCHAR(30) PRIMARY KEY,
    last_applied_lsn PG_LSN,
    events_applied BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS run_id BIGINT;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS state VARCHAR(40);
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS events_seen BIGINT NOT NULL DEFAULT 0;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS events_published BIGINT NOT NULL DEFAULT 0;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMPTZ;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS seconds_behind DOUBLE PRECISION;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS last_heartbeat TEXT;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS message TEXT;

-- Watermark table: the cutover runbook inserts a token here; the CDC
-- producer forwards it to every Kinesis shard, and an applier that has seen
-- the token on all shards has provably applied everything before it.
CREATE TABLE IF NOT EXISTS cdc_heartbeat (
    id BIGSERIAL PRIMARY KEY,
    token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cutover_events (
    id BIGSERIAL PRIMARY KEY,
    step VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL,
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS validation_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(30) NOT NULL,
    total_checks INTEGER NOT NULL DEFAULT 0,
    passed_checks INTEGER NOT NULL DEFAULT 0,
    failed_checks INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS targets TEXT;
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS writes_frozen BOOLEAN;
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS migration_run_id BIGINT;

CREATE TABLE IF NOT EXISTS validation_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES validation_runs(id),
    check_type VARCHAR(50) NOT NULL DEFAULT 'count',
    check_name VARCHAR(255) NOT NULL,
    table_name VARCHAR(100),
    source_count BIGINT,
    target_count BIGINT,
    count_difference BIGINT,
    status VARCHAR(30) NOT NULL,
    checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE validation_results ADD COLUMN IF NOT EXISTS target VARCHAR(30) NOT NULL DEFAULT 'databricks';
ALTER TABLE validation_results ADD COLUMN IF NOT EXISTS source_value TEXT;
ALTER TABLE validation_results ADD COLUMN IF NOT EXISTS target_value TEXT;
ALTER TABLE validation_results ADD COLUMN IF NOT EXISTS details TEXT;
"""

# Arbitrary constant: serialises concurrent schema upgrades from the backend
# and the three CDC appliers starting at the same time.
_SCHEMA_LOCK_KEY = 74210


def ensure_control_schema() -> None:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
                cursor.execute(CONTROL_DDL)
    finally:
        connection.close()


def fetch_one_dict(cursor) -> dict | None:
    row = cursor.fetchone()
    if row is None:
        return None
    return {d[0]: v for d, v in zip(cursor.description, row)}


def fetch_all_dicts(cursor) -> list[dict]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def get_control() -> dict:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM migration_control WHERE id = 1")
            return fetch_one_dict(cursor) or {}
    finally:
        connection.close()


def set_control(**fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{name} = %s" for name in fields)
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE migration_control SET {assignments}, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                    tuple(fields.values()),
                )
    finally:
        connection.close()


def latest_run() -> dict | None:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM migration_runs ORDER BY id DESC LIMIT 1")
            return fetch_one_dict(cursor)
    finally:
        connection.close()


def run_targets(run: dict | None) -> list[str]:
    if not run:
        return []
    return [t for t in (run.get("targets") or "").split(",") if t]


def target_full_load_done(run_id: int, target: str) -> bool:
    """True when every full-load job of this run for this target completed."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'completed') AS done
                FROM migration_jobs
                WHERE run_id = %s AND target = %s
                """,
                (run_id, target),
            )
            total, done = cursor.fetchone()
            return total > 0 and total == done
    finally:
        connection.close()


def upsert_cdc_status(target: str, **fields) -> None:
    columns = ["target", *fields.keys(), "updated_at"]
    placeholders = ["%s"] * (len(fields) + 1) + ["CURRENT_TIMESTAMP"]
    updates = [f"{name} = EXCLUDED.{name}" for name in [*fields.keys(), "updated_at"]]

    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO cdc_status ({", ".join(columns)})
                    VALUES ({", ".join(placeholders)})
                    ON CONFLICT (target) DO UPDATE SET {", ".join(updates)}
                    """,
                    (target, *fields.values()),
                )
    finally:
        connection.close()


def log_cutover_event(step: str, status: str, message: str = "") -> None:
    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO cutover_events (step, status, message) VALUES (%s, %s, %s)",
                    (step, status, message),
                )
    finally:
        connection.close()
