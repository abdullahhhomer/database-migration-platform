from app.validation.validator import get_db_connection


def get_migration_readiness():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    total_checks,
                    passed_checks,
                    failed_checks,
                    completed_at
                FROM validation_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )

            run = cursor.fetchone()

            if not run:
                return {
                    "status": "not_ready",
                    "reason": "No validation run exists",
                    "checks": [],
                }

            run_id = run[0]
            validation_status = run[1]
            total_checks = run[2]
            passed_checks = run[3]
            failed_checks = run[4]
            completed_at = run[5]

            cursor.execute(
                """
                SELECT
                    table_name,
                    source_count,
                    target_count,
                    count_difference,
                    status
                FROM validation_results
                WHERE run_id = %s
                ORDER BY id
                """,
                (run_id,),
            )

            results = cursor.fetchall()

            checks = []

            for row in results:
                checks.append(
                    {
                        "table_name": row[0],
                        "source_count": row[1],
                        "target_count": row[2],
                        "count_difference": row[3],
                        "status": row[4],
                    }
                )

            ready = (
                validation_status == "passed"
                and failed_checks == 0
                and total_checks > 0
            )

            return {
                "status": "ready" if ready else "not_ready",
                "validation_run_id": run_id,
                "validation_status": validation_status,
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "completed_at": completed_at,
                "checks": checks,
            }

    finally:
        connection.close()