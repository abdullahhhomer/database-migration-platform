import os

from databricks import sql

from app.migration.reader import get_db_connection


TABLES = [
    "customers",
    "products",
    "orders",
    "order_items",
    "payments",
    "shipments",
    "returns",
]


RELATIONSHIPS = [
    {
        "name": "orders.customer_id -> customers.id",
        "source_table": "orders",
        "source_column": "customer_id",
        "target_table": "customers",
        "target_column": "id",
    },
    {
        "name": "order_items.order_id -> orders.id",
        "source_table": "order_items",
        "source_column": "order_id",
        "target_table": "orders",
        "target_column": "id",
    },
    {
        "name": "order_items.product_id -> products.id",
        "source_table": "order_items",
        "source_column": "product_id",
        "target_table": "products",
        "target_column": "id",
    },
    {
        "name": "payments.order_id -> orders.id",
        "source_table": "payments",
        "source_column": "order_id",
        "target_table": "orders",
        "target_column": "id",
    },
    {
        "name": "shipments.order_id -> orders.id",
        "source_table": "shipments",
        "source_column": "order_id",
        "target_table": "orders",
        "target_column": "id",
    },
    {
        "name": "returns.order_item_id -> order_items.id",
        "source_table": "returns",
        "source_column": "order_item_id",
        "target_table": "order_items",
        "target_column": "id",
    },
]


def get_databricks_connection():
    return sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )


def get_source_count(table_name: str) -> int:
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            )
            return cursor.fetchone()[0]
    finally:
        connection.close()


def get_target_count(table_name: str) -> int:
    connection = get_databricks_connection()

    try:
        catalog = os.getenv(
            "DATABRICKS_CATALOG",
            "migration_platform",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM `{catalog}`.`bronze`.`{table_name}`
                """
            )

            return cursor.fetchone()[0]

    finally:
        connection.close()


def get_source_orphans(
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
) -> int:
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM "{source_table}" s
                LEFT JOIN "{target_table}" t
                    ON s."{source_column}" = t."{target_column}"
                WHERE t."{target_column}" IS NULL
                """
            )

            return cursor.fetchone()[0]

    finally:
        connection.close()


def get_target_orphans(
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
) -> int:
    connection = get_databricks_connection()

    try:
        catalog = os.getenv(
            "DATABRICKS_CATALOG",
            "migration_platform",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM `{catalog}`.`bronze`.`{source_table}` s
                LEFT JOIN `{catalog}`.`bronze`.`{target_table}` t
                    ON s.`{source_column}` = t.`{target_column}`
                WHERE t.`{target_column}` IS NULL
                """
            )

            return cursor.fetchone()[0]

    finally:
        connection.close()


def create_validation_run() -> int:
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO validation_runs (
                    status,
                    total_checks,
                    passed_checks,
                    failed_checks
                )
                VALUES ('running', 0, 0, 0)
                RETURNING id
                """
            )

            run_id = cursor.fetchone()[0]

        connection.commit()

        return run_id

    finally:
        connection.close()


def save_validation_result(
    run_id: int,
    check_type: str,
    check_name: str,
    table_name: str | None,
    source_count: int,
    target_count: int,
    difference: int,
    status: str,
):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO validation_results (
                    run_id,
                    check_type,
                    check_name,
                    table_name,
                    source_count,
                    target_count,
                    count_difference,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    run_id,
                    check_type,
                    check_name,
                    table_name,
                    source_count,
                    target_count,
                    difference,
                    status,
                ),
            )

        connection.commit()

    finally:
        connection.close()


def complete_validation_run(
    run_id: int,
    total_checks: int,
    passed_checks: int,
    failed_checks: int,
):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            status = "passed" if failed_checks == 0 else "failed"

            cursor.execute(
                """
                UPDATE validation_runs
                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = %s,
                    total_checks = %s,
                    passed_checks = %s,
                    failed_checks = %s
                WHERE id = %s
                """,
                (
                    status,
                    total_checks,
                    passed_checks,
                    failed_checks,
                    run_id,
                ),
            )

        connection.commit()

    finally:
        connection.close()


