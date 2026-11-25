"""
S3 landing zone (raw layer of the data lake).

Every full-load batch for the lakehouse is written once as Parquet to
s3://<bucket>/raw/run=<run_id>/<table>/<file>. The same bytes are then loaded
into Databricks. On real AWS, Databricks would read the files straight from
S3 (external location); locally Databricks cannot reach the laptop, so the
file is also uploaded to a Unity Catalog volume.
"""

import io

import pyarrow as pa
import pyarrow.parquet as pq

from app import aws
from app.migration.schema import get_columns
from app.migration.type_mapping import arrow_schema


def rows_to_parquet(table: str, column_names: list[str], rows: list[tuple]) -> bytes:
    columns = get_columns(table)
    by_name = {c.name: c for c in columns}
    ordered = [by_name[name] for name in column_names]
    schema = arrow_schema(ordered)

    arrays = [
        pa.array([row[i] for row in rows], type=schema.field(i).type)
        for i in range(len(ordered))
    ]
    arrow_table = pa.Table.from_arrays(arrays, schema=schema)

    buffer = io.BytesIO()
    pq.write_table(arrow_table, buffer, compression="snappy")
    return buffer.getvalue()


def landing_key(run_id: int, table: str, file_name: str) -> str:
    return f"raw/run={run_id}/{table}/{file_name}"


def put_landing_file(run_id: int, table: str, file_name: str, data: bytes) -> str:
    key = landing_key(run_id, table, file_name)
    aws.client("s3").put_object(
        Bucket=aws.LANDING_BUCKET,
        Key=key,
        Body=data,
        ContentType="application/vnd.apache.parquet",
    )
    return f"s3://{aws.LANDING_BUCKET}/{key}"


def landing_stats(run_id: int | None) -> dict:
    """Object count and size of a run's landing zone (for the dashboard)."""
    prefix = f"raw/run={run_id}/" if run_id else "raw/"
    s3 = aws.client("s3")

    files = 0
    size = 0
    tables: dict[str, int] = {}

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=aws.LANDING_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            files += 1
            size += obj["Size"]
            parts = obj["Key"].split("/")
            if len(parts) >= 3:
                tables[parts[2]] = tables.get(parts[2], 0) + 1

    return {
        "bucket": aws.LANDING_BUCKET,
        "prefix": prefix,
        "files": files,
        "bytes": size,
        "files_per_table": tables,
    }
