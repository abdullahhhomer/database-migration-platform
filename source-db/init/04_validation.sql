CREATE TABLE IF NOT EXISTS validation_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(30) NOT NULL,
    total_checks INTEGER NOT NULL DEFAULT 0,
    passed_checks INTEGER NOT NULL DEFAULT 0,
    failed_checks INTEGER NOT NULL DEFAULT 0
);

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

CREATE INDEX IF NOT EXISTS idx_validation_results_run_id
    ON validation_results(run_id);