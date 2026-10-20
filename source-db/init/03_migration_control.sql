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

CREATE INDEX IF NOT EXISTS idx_migration_jobs_table
    ON migration_jobs(table_name);

CREATE INDEX IF NOT EXISTS idx_migration_jobs_status
    ON migration_jobs(status);