// Shapes returned by GET /api/dashboard (backend/app/dashboard.py).

export type TargetName = "databricks" | "sqlserver" | "mongodb";

export interface Control {
  writes_frozen: boolean;
  cutover_status: string;
  heartbeat_token: string | null;
  updated_at: string;
}

export interface SourceTable {
  table_name: string;
  approx_rows: number;
  changes: number;
}

export interface Source {
  tables: SourceTable[];
  approx_rows: number;
  writes_per_second: number | null;
  slot: { exists: boolean; active: boolean; lag_bytes: number | null };
}

export interface Run {
  id: number;
  status: string;
  targets: string;
  workers: number;
  started_at: string;
  full_load_completed_at: string | null;
  start_lsn: string | null;
  total_rows: number;
  error_message: string | null;
}

export interface Job {
  id: number;
  table_name: string;
  target: TargetName;
  status: "pending" | "running" | "completed" | "failed";
  total_rows: number;
  migrated_rows: number;
  batch_size: number;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  seconds: number | null;
  rows_per_second: number | null;
  percent: number;
}

export interface Migration {
  run: Run | null;
  active?: boolean;
  jobs: Job[];
  timing: {
    workers: number;
    elapsed_seconds: number;
    rows_migrated: number;
    rows_total: number;
    rows_per_second: number | null;
  } | null;
}

export interface HistoryRun {
  id: number;
  status: string;
  targets: string;
  workers: number;
  started_at: string;
  full_load_completed_at: string | null;
  total_rows: number;
  seconds: number | null;
  migrated_rows: number;
  rows_per_second: number | null;
}

export interface Landing {
  bucket: string;
  prefix: string;
  files: number;
  bytes: number;
  files_per_table: Record<string, number>;
  endpoint: string;
}

export interface CdcTarget {
  target: TargetName;
  state: string | null;
  run_id: number | null;
  events_applied: number;
  events_seen: number;
  seconds_behind: number | null;
  last_applied_lsn: string | null;
  last_heartbeat: string | null;
  message: string | null;
  events_per_second: number | null;
  backlog: number | null;
}

export interface Producer {
  state: string | null;
  events_published: number;
  last_applied_lsn: string | null;
  message: string | null;
  events_per_second: number | null;
  since_run_start: number;
}

export interface Cdc {
  producer: Producer | null;
  targets: Partial<Record<TargetName, CdcTarget>>;
}

export interface CheckResult {
  target: TargetName;
  check_type: string;
  check_name: string;
  table_name: string | null;
  source_value: string | null;
  target_value: string | null;
  status: "passed" | "failed";
  details: string | null;
}

export interface Validation {
  run_id: number;
  status: string;
  targets: string | null;
  writes_frozen: boolean | null;
  migration_run_id: number | null;
  total_checks: number;
  passed_checks: number;
  failed_checks: number;
  started_at: string | null;
  completed_at: string | null;
  results: CheckResult[];
}

export interface Condition {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Readiness {
  status: "ready" | "not_ready";
  cutover_status: string;
  conditions: Condition[];
}

export interface CutoverEvent {
  step: string;
  status: string;
  message: string | null;
  created_at: string;
}

export interface Cutover {
  active: boolean;
  cutover_status: string;
  writes_frozen: boolean;
  events: CutoverEvent[];
}

type Maybe<T> = T | { error: string };

export interface Dashboard {
  generated_at: string;
  control: Maybe<Control>;
  source: Maybe<Source>;
  migration: Maybe<Migration>;
  history: Maybe<HistoryRun[]>;
  landing: Maybe<Landing>;
  cdc: Maybe<Cdc>;
  validation: Maybe<Validation> | null;
  readiness: Maybe<Readiness>;
  cutover: Maybe<Cutover>;
}

export interface PlatformConfig {
  targets_available: TargetName[];
  targets_default: TargetName[];
  workers_default: number;
  databricks_catalog: string;
}

export function ok<T>(value: Maybe<T> | null | undefined): T | null {
  if (!value || (typeof value === "object" && "error" in (value as object))) return null;
  return value as T;
}

export function errorOf(value: unknown): string | null {
  if (value && typeof value === "object" && "error" in value) return String((value as { error: unknown }).error);
  return null;
}
