"""
CDC producer: PostgreSQL logical replication (wal2json) -> Amazon Kinesis.

  * Creates the logical replication slot `migration_cdc_slot` (wal2json).
    From that moment Postgres retains every change for us, even while this
    worker is down.
  * Streams row changes for the business tables and publishes each one as a
    JSON record to Kinesis. Partition key = "<table>:<pk>", so all changes
    to one row land on the same shard, in commit order.
  * Acknowledges a WAL position back to Postgres only after Kinesis accepted
    the records (at-least-once delivery; the appliers are idempotent).
  * Rows inserted into cdc_heartbeat are fanned out to EVERY shard; the
    cutover runbook uses them as a watermark to prove the stream is drained.
"""

import json
import logging
import os
import select
import time

import boto3
import psycopg2
from botocore.config import Config
from psycopg2.extras import LogicalReplicationConnection


SLOT = os.getenv("CDC_SLOT", "migration_cdc_slot")
STREAM = os.getenv("KINESIS_STREAM", "cdc-changes")
SHARDS = int(os.getenv("KINESIS_SHARDS", "2"))

TABLES = ["customers", "products", "orders", "order_items", "payments", "shipments", "returns"]
HEARTBEAT_TABLE = "cdc_heartbeat"

# Postgres 17.x only allows allow-listed logical decoding plugins.
PLUGIN_OPTION = "-c output_plugin_libraries=pgoutput,test_decoding,wal2json"

FLUSH_RECORDS = 500         # Kinesis PutRecords limit per call
FLUSH_SECONDS = 0.2         # max time a change waits in the local buffer
FEEDBACK_SECONDS = 5        # keepalive / ack interval towards Postgres
STATS_SECONDS = 2           # dashboard stats interval

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "migration_source"),
    "user": os.getenv("POSTGRES_USER", "migration_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "migration_password"),
}

WAL2JSON_OPTIONS = {
    "format-version": "2",
    "include-timestamp": "1",
    "include-pk": "1",
    # Numbers as text: no float rounding of NUMERIC(12,2) money values.
    "numeric-data-types-as-string": "1",
    "add-tables": ",".join(f"public.{t}" for t in [*TABLES, HEARTBEAT_TABLE]),
}

