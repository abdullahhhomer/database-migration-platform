import os

import psycopg2


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "migration_source"),
        user=os.getenv("POSTGRES_USER", "migration_user"),
        password=os.getenv("POSTGRES_PASSWORD", "migration_password"),
    )


def read_table_batch(
    table_name: str,
    last_id: int = 0,
    batch_size: int = 1000,
):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f'''
                SELECT *
                FROM "{table_name}"
                WHERE id > %s
                ORDER BY id
                LIMIT %s
                ''',
                (last_id, batch_size),
            )

            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()

        next_last_id = rows[-1][0] if rows else last_id

        return {
            "columns": columns,
            "rows": rows,
            "count": len(rows),
            "last_id": last_id,
            "next_last_id": next_last_id,
            "batch_size": batch_size,
        }

    finally:
        connection.close()