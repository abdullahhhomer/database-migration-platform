"""
Legacy single-table Databricks helpers, used by the original
/api/migration/tables/{table}/create and /migrate-batch endpoints.

They now delegate to DatabricksTarget so type mapping (exact DECIMAL(p,s),
TIMESTAMP_NTZ, ...) and SQL escaping live in one place.
"""

from app.targets.databricks import DatabricksTarget


def get_table_name(table_name: str) -> str:
    return DatabricksTarget().fq(table_name)


def create_table(table_name: str, columns: list[dict] | None = None):
    """Creates the bronze table from the source schema (`columns` is ignored)."""
    target = DatabricksTarget()
    try:
        target.execute(target._table_ddl(table_name, replace=False))
    finally:
        target.close()


def insert_rows(table_name: str, columns: list[str], rows: list[list]):
    if not rows:
        return
    target = DatabricksTarget()
    try:
        target._insert_values(table_name, columns, [tuple(r) for r in rows])
    finally:
        target.close()
