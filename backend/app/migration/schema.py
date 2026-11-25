"""Source schema introspection (PostgreSQL information_schema)."""

import threading
from dataclasses import dataclass

from app.migration.reader import get_db_connection


# Business tables in dependency order (parents before children).
BUSINESS_TABLES = [
    "customers",
    "products",
    "orders",
    "order_items",
    "payments",
    "shipments",
    "returns",
]

# Foreign keys, used for referential-integrity checks and for the
# constraints added on SQL Server at cutover.
RELATIONSHIPS = [
    ("orders", "customer_id", "customers", "id"),
    ("order_items", "order_id", "orders", "id"),
    ("order_items", "product_id", "products", "id"),
    ("payments", "order_id", "orders", "id"),
    ("shipments", "order_id", "orders", "id"),
    ("returns", "order_item_id", "order_items", "id"),
]

# Money columns summed by the checksum validation.
MONEY_COLUMNS = {
    "products": "price",
    "orders": "total_amount",
    "order_items": "unit_price",
    "payments": "amount",
}


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str          # information_schema data_type, e.g. 'numeric'
    precision: int | None
    scale: int | None
    max_length: int | None
    nullable: bool


_cache: dict[str, list[Column]] = {}
_lock = threading.Lock()


def get_columns(table: str) -> list[Column]:
    with _lock:
        if table in _cache:
            return _cache[table]

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    column_name,
                    data_type,
                    numeric_precision,
                    numeric_scale,
                    character_maximum_length,
                    is_nullable = 'YES'
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table,),
            )
            columns = [Column(*row) for row in cursor.fetchall()]
    finally:
        connection.close()

    if not columns:
        raise ValueError(f"Source table '{table}' does not exist")

    with _lock:
        _cache[table] = columns

    return columns


def column_names(table: str) -> list[str]:
    return [c.name for c in get_columns(table)]


def source_count(table: str) -> int:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            return cursor.fetchone()[0]
    finally:
        connection.close()