def validate_counts():
    run_id = create_validation_run()

    results = []
    passed_checks = 0
    failed_checks = 0

    try:
        # -----------------------------
        # Table count validation
        # -----------------------------
        for table_name in TABLES:
            source_count = get_source_count(table_name)
            target_count = get_target_count(table_name)

            difference = source_count - target_count
            status = "passed" if difference == 0 else "failed"

            if status == "passed":
                passed_checks += 1
            else:
                failed_checks += 1

            save_validation_result(
                run_id=run_id,
                check_type="count",
                check_name=f"{table_name} row count",
                table_name=table_name,
                source_count=source_count,
                target_count=target_count,
                difference=difference,
                status=status,
            )

            results.append(
                {
                    "check_type": "count",
                    "check_name": f"{table_name} row count",
                    "table_name": table_name,
                    "source_count": source_count,
                    "target_count": target_count,
                    "count_difference": difference,
                    "status": status,
                }
            )

        # -----------------------------
        # Referential integrity
        # -----------------------------
        for relationship in RELATIONSHIPS:
            source_orphans = get_source_orphans(
                source_table=relationship["source_table"],
                source_column=relationship["source_column"],
                target_table=relationship["target_table"],
                target_column=relationship["target_column"],
            )

            target_orphans = get_target_orphans(
                source_table=relationship["source_table"],
                source_column=relationship["source_column"],
                target_table=relationship["target_table"],
                target_column=relationship["target_column"],
            )

            difference = target_orphans - source_orphans

            status = (
                "passed"
                if source_orphans == 0 and target_orphans == 0
                else "failed"
            )

            if status == "passed":
                passed_checks += 1
            else:
                failed_checks += 1

            save_validation_result(
                run_id=run_id,
                check_type="referential_integrity",
                check_name=relationship["name"],
                table_name=relationship["source_table"],
                source_count=source_orphans,
                target_count=target_orphans,
                difference=difference,
                status=status,
            )

            results.append(
                {
                    "check_type": "referential_integrity",
                    "check_name": relationship["name"],
                    "source_table": relationship["source_table"],
                    "source_orphans": source_orphans,
                    "target_orphans": target_orphans,
                    "count_difference": difference,
                    "status": status,
                }
            )

        total_checks = passed_checks + failed_checks

        complete_validation_run(
            run_id=run_id,
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
        )

        return {
            "run_id": run_id,
            "status": "passed" if failed_checks == 0 else "failed",
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "results": results,
        }

    except Exception:
        total_checks = passed_checks + failed_checks

        complete_validation_run(
            run_id=run_id,
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
        )

        raise


def get_validation_history():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    started_at,
                    completed_at,
                    status,
                    total_checks,
                    passed_checks,
                    failed_checks
                FROM validation_runs
                ORDER BY id DESC
                """
            )

            rows = cursor.fetchall()

            return [
                {
                    "run_id": row[0],
                    "started_at": row[1],
                    "completed_at": row[2],
                    "status": row[3],
                    "total_checks": row[4],
                    "passed_checks": row[5],
                    "failed_checks": row[6],
                }
                for row in rows
            ]

    finally:
        connection.close()


def get_validation_run(run_id: int):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    started_at,
                    completed_at,
                    status,
                    total_checks,
                    passed_checks,
                    failed_checks
                FROM validation_runs
                WHERE id = %s
                """,
                (run_id,),
            )

            run = cursor.fetchone()

            if not run:
                return None

            cursor.execute(
                """
                SELECT
                    check_type,
                    check_name,
                    table_name,
                    source_count,
                    target_count,
                    count_difference,
                    status,
                    checked_at
                FROM validation_results
                WHERE run_id = %s
                ORDER BY id
                """,
                (run_id,),
            )

            results = cursor.fetchall()

            return {
                "run_id": run[0],
                "started_at": run[1],
                "completed_at": run[2],
                "status": run[3],
                "total_checks": run[4],
                "passed_checks": run[5],
                "failed_checks": run[6],
                "results": [
                    {
                        "check_type": row[0],
                        "check_name": row[1],
                        "table_name": row[2],
                        "source_count": row[3],
                        "target_count": row[4],
                        "count_difference": row[5],
                        "status": row[6],
                        "checked_at": row[7],
                    }
                    for row in results
                ],
            }

    finally:
        connection.close()