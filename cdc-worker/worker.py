import json
import os
import time

import psycopg2
from psycopg2.extras import LogicalReplicationConnection


DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "migration_source"),
    "user": os.getenv("POSTGRES_USER", "migration_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "migration_password"),
}


def parse_change(payload):
    """
    PostgreSQL pgoutput produces a binary protocol, so this initial
    worker uses test_decoding instead for a simple readable CDC stream.
    """
    return payload


def consume_changes():
    connection = psycopg2.connect(
        connection_factory=LogicalReplicationConnection,
        **DB_CONFIG,
    )

    cursor = connection.cursor()

    slot_name = "migration_cdc_slot"

    try:
        cursor.create_replication_slot(
            slot_name,
            output_plugin="test_decoding",
        )
        print(f"Created replication slot: {slot_name}", flush=True)
    except psycopg2.errors.DuplicateObject:
        connection.rollback()
        print(f"Using existing replication slot: {slot_name}", flush=True)

    options = {
        "include-xids": "0",
        "skip-empty-xacts": "1",
    }

    def consume(message):
        change = {
            "lsn": str(message.data_start),
            "payload": parse_change(message.payload),
        }

        print(json.dumps(change), flush=True)

        message.cursor.send_feedback(
            flush_lsn=message.data_start
        )

    print("Starting CDC worker...", flush=True)

    cursor.start_replication(
        slot_name=slot_name,
        options=options,
        decode=True,
    )

    cursor.consume_stream(consume)

def main():
    while True:
        try:
            consume_changes()
        except KeyboardInterrupt:
            print("CDC worker stopped.", flush=True)
            break
        except Exception as error:
            print(f"CDC error: {error}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()