PRODUCER_DDL = """
CREATE TABLE IF NOT EXISTS cdc_status (
    target VARCHAR(30) PRIMARY KEY,
    last_applied_lsn PG_LSN,
    events_applied BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS state VARCHAR(40);
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS events_published BIGINT NOT NULL DEFAULT 0;
ALTER TABLE cdc_status ADD COLUMN IF NOT EXISTS message TEXT;
CREATE TABLE IF NOT EXISTS cdc_heartbeat (
    id BIGSERIAL PRIMARY KEY,
    token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

log = logging.getLogger("cdc.producer")


def lsn_str(lsn: int) -> str:
    return f"{lsn >> 32:X}/{lsn & 0xFFFFFFFF:X}"


class Producer:
    def __init__(self):
        self.kinesis = boto3.client(
            "kinesis",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            endpoint_url=os.getenv("AWS_ENDPOINT_URL") or None,
            config=Config(retries={"max_attempts": 10, "mode": "standard"}),
        )
        self.shard_hash_keys: list[str] = []
        self.buffer: list[dict] = []
        self.buffer_since: float | None = None
        self.pending_lsn: int | None = None   # last WAL position consumed
        self.acked_lsn: int | None = None     # last WAL position confirmed to Postgres
        self.events_published = 0
        self.last_published_lsn: str | None = None
        self._candidate_lsn: str | None = None
        self.stats_connection = None
        self.last_stats = 0.0

    # --- setup -------------------------------------------------------------
    def ensure_stream(self) -> None:
        try:
            self.kinesis.describe_stream_summary(StreamName=STREAM)
        except self.kinesis.exceptions.ResourceNotFoundException:
            log.info("Creating Kinesis stream %s (%d shards)", STREAM, SHARDS)
            self.kinesis.create_stream(StreamName=STREAM, ShardCount=SHARDS)
            self.kinesis.get_waiter("stream_exists").wait(StreamName=STREAM)

        shards = self.kinesis.list_shards(StreamName=STREAM)["Shards"]
        self.shard_hash_keys = [s["HashKeyRange"]["StartingHashKey"] for s in shards]
        log.info("Kinesis stream %s ready (%d shards)", STREAM, len(shards))

    def ensure_slot(self) -> None:
        connection = psycopg2.connect(**DB_CONFIG, options=PLUGIN_OPTION)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(74210)")
                cursor.execute(PRODUCER_DDL)
                cursor.execute("SELECT pg_advisory_unlock(74210)")

                cursor.execute(
                    "SELECT plugin FROM pg_replication_slots WHERE slot_name = %s", (SLOT,)
                )
                row = cursor.fetchone()
                if row and row[0] != "wal2json":
                    log.warning("Slot %s uses %s; recreating it with wal2json", SLOT, row[0])
                    cursor.execute("SELECT pg_drop_replication_slot(%s)", (SLOT,))
                    row = None
                if not row:
                    cursor.execute(
                        "SELECT lsn FROM pg_create_logical_replication_slot(%s, 'wal2json')", (SLOT,)
                    )
                    log.info("Created replication slot %s at %s", SLOT, cursor.fetchone()[0])
                else:
                    log.info("Using existing replication slot %s", SLOT)

                cursor.execute(
                    "SELECT events_published FROM cdc_status WHERE target = 'producer'"
                )
                row = cursor.fetchone()
                self.events_published = row[0] if row else 0
        finally:
            connection.close()

    # --- stats ---------------------------------------------------------------
    def write_stats(self, state: str, message: str | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_stats < STATS_SECONDS:
            return
        self.last_stats = now
        try:
            if self.stats_connection is None or self.stats_connection.closed:
                self.stats_connection = psycopg2.connect(**DB_CONFIG)
                self.stats_connection.autocommit = True
            with self.stats_connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cdc_status (target, state, events_published, last_applied_lsn, message, updated_at)
                    VALUES ('producer', %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (target) DO UPDATE SET
                        state = EXCLUDED.state,
                        events_published = EXCLUDED.events_published,
                        last_applied_lsn = COALESCE(EXCLUDED.last_applied_lsn, cdc_status.last_applied_lsn),
                        message = EXCLUDED.message,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (state, self.events_published, self.last_published_lsn, message),
                )
        except Exception as error:
            log.warning("Could not write producer stats: %s", error)
            self.stats_connection = None

    # --- change handling -----------------------------------------------------
    def to_records(self, change: dict, lsn: str) -> list[dict]:
        action = change.get("action")
        table = change.get("table")
        if action not in ("I", "U", "D"):
            return []   # B/C (transaction boundaries), T (truncate), M (messages)

        if table == HEARTBEAT_TABLE:
            if action != "I":
                return []
            token = next(c["value"] for c in change["columns"] if c["name"] == "token")
            data = json.dumps({"type": "heartbeat", "token": token, "lsn": lsn})
            return [
                {"Data": data.encode(), "PartitionKey": "heartbeat", "ExplicitHashKey": key}
                for key in self.shard_hash_keys
            ]

        if table not in TABLES:
            return []

        columns = change.get("identity", []) if action == "D" else change.get("columns", [])
        row = {c["name"]: c["value"] for c in columns}
        pk = int(row["id"])

        event = {
            "lsn": lsn,
            "table": table,
            "op": action,
            "pk": pk,
            "row": row if action != "D" else {},
            "types": {c["name"]: c["type"] for c in columns} if action != "D" else {},
            "commit_ts": change.get("timestamp"),
        }
        return [{
            "Data": json.dumps(event, separators=(",", ":")).encode(),
            "PartitionKey": f"{table}:{pk}",
        }]

    def flush(self) -> None:
        records = self.buffer
        while records:
            chunk = records[:FLUSH_RECORDS]
            response = self.kinesis.put_records(StreamName=STREAM, Records=chunk)
            if response.get("FailedRecordCount"):
                # Resend from the first failed record onwards. Re-sending a few
                # records that did succeed keeps per-key order; duplicates are
                # harmless because the appliers are idempotent.
                first_failed = next(
                    i for i, r in enumerate(response["Records"]) if "ErrorCode" in r
                )
                records = records[first_failed:]
                time.sleep(0.5)
                continue
            records = records[FLUSH_RECORDS:]

        self.events_published += len(self.buffer)
        if self._candidate_lsn:
            self.last_published_lsn = self._candidate_lsn
        self.buffer = []
        self.buffer_since = None

    def acknowledge(self, cursor) -> None:
        if self.pending_lsn is not None and self.pending_lsn != self.acked_lsn:
            cursor.send_feedback(flush_lsn=self.pending_lsn)
            self.acked_lsn = self.pending_lsn

    # --- main loop -------------------------------------------------------------
    def stream(self) -> None:
        self.ensure_stream()
        self.ensure_slot()
        self.buffer, self.buffer_since, self.pending_lsn = [], None, None

        connection = psycopg2.connect(
            **DB_CONFIG,
            connection_factory=LogicalReplicationConnection,
            options=PLUGIN_OPTION,
        )
        cursor = connection.cursor()
        cursor.start_replication(slot_name=SLOT, decode=True, options=WAL2JSON_OPTIONS)
        log.info("Streaming changes for %s", ", ".join(TABLES))
        self.write_stats("streaming", force=True)

        last_feedback = time.monotonic()

        try:
            while True:
                message = cursor.read_message()
                if message is not None:
                    lsn = lsn_str(message.data_start)
                    records = self.to_records(json.loads(message.payload), lsn)
                    if records:
                        self.buffer.extend(records)
                        self.buffer_since = self.buffer_since or time.monotonic()
                        self._candidate_lsn = lsn
                    self.pending_lsn = message.data_start

                    if len(self.buffer) >= FLUSH_RECORDS:
                        self.flush()
                        self.acknowledge(cursor)
                    continue

                now = time.monotonic()
                if self.buffer and now - self.buffer_since >= FLUSH_SECONDS:
                    self.flush()
                    self.acknowledge(cursor)
                elif not self.buffer:
                    self.acknowledge(cursor)

                if now - last_feedback >= FEEDBACK_SECONDS:
                    cursor.send_feedback()
                    last_feedback = now

                self.write_stats("streaming")
                select.select([cursor], [], [], FLUSH_SECONDS)
        finally:
            connection.close()

    def run_forever(self) -> None:
        while True:
            try:
                self.stream()
            except KeyboardInterrupt:
                log.info("CDC producer stopped.")
                return
            except Exception as error:
                log.exception("CDC producer error, reconnecting in 5s")
                self.write_stats("error", message=f"{type(error).__name__}: {error}"[:500], force=True)
                time.sleep(5)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [cdc-producer] %(message)s",
    )
    Producer().run_forever()


if __name__ == "__main__":
    main()
