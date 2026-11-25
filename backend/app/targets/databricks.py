"""
Databricks lakehouse target (bronze layer).

Full load:  Postgres batch -> Parquet -> S3 landing zone (raw)
                           -> Unity Catalog volume -> COPY INTO bronze.<table>
            If the volume upload is not available (e.g. workspace limits), it
            falls back to multi-row INSERTs over a single connection.
CDC:        de-duplicated micro-batches -> MERGE INTO bronze.<table>
            plus an append-only audit log in bronze.cdc_events.
"""

import datetime as dt
import io
import json
import logging
import os
import uuid
from decimal import Decimal

from databricks import sql

from app.config import databricks_configured, databricks_settings
from app.migration.landing import put_landing_file, rows_to_parquet
from app.migration.schema import BUSINESS_TABLES, get_columns
from app.migration.type_mapping import databricks_type
from app.targets.base import Change, Target


log = logging.getLogger("targets.databricks")

AUDIT_TABLE = "cdc_events"
VOLUME = "landing"
MERGE_CHUNK = 500


def _quote(identifier: str) -> str:
    return f"`{identifier}`"


def sql_literal(value, type_name: str) -> str:
    """Renders a Python value as a typed Databricks SQL literal."""
    if value is None:
        return f"CAST(NULL AS {type_name})"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, Decimal, float)):
        return f"CAST('{value}' AS {type_name})"
    if isinstance(value, dt.datetime):
        return f"CAST('{value.isoformat(sep=' ')}' AS {type_name})"
    if isinstance(value, dt.date):
        return f"CAST('{value.isoformat()}' AS {type_name})"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


