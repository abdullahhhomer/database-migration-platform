"""
SQL Server target (stand-in for Amazon RDS for SQL Server).

Relational -> relational with type mapping (Postgres -> T-SQL).
Full load uses pyodbc fast_executemany. CDC uses MERGE upserts and deletes.
Foreign keys are NOT created during the load (CDC can deliver a child row
before its parent); they are added WITH CHECK at cutover, which also proves
referential integrity on the target.
"""

import os

import pyodbc

from app.config import sqlserver_settings
from app.migration.schema import BUSINESS_TABLES, RELATIONSHIPS, get_columns
from app.migration.type_mapping import sqlserver_type
from app.targets.base import Change, Target


def _q(identifier: str) -> str:
    return f"[{identifier}]"


def _odbc_value(value: str) -> str:
    return "{" + str(value).replace("}", "}}") + "}"


class SqlServerTarget(Target):
    name = "sqlserver"
    batch_size = int(os.getenv("SQLSERVER_BATCH_ROWS", "10000"))

    def __init__(self):
        self.settings = sqlserver_settings()
        self.driver = os.getenv("SQLSERVER_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
        self._connection = None

    # --- connection ------------------------------------------------------
    def _connection_string(self, database: str) -> str:
        s = self.settings
        return (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={s['host']},{s['port']};"
            f"DATABASE={database};"
            f"UID={_odbc_value(s['user'])};"
            f"PWD={_odbc_value(s['password'])};"
            "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15"
        )

    def _ensure_database(self) -> None:
        database = self.settings["database"]
        with pyodbc.connect(self._connection_string("master"), autocommit=True) as conn:
            conn.execute(
                f"IF DB_ID(N'{database}') IS NULL CREATE DATABASE {_q(database)}"
            )

    def connection(self):
        if self._connection is None:
            self._ensure_database()
            self._connection = pyodbc.connect(
                self._connection_string(self.settings["database"]),
                autocommit=False,
            )
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def scalar(self, query: str, *params):
        cursor = self.connection().cursor()
        try:
            cursor.execute(query, *params)
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            cursor.close()

    def fq(self, table: str) -> str:
        return f"dbo.{_q(table)}"

    # --- lifecycle -------------------------------------------------------
    def prepare(self, reset: bool) -> None:
        conn = self.connection()
        cursor = conn.cursor()

        if reset:
            self.drop_constraints()
            for table in reversed(BUSINESS_TABLES):
                cursor.execute(f"DROP TABLE IF EXISTS {self.fq(table)}")

        for table in BUSINESS_TABLES:
            column_ddl = ", ".join(
                f"{_q(c.name)} {sqlserver_type(c)} {'NULL' if c.nullable else 'NOT NULL'}"
                for c in get_columns(table)
            )
            cursor.execute(
                f"IF OBJECT_ID(N'dbo.{table}', N'U') IS NULL "
                f"CREATE TABLE {self.fq(table)} ({column_ddl}, "
                f"CONSTRAINT {_q('PK_' + table)} PRIMARY KEY ({_q('id')}))"
            )

        conn.commit()
        cursor.close()

    # --- full load -------------------------------------------------------
    def load_units(self) -> list[str]:
        return list(BUSINESS_TABLES)

    def truncate_after(self, table: str, last_id: int) -> None:
        conn = self.connection()
        conn.execute(f"DELETE FROM {self.fq(table)} WHERE id > ?", int(last_id))
        conn.commit()

    def load_batch(self, table: str, columns: list[str], rows: list[tuple], run_id: int) -> None:
        if not rows:
            return
        conn = self.connection()
        cursor = conn.cursor()
        cursor.fast_executemany = True
        try:
            cursor.executemany(
                f"INSERT INTO {self.fq(table)} ({', '.join(_q(c) for c in columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [tuple(row) for row in rows],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    # --- CDC -------------------------------------------------------------
    def apply_changes(self, table: str, changes: list[Change]) -> None:
        columns = get_columns(table)
        names = [c.name for c in columns]

        source_select = ", ".join(
            f"CAST(? AS {sqlserver_type(c)}) AS {_q(c.name)}" for c in columns
        )
        updates = ", ".join(f"t.{_q(n)} = s.{_q(n)}" for n in names if n != "id")
        merge_sql = (
            f"MERGE {self.fq(table)} WITH (HOLDLOCK) AS t "
            f"USING (SELECT {source_select}) AS s ON t.[id] = s.[id] "
            f"WHEN MATCHED THEN UPDATE SET {updates} "
            f"WHEN NOT MATCHED THEN INSERT ({', '.join(_q(n) for n in names)}) "
            f"VALUES ({', '.join('s.' + _q(n) for n in names)});"
        )

        conn = self.connection()
        cursor = conn.cursor()
        try:
            for change in changes:
                if change.op == "D":
                    cursor.execute(f"DELETE FROM {self.fq(table)} WHERE id = ?", change.pk)
                else:
                    row = dict(change.row)
                    row["id"] = change.pk
                    cursor.execute(merge_sql, *[row.get(n) for n in names])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    # --- validation ------------------------------------------------------
    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT_BIG(*) FROM {self.fq(table)}"))

    def sum_column(self, table: str, column: str):
        return self.scalar(f"SELECT SUM({_q(column)}) FROM {self.fq(table)}")

    def orphans(self, child: str, fk: str, parent: str, parent_key: str) -> int:
        return int(self.scalar(
            f"SELECT COUNT_BIG(*) FROM {self.fq(child)} c "
            f"LEFT JOIN {self.fq(parent)} p ON c.{_q(fk)} = p.{_q(parent_key)} "
            f"WHERE c.{_q(fk)} IS NOT NULL AND p.{_q(parent_key)} IS NULL"
        ))

    def fetch_rows(self, table: str, ids: list[int]) -> dict[int, dict]:
        result: dict[int, dict] = {}
        cursor = self.connection().cursor()
        try:
            for start in range(0, len(ids), 1000):
                chunk = [int(i) for i in ids[start:start + 1000]]
                cursor.execute(
                    f"SELECT * FROM {self.fq(table)} WHERE id IN ({', '.join('?' for _ in chunk)})",
                    *chunk,
                )
                names = [d[0] for d in cursor.description]
                for row in cursor.fetchall():
                    record = dict(zip(names, row))
                    result[int(record["id"])] = record
        finally:
            cursor.close()
        return result

    # --- cutover ---------------------------------------------------------
    @staticmethod
    def _fk_name(child: str, fk: str) -> str:
        return f"FK_{child}_{fk}"

    def add_constraints(self) -> None:
        conn = self.connection()
        try:
            for child, fk, parent, parent_key in RELATIONSHIPS:
                name = self._fk_name(child, fk)
                conn.execute(
                    f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'{name}') "
                    f"ALTER TABLE {self.fq(child)} WITH CHECK ADD CONSTRAINT {_q(name)} "
                    f"FOREIGN KEY ({_q(fk)}) REFERENCES {self.fq(parent)} ({_q(parent_key)})"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def drop_constraints(self) -> None:
        conn = self.connection()
        for child, fk, _parent, _key in RELATIONSHIPS:
            name = self._fk_name(child, fk)
            conn.execute(
                f"IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'{name}') "
                f"ALTER TABLE {self.fq(child)} DROP CONSTRAINT {_q(name)}"
            )
        conn.commit()
