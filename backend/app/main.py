import json
import logging
import os
from contextlib import asynccontextmanager

import psycopg2
from databricks import sql
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import aws, cutover, dashboard
from app.config import ALL_TARGETS, configured_targets, databricks_settings, default_workers
from app.control import ensure_control_schema
from app.migration import orchestrator
from app.migration.reader import read_table_batch
from app.migration.service import migrate_table
from app.migration.writer import create_table
from app.migration.writer import insert_rows

from app.validation.validator import run_validation
from app.validation.validator import validate_counts
from app.validation.validator import get_validation_history
from app.validation.validator import get_validation_run
from app.validation.readiness import get_migration_readiness


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
for _noisy in ("databricks.sql", "databricks.sdk", "urllib3", "botocore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_control_schema()
    orchestrator.mark_interrupted_runs()
    yield


app = FastAPI(
    title="Database Migration & Validation Platform",
    version="2.0.0",
    lifespan=lifespan,
)


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "migration_source"),
        user=os.getenv("POSTGRES_USER", "migration_user"),
        password=os.getenv("POSTGRES_PASSWORD", "migration_password"),
    )


@app.get("/health")
def health():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        return {
            "status": "healthy",
            "database": "connected",
        }
    finally:
        connection.close()


@app.get("/api/source/tables")
def get_source_tables():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """
            )

            tables = [row[0] for row in cursor.fetchall()]

        return {
            "tables": tables,
            "count": len(tables),
        }
    finally:
        connection.close()


@app.get("/api/source/tables/{table_name}/schema")
def get_table_schema(table_name: str):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                                ON tc.constraint_name = kcu.constraint_name
                                AND tc.table_schema = kcu.table_schema
                            WHERE tc.table_schema = 'public'
                              AND tc.table_name = c.table_name
                              AND tc.constraint_type = 'PRIMARY KEY'
                              AND kcu.column_name = c.column_name
                        )
                        THEN true
                        ELSE false
                    END AS is_primary_key
                FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                  AND c.table_name = %s
                ORDER BY c.ordinal_position;
                """,
                (table_name,),
            )

            columns = cursor.fetchall()

        if not columns:
            return {
                "table": table_name,
                "columns": [],
                "count": 0,
            }

        return {
            "table": table_name,
            "columns": [
                {
                    "name": row[0],
                    "data_type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[3],
                    "primary_key": row[4],
                }
                for row in columns
            ],
            "count": len(columns),
        }

    finally:
        connection.close()


@app.get("/api/source/schema")
def get_source_schema():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                                ON tc.constraint_name = kcu.constraint_name
                                AND tc.table_schema = kcu.table_schema
                            WHERE tc.table_schema = 'public'
                              AND tc.table_name = c.table_name
                              AND tc.constraint_type = 'PRIMARY KEY'
                              AND kcu.column_name = c.column_name
                        )
                        THEN true
                        ELSE false
                    END AS is_primary_key
                FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                ORDER BY c.table_name, c.ordinal_position;
                """
            )

            rows = cursor.fetchall()

        schema = {}

        for row in rows:
            table_name = row[0]

            if table_name not in schema:
                schema[table_name] = []

            schema[table_name].append(
                {
                    "name": row[1],
                    "data_type": row[2],
                    "nullable": row[3] == "YES",
                    "default": row[4],
                    "primary_key": row[5],
                }
            )

        return {
            "tables": schema,
            "count": len(schema),
        }

    finally:
        connection.close()


@app.get("/api/source/tables/{table_name}/count")
def get_table_count(table_name: str):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s;
                """,
                (table_name,),
            )

            exists = cursor.fetchone()[0]

            if not exists:
                return {
                    "table": table_name,
                    "count": 0,
                }

            cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            )

            count = cursor.fetchone()[0]

        return {
            "table": table_name,
            "count": count,
        }

    finally:
        connection.close()


