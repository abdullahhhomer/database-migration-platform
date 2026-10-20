import os

import psycopg2
from databricks import sql
from fastapi import FastAPI

from app.migration.reader import read_table_batch
from app.migration.service import migrate_table
from app.migration.writer import create_table
from app.migration.writer import insert_rows

from app.validation.validator import validate_counts
from app.validation.validator import get_validation_history
from app.validation.validator import get_validation_run
from app.validation.readiness import get_migration_readiness



app = FastAPI(
    title="Database Migration & Validation Platform",
    version="1.0.0",
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
    connection = sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
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