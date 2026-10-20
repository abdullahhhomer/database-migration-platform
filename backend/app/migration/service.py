import psycopg2

from app.migration.reader import get_db_connection, read_table_batch
from app.migration.writer import insert_rows


def get_or_create_job(table_name: str, batch_size: int):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    batch_size,
                    total_rows,
                    migrated_rows,
                    last_id
                FROM migration_jobs
                WHERE table_name = %s
                  AND status IN ('pending', 'running')
                ORDER BY id DESC
                LIMIT 1
                """,
                (table_name,),
            )

            job = cursor.fetchone()

            if job:
                connection.commit()
                return {
                    "id": job[0],
                    "status": job[1],
                    "batch_size": job[2],
                    "total_rows": job[3],
                    "migrated_rows": job[4],
                    "last_id": job[5],
                }

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s
                """,
                (table_name,),
            )

            if cursor.fetchone()[0] == 0:
                raise ValueError(
                    f"Source table '{table_name}' does not exist"
                )

            cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            )
            total_rows = cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO migration_jobs (
                    table_name,
                    status,
                    batch_size,
                    total_rows,
                    migrated_rows,
                    last_id,
                    started_at
                )
                VALUES (%s, 'running', %s, %s, 0, 0, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                (table_name, batch_size, total_rows),
            )

            job_id = cursor.fetchone()[0]
            connection.commit()

            return {
                "id": job_id,
                "status": "running",
                "batch_size": batch_size,
                "total_rows": total_rows,
                "migrated_rows": 0,
                "last_id": 0,
            }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def update_job(
    job_id: int,
    last_id: int,
    migrated_rows: int,
):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE migration_jobs
                SET
                    last_id = %s,
                    migrated_rows = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (last_id, migrated_rows, job_id),
            )

        connection.commit()

    finally:
        connection.close()


def complete_job(job_id: int):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE migration_jobs
                SET
                    status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (job_id,),
            )

        connection.commit()

    finally:
        connection.close()


def fail_job(job_id: int, error_message: str):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE migration_jobs
                SET
                    status = 'failed',
                    error_message = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (error_message, job_id),
            )

        connection.commit()

    finally:
        connection.close()


def migrate_table(
    table_name: str,
    batch_size: int = 1000,
):
    job = get_or_create_job(
        table_name=table_name,
        batch_size=batch_size,
    )

    job_id = job["id"]
    last_id = job["last_id"]
    total_migrated = job["migrated_rows"]

    try:
        while True:
            batch = read_table_batch(
                table_name=table_name,
                last_id=last_id,
                batch_size=batch_size,
            )

            if batch["count"] == 0:
                complete_job(job_id)

                return {
                    "status": "completed",
                    "job_id": job_id,
                    "table": table_name,
                    "total_rows": job["total_rows"],
                    "migrated_rows": total_migrated,
                    "last_id": last_id,
                }

            insert_rows(
                table_name=table_name,
                columns=batch["columns"],
                rows=batch["rows"],
            )

            total_migrated += batch["count"]
            last_id = batch["next_last_id"]

            update_job(
                job_id=job_id,
                last_id=last_id,
                migrated_rows=total_migrated,
            )

    except Exception as error:
        fail_job(
            job_id=job_id,
            error_message=str(error),
        )
        raise