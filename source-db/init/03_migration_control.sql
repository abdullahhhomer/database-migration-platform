-- One full-load job per (table, target). Targets: databricks, sqlserver, mongodb.
CREATE TABLE IF NOT EXISTS migration_jobs (
    id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    target VARCHAR(30) NOT NULL DEFAULT 'databricks',
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

CREATE INDEX IF NOT EXISTS idx_migration_jobs_table
    ON migration_jobs(table_name);

CREATE INDEX IF NOT EXISTS idx_migration_jobs_status
    ON migration_jobs(status);

CREATE INDEX IF NOT EXISTS idx_migration_jobs_table_target
    ON migration_jobs(table_name, target);


-- Single-row switchboard for the cutover runbook.
-- writes_frozen = TRUE pauses the transaction generator (the "application")
-- so CDC can drain and validation can compare a quiet source.
CREATE TABLE IF NOT EXISTS migration_control (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    writes_frozen BOOLEAN NOT NULL DEFAULT FALSE,
    cutover_status VARCHAR(30) NOT NULL DEFAULT 'not_started',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO migration_control (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;


-- CDC progress per target, written by the CDC appliers.
-- Lag in bytes = pg_wal_lsn_diff(pg_current_wal_lsn(), last_applied_lsn).
CREATE TABLE IF NOT EXISTS cdc_status (
    target VARCHAR(30) PRIMARY KEY,
    last_applied_lsn PG_LSN,
    events_applied BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);