class DatabricksTarget(Target):
    name = "databricks"
    batch_size = int(os.getenv("DATABRICKS_BATCH_ROWS", "50000"))

    def __init__(self):
        self.settings = databricks_settings()
        self._connection = None
        self._workspace = None
        self._volume_ok: bool | None = None
        self.audit_enabled = os.getenv("CDC_AUDIT_LOG", "true").lower() == "true"

    # --- connection ------------------------------------------------------
    @property
    def catalog(self) -> str:
        return self.settings["catalog"]

    @property
    def schema(self) -> str:
        return self.settings["schema"]

    def fq(self, table: str) -> str:
        return f"{_quote(self.catalog)}.{_quote(self.schema)}.{_quote(table)}"

    def connection(self):
        if not databricks_configured():
            raise RuntimeError(
                "Databricks is not configured: set DATABRICKS_HOST, "
                "DATABRICKS_HTTP_PATH and DATABRICKS_TOKEN in .env"
            )
        if self._connection is None:
            self._connection = sql.connect(
                server_hostname=self.settings["host"],
                http_path=self.settings["http_path"],
                access_token=self.settings["token"],
            )
        return self._connection

    def execute(self, query: str, fetch: bool = False, retry: bool = True):
        """
        retry=True re-runs the statement once on a fresh connection after a
        dropped session. Only idempotent statements may retry (DDL, COPY INTO,
        MERGE, SELECT): a plain INSERT that succeeded server-side but lost its
        response would be applied twice.
        """
        attempts = (1, 2) if retry else (1,)
        for attempt in attempts:
            try:
                with self.connection().cursor() as cursor:
                    cursor.execute(query)
                    if fetch:
                        return cursor.fetchall(), [d[0] for d in cursor.description]
                    return None
            except Exception:
                self.close()
                if attempt == attempts[-1]:
                    raise

    def scalar(self, query: str):
        rows, _ = self.execute(query, fetch=True)
        return rows[0][0] if rows else None

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    # --- lifecycle -------------------------------------------------------
    def _table_ddl(self, table: str, replace: bool) -> str:
        columns = ", ".join(
            f"{_quote(c.name)} {databricks_type(c)}" for c in get_columns(table)
        )
        verb = "CREATE OR REPLACE TABLE" if replace else "CREATE TABLE IF NOT EXISTS"
        return (
            f"{verb} {self.fq(table)} ({columns}) USING DELTA "
            "TBLPROPERTIES ('delta.feature.timestampNtz' = 'supported')"
        )

    def prepare(self, reset: bool) -> None:
        self.execute(
            f"CREATE SCHEMA IF NOT EXISTS {_quote(self.catalog)}.{_quote(self.schema)}"
        )
        try:
            self.execute(
                f"CREATE VOLUME IF NOT EXISTS "
                f"{_quote(self.catalog)}.{_quote(self.schema)}.{_quote(VOLUME)}"
            )
        except Exception as error:
            log.warning("Could not create volume, will use INSERT fallback: %s", error)
            self._volume_ok = False

        for table in BUSINESS_TABLES:
            self.execute(self._table_ddl(table, replace=reset))

        verb = "CREATE OR REPLACE TABLE" if reset else "CREATE TABLE IF NOT EXISTS"
        self.execute(
            f"{verb} {self.fq(AUDIT_TABLE)} ("
            "lsn STRING, table_name STRING, op STRING, pk BIGINT, "
            "commit_ts STRING, payload STRING, applied_at TIMESTAMP) USING DELTA"
        )

    # --- full load -------------------------------------------------------
    def load_units(self) -> list[str]:
        return list(BUSINESS_TABLES)

    def truncate_after(self, table: str, last_id: int) -> None:
        self.execute(f"DELETE FROM {self.fq(table)} WHERE id > {int(last_id)}")

    def _workspace_client(self):
        if self._workspace is None:
            from databricks.sdk import WorkspaceClient

            self._workspace = WorkspaceClient(
                host=f"https://{self.settings['host']}",
                token=self.settings["token"],
                auth_type="pat",
            )
        return self._workspace

    def _copy_into(self, table: str, run_id: int, file_name: str, data: bytes) -> None:
        directory = f"/Volumes/{self.catalog}/{self.schema}/{VOLUME}/run_{run_id}/{table}"
        self._workspace_client().files.upload(
            f"{directory}/{file_name}", io.BytesIO(data), overwrite=True
        )

        casts = ", ".join(
            f"CAST({_quote(c.name)} AS {databricks_type(c)}) AS {_quote(c.name)}"
            for c in get_columns(table)
        )
        self.execute(
            f"COPY INTO {self.fq(table)} "
            f"FROM (SELECT {casts} FROM '{directory}/') "
            f"FILEFORMAT = PARQUET FILES = ('{file_name}')"
        )

    def _insert_values(self, table: str, columns: list[str], rows: list[tuple]) -> None:
        types = {c.name: databricks_type(c) for c in get_columns(table)}
        column_list = ", ".join(_quote(c) for c in columns)
        for start in range(0, len(rows), 1000):
            chunk = rows[start:start + 1000]
            values = ", ".join(
                "(" + ", ".join(sql_literal(v, types[c]) for c, v in zip(columns, row)) + ")"
                for row in chunk
            )
            self.execute(f"INSERT INTO {self.fq(table)} ({column_list}) VALUES {values}", retry=False)

    def load_batch(self, table: str, columns: list[str], rows: list[tuple], run_id: int) -> None:
        if not rows:
            return

        first_id = rows[0][columns.index("id")]
        file_name = f"part-{first_id:012d}-{uuid.uuid4().hex[:8]}.parquet"

        # 1. Raw zone in the (mocked) S3 data lake.
        data = rows_to_parquet(table, columns, rows)
        put_landing_file(run_id, table, file_name, data)

        # 2. Load into the lakehouse.
        if self._volume_ok is not False:
            try:
                self._copy_into(table, run_id, file_name, data)
                self._volume_ok = True
                return
            except Exception as error:
                if self._volume_ok:
                    raise
                log.warning("Volume upload/COPY INTO unavailable, using INSERT fallback: %s", error)
                self._volume_ok = False

        self._insert_values(table, columns, rows)

    # --- CDC -------------------------------------------------------------
    def apply_changes(self, table: str, changes: list[Change]) -> None:
        columns = get_columns(table)
        names = [c.name for c in columns]
        types = {c.name: databricks_type(c) for c in columns}

        alias = ", ".join(_quote(n) for n in ["_op", *names])
        updates = ", ".join(f"t.{_quote(n)} = s.{_quote(n)}" for n in names if n != "id")
        insert_cols = ", ".join(_quote(n) for n in names)
        insert_vals = ", ".join(f"s.{_quote(n)}" for n in names)

        for start in range(0, len(changes), MERGE_CHUNK):
            chunk = changes[start:start + MERGE_CHUNK]
            value_rows = []
            for change in chunk:
                row = dict(change.row)
                row["id"] = change.pk
                literals = [f"'{change.op}'"] + [
                    sql_literal(row.get(n) if change.op != "D" or n == "id" else None, types[n])
                    for n in names
                ]
                value_rows.append("(" + ", ".join(literals) + ")")

            self.execute(
                f"MERGE INTO {self.fq(table)} AS t "
                f"USING (SELECT * FROM VALUES {', '.join(value_rows)} AS s({alias})) AS s "
                "ON t.`id` = s.`id` "
                "WHEN MATCHED AND s.`_op` = 'D' THEN DELETE "
                f"WHEN MATCHED THEN UPDATE SET {updates} "
                f"WHEN NOT MATCHED AND s.`_op` <> 'D' THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
            )

    def append_audit(self, events: list[dict]) -> None:
        if not self.audit_enabled or not events:
            return
        for start in range(0, len(events), MERGE_CHUNK):
            chunk = events[start:start + MERGE_CHUNK]
            values = ", ".join(
                "("
                + ", ".join(
                    [
                        sql_literal(e.get("lsn"), "STRING"),
                        sql_literal(e.get("table"), "STRING"),
                        sql_literal(e.get("op"), "STRING"),
                        sql_literal(e.get("pk"), "BIGINT"),
                        sql_literal(e.get("commit_ts"), "STRING"),
                        sql_literal(json.dumps(e.get("row") or {}), "STRING"),
                        "current_timestamp()",
                    ]
                )
                + ")"
                for e in chunk
            )
            self.execute(f"INSERT INTO {self.fq(AUDIT_TABLE)} VALUES {values}", retry=False)

    # --- validation ------------------------------------------------------
    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {self.fq(table)}"))

    def sum_column(self, table: str, column: str):
        return self.scalar(f"SELECT SUM({_quote(column)}) FROM {self.fq(table)}")

    def duplicate_ids(self, table: str) -> int | None:
        # Delta Lake does not enforce primary keys, so duplicates must be checked.
        return int(self.scalar(
            f"SELECT COUNT(*) - COUNT(DISTINCT id) FROM {self.fq(table)}"
        ))

    def orphans(self, child: str, fk: str, parent: str, parent_key: str) -> int:
        return int(self.scalar(
            f"SELECT COUNT(*) FROM {self.fq(child)} c "
            f"LEFT JOIN {self.fq(parent)} p ON c.{_quote(fk)} = p.{_quote(parent_key)} "
            f"WHERE c.{_quote(fk)} IS NOT NULL AND p.{_quote(parent_key)} IS NULL"
        ))

    def fetch_rows(self, table: str, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        id_list = ", ".join(str(int(i)) for i in ids)
        rows, names = self.execute(
            f"SELECT * FROM {self.fq(table)} WHERE id IN ({id_list})", fetch=True
        )
        result = {}
        for row in rows:
            record = dict(zip(names, row))
            result[int(record["id"])] = record
        return result