@app.get("/health/databricks")
def databricks_health():
    settings = databricks_settings()
    connection = sql.connect(
        server_hostname=settings["host"],
        http_path=settings["http_path"],
        access_token=settings["token"],
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

        return {
            "status": "healthy",
            "databricks": "connected",
            "result": result[0],
        }

    finally:
        connection.close()


@app.get("/api/source/tables/{table_name}/batch")
def get_table_batch(
    table_name: str,
    last_id: int = 0,
    batch_size: int = 1000,
):
    if batch_size < 1 or batch_size > 5000:
        return {
            "error": "batch_size must be between 1 and 5000"
        }

    if last_id < 0:
        return {
            "error": "last_id cannot be negative"
        }

    return read_table_batch(
        table_name=table_name,
        last_id=last_id,
        batch_size=batch_size,
    )


@app.post("/api/migration/tables/{table_name}/create")
def create_migration_table(table_name: str):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default
                FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                  AND c.table_name = %s
                ORDER BY c.ordinal_position;
                """,
                (table_name,),
            )

            rows = cursor.fetchall()

        if not rows:
            return {
                "error": f"Source table '{table_name}' does not exist"
            }

        columns = [
            {
                "name": row[0],
                "data_type": row[1],
                "nullable": row[2] == "YES",
                "default": row[3],
            }
            for row in rows
        ]

        create_table(table_name, columns)

        return {
            "status": "created",
            "table": table_name,
            "target": (
                f"{os.getenv('DATABRICKS_CATALOG')}"
                f".{os.getenv('DATABRICKS_SCHEMA')}"
                f".{table_name}"
            ),
        }

    finally:
        connection.close()


@app.post("/api/migration/tables/{table_name}/migrate-batch")
def migrate_table_batch(
    table_name: str,
    last_id: int = 0,
    batch_size: int = 1000,
):
    batch = read_table_batch(
        table_name=table_name,
        last_id=last_id,
        batch_size=batch_size,
    )

    if batch["count"] == 0:
        return {
            "status": "complete",
            "table": table_name,
            "migrated": 0,
            "last_id": last_id,
        }

    insert_rows(
        table_name=table_name,
        columns=batch["columns"],
        rows=batch["rows"],
    )

    return {
        "status": "migrated",
        "table": table_name,
        "migrated": batch["count"],
        "last_id": batch["last_id"],
        "next_last_id": batch["next_last_id"],
    }


@app.post("/api/migration/tables/{table_name}/migrate")
def migrate_table_endpoint(
    table_name: str,
    batch_size: int = 1000,
    last_id: int = 0,
):
    if batch_size < 100 or batch_size > 5000:
        return {
            "error": "batch_size must be between 100 and 5000"
        }

    if last_id < 0:
        return {
            "error": "last_id cannot be negative"
        }

    return migrate_table(
        table_name=table_name,
        batch_size=batch_size,
    )


@app.get("/api/validation/counts")
def validate_migration_counts():
    return {
        "status": "completed",
        "results": validate_counts(),
    }


@app.get("/api/validation/runs/{run_id}")
def validation_run_details(run_id: int):
    result = get_validation_run(run_id)

    if result is None:
        return {
            "error": "Validation run not found"
        }

    return result


@app.get("/api/validation/runs")
def validation_history():
    return get_validation_history()



@app.get("/api/validation/readiness")
def migration_readiness():
    return get_migration_readiness()


# ============================================================
# AWS (mocked by moto locally)
# ============================================================

@app.get("/health/aws")
def aws_health():
    result = {"endpoint": aws.endpoint_url() or "aws", "region": aws.region()}

    def check(name, fn):
        try:
            result[name] = fn()
        except Exception as error:
            result[name] = {"error": f"{type(error).__name__}: {error}"}

    check("s3", lambda: {
        "bucket": aws.LANDING_BUCKET,
        "exists": aws.LANDING_BUCKET in [b["Name"] for b in aws.client("s3").list_buckets()["Buckets"]],
    })
    check("kinesis", lambda: {
        "stream": aws.CDC_STREAM,
        "status": aws.client("kinesis").describe_stream_summary(
            StreamName=aws.CDC_STREAM)["StreamDescriptionSummary"]["StreamStatus"],
        "shards": len(aws.client("kinesis").list_shards(StreamName=aws.CDC_STREAM)["Shards"]),
    })
    check("dynamodb", lambda: {
        "table": aws.CHECKPOINT_TABLE,
        "status": aws.client("dynamodb").describe_table(
            TableName=aws.CHECKPOINT_TABLE)["Table"]["TableStatus"],
    })
    check("secretsmanager", lambda: sorted(
        s["Name"] for s in aws.client("secretsmanager").list_secrets()["SecretList"]
    ))
    return result


@app.get("/api/cdc/peek")
def cdc_peek(limit: int = 20, seconds: int = 300):
    """Most recent CDC records on the Kinesis stream (debugging aid)."""
    import datetime as dt

    kinesis = aws.client("kinesis")
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)
    records = []
    for shard in kinesis.list_shards(StreamName=aws.CDC_STREAM)["Shards"]:
        iterator = kinesis.get_shard_iterator(
            StreamName=aws.CDC_STREAM, ShardId=shard["ShardId"],
            ShardIteratorType="AT_TIMESTAMP", Timestamp=start,
        )["ShardIterator"]
        response = kinesis.get_records(ShardIterator=iterator, Limit=1000)
        for r in response["Records"]:
            records.append({
                "shard": shard["ShardId"],
                "sequence_number": r["SequenceNumber"],
                "arrived_at": r["ApproximateArrivalTimestamp"],
                "event": json.loads(r["Data"]),
            })
    records.sort(key=lambda r: r["arrived_at"])
    return {"stream": aws.CDC_STREAM, "count": len(records), "records": records[-limit:]}


# ============================================================
# Migration runs (full load + CDC)
# ============================================================

class StartMigration(BaseModel):
    targets: list[str] | None = None
    workers: int | None = None
    reset: bool = True


@app.get("/api/config")
def platform_config():
    return {
        "targets_available": list(ALL_TARGETS),
        "targets_default": configured_targets(),
        "workers_default": default_workers(),
        "databricks_catalog": databricks_settings()["catalog"],
    }


@app.post("/api/migration/start")
def start_migration(request: StartMigration):
    targets = request.targets or configured_targets()
    unknown = [t for t in targets if t not in ALL_TARGETS]
    if unknown:
        raise HTTPException(400, f"Unknown target(s): {', '.join(unknown)}")
    try:
        return orchestrator.start_run(targets, request.workers, request.reset)
    except orchestrator.MigrationError as error:
        raise HTTPException(409, str(error))


@app.post("/api/migration/resume")
def resume_migration():
    try:
        return orchestrator.resume_run()
    except orchestrator.MigrationError as error:
        raise HTTPException(409, str(error))


@app.post("/api/migration/cancel")
def cancel_migration():
    try:
        return orchestrator.cancel_run()
    except orchestrator.MigrationError as error:
        raise HTTPException(409, str(error))


@app.get("/api/migration/status")
def migration_status(run_id: int | None = None):
    return orchestrator.run_status(run_id)


@app.get("/api/migration/runs")
def migration_runs(limit: int = 10):
    return orchestrator.run_history(limit)


# ============================================================
# Validation (all targets) and cutover
# ============================================================

@app.post("/api/validation/run")
def run_full_validation(targets: str | None = None, sample_size: int | None = None):
    selected = [t for t in targets.split(",") if t] if targets else None
    return run_validation(selected, sample_size)


@app.post("/api/cutover/start")
def start_cutover():
    try:
        return cutover.start_cutover()
    except cutover.CutoverError as error:
        raise HTTPException(409, str(error))


@app.post("/api/cutover/rollback")
def rollback_cutover():
    try:
        return cutover.rollback_cutover()
    except cutover.CutoverError as error:
        raise HTTPException(409, str(error))


@app.get("/api/cutover/status")
def get_cutover_status():
    return cutover.cutover_status()


@app.get("/api/dashboard")
def get_dashboard():
    return dashboard.snapshot()