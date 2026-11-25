"""
Type mapping between PostgreSQL and every target format.

    PostgreSQL                    Databricks      SQL Server       Parquet (S3)        MongoDB
    bigint                        BIGINT          BIGINT           int64               int64
    integer                       INT             INT              int32               int32
    numeric(p,s)                  DECIMAL(p,s)    DECIMAL(p,s)     decimal128(p,s)     Decimal128
    varchar(n) / text             STRING          NVARCHAR(n|MAX)  string              string
    timestamp without time zone   TIMESTAMP_NTZ   DATETIME2(6)     timestamp[us]       date (ms)
    timestamp with time zone      TIMESTAMP       DATETIMEOFFSET   timestamp[us, UTC]  date (ms)
    boolean                       BOOLEAN         BIT              bool                bool
    date                          DATE            DATE             date32              date
"""

import datetime as dt
from decimal import Decimal

import pyarrow as pa

from app.migration.schema import Column


def _decimal_parts(column: Column) -> tuple[int, int]:
    precision = column.precision or 38
    scale = column.scale if column.scale is not None else 10
    return min(precision, 38), scale


def databricks_type(column: Column) -> str:
    t = column.data_type
    if t == "bigint":
        return "BIGINT"
    if t == "integer":
        return "INT"
    if t == "smallint":
        return "SMALLINT"
    if t in ("numeric", "decimal"):
        p, s = _decimal_parts(column)
        return f"DECIMAL({p},{s})"
    if t in ("double precision", "real"):
        return "DOUBLE"
    if t == "timestamp without time zone":
        return "TIMESTAMP_NTZ"
    if t == "timestamp with time zone":
        return "TIMESTAMP"
    if t == "date":
        return "DATE"
    if t == "boolean":
        return "BOOLEAN"
    return "STRING"


def sqlserver_type(column: Column) -> str:
    t = column.data_type
    if t == "bigint":
        return "BIGINT"
    if t == "integer":
        return "INT"
    if t == "smallint":
        return "SMALLINT"
    if t in ("numeric", "decimal"):
        p, s = _decimal_parts(column)
        return f"DECIMAL({p},{s})"
    if t in ("double precision", "real"):
        return "FLOAT"
    if t == "timestamp without time zone":
        return "DATETIME2(6)"
    if t == "timestamp with time zone":
        return "DATETIMEOFFSET(6)"
    if t == "date":
        return "DATE"
    if t == "boolean":
        return "BIT"
    if t == "character varying" and column.max_length and column.max_length <= 4000:
        return f"NVARCHAR({column.max_length})"
    return "NVARCHAR(MAX)"


def arrow_type(column: Column) -> pa.DataType:
    t = column.data_type
    if t == "bigint":
        return pa.int64()
    if t == "integer":
        return pa.int32()
    if t == "smallint":
        return pa.int16()
    if t in ("numeric", "decimal"):
        p, s = _decimal_parts(column)
        return pa.decimal128(p, s)
    if t in ("double precision", "real"):
        return pa.float64()
    if t == "timestamp without time zone":
        return pa.timestamp("us")
    if t == "timestamp with time zone":
        return pa.timestamp("us", tz="UTC")
    if t == "date":
        return pa.date32()
    if t == "boolean":
        return pa.bool_()
    return pa.string()


def arrow_schema(columns: list[Column]) -> pa.Schema:
    return pa.schema(
        [pa.field(c.name, arrow_type(c), nullable=c.nullable) for c in columns]
    )


def from_wal2json(value, pg_type: str):
    """
    Converts a wal2json value back to a Python value. The CDC worker runs
    wal2json with numeric-data-types-as-string, so numbers arrive as text
    (no float rounding); `pg_type` is wal2json's type name, e.g.
    'numeric(12,2)', 'character varying(50)', 'timestamp without time zone'.
    """
    if value is None:
        return None

    t = pg_type.lower()

    if t in ("bigint", "integer", "smallint", "int8", "int4", "int2"):
        return int(value)
    if t.startswith("numeric") or t.startswith("decimal"):
        return Decimal(str(value))
    if t in ("double precision", "real", "float8", "float4"):
        return float(value)
    if t == "boolean" or t == "bool":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("t", "true", "1")
    if t.startswith("timestamp"):
        return dt.datetime.fromisoformat(str(value))
    if t == "date":
        return dt.date.fromisoformat(str(value))
    return value


def normalize_for_compare(value):
    """
    Canonical form used by row-level validation, so values read back from
    different engines compare equal when they represent the same data.
    MongoDB stores dates with millisecond precision, so timestamps are
    compared at millisecond precision everywhere.
    """
    if value is None:
        return None

    # bson.Decimal128 without importing bson here
    if hasattr(value, "to_decimal"):
        value = value.to_decimal()

    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value)).normalize()
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
    if isinstance(value, dt.date):
        return value
    return str(value)
