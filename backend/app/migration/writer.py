import os

from databricks import sql


def get_databricks_connection():
    return sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )


def get_table_name(table_name: str) -> str:
    catalog = os.getenv("DATABRICKS_CATALOG", "migration_platform")
    schema = os.getenv("DATABRICKS_SCHEMA", "bronze")

    return f"`{catalog}`.`{schema}`.`{table_name}`"


def create_table(table_name: str, columns: list[dict]):
    connection = get_databricks_connection()

    try:
        column_definitions = []

        for column in columns:
            name = column["name"]
            data_type = column["data_type"]

            if data_type == "bigint":
                databricks_type = "BIGINT"
            elif data_type == "integer":
                databricks_type = "INT"
            elif data_type in ("numeric", "decimal"):
                databricks_type = "DECIMAL(18,2)"
            elif data_type in (
                "timestamp without time zone",
                "timestamp with time zone",
            ):
                databricks_type = "TIMESTAMP"
            elif data_type == "boolean":
                databricks_type = "BOOLEAN"
            else:
                databricks_type = "STRING"

            column_definitions.append(
                f"`{name}` {databricks_type}"
            )

        full_table_name = get_table_name(table_name)

        query = f"""
            CREATE TABLE IF NOT EXISTS {full_table_name} (
                {", ".join(column_definitions)}
            )
            USING DELTA
        """

        with connection.cursor() as cursor:
            cursor.execute(query)

    finally:
        connection.close()



def insert_rows(table_name: str, columns: list[str], rows: list[list]):
    if not rows:
        return

    connection = get_databricks_connection()

    try:
        full_table_name = get_table_name(table_name)
        column_names = ", ".join(f"`{column}`" for column in columns)

        value_rows = []

        for row in rows:
            values = []

            for value in row:
                if value is None:
                    values.append("NULL")
                elif isinstance(value, bool):
                    values.append("TRUE" if value else "FALSE")
                elif isinstance(value, (int, float)):
                    values.append(str(value))
                else:
                    escaped_value = str(value).replace("'", "''")
                    values.append(f"'{escaped_value}'")

            value_rows.append(f"({', '.join(values)})")

        query = f"""
            INSERT INTO {full_table_name}
            ({column_names})
            VALUES
            {", ".join(value_rows)}
        """

        with connection.cursor() as cursor:
            cursor.execute(query)

    finally:
        connection.close()