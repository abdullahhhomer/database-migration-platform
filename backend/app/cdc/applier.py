"""
CDC applier: Kinesis -> one target. Runs as its own process per target:

    python -m app.cdc.applier --target databricks|sqlserver|mongodb

Behaviour (same as AWS DMS "full-load-and-cdc"):
  * while the target's full load is running, changes accumulate in Kinesis;
  * once it finishes, the applier replays the stream from the run start
    (minus a safety margin) as idempotent upserts/deletes, in micro-batches;
  * checkpoints (Kinesis sequence numbers) are stored in DynamoDB, like the
    Kinesis Client Library does, so a restarted applier resumes exactly;
  * progress and lag are written to the cdc_status table for the dashboard.
"""

import argparse
import datetime as dt
import json
import logging
import os
import time

from app import aws
from app.cdc.events import build_changes, lsn_to_int
from app.config import databricks_configured
from app.control import (
    ensure_control_schema,
    fetch_one_dict,
    latest_run,
    run_targets,
    target_full_load_done,
    upsert_cdc_status,
)
from app.migration.reader import get_db_connection
from app.migration.schema import BUSINESS_TABLES
from app.targets import get_target


log = logging.getLogger("cdc.applier")

DEFAULT_BATCH_SECONDS = {"databricks": 10.0, "sqlserver": 2.0, "mongodb": 2.0}
MAX_BATCH_EVENTS = int(os.getenv("CDC_MAX_BATCH_EVENTS", "5000"))
REPLAY_MARGIN_SECONDS = int(os.getenv("CDC_REPLAY_MARGIN_SECONDS", "60"))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Applier:
    def __init__(self, target_name: str):
        self.name = target_name
        self.batch_seconds = float(
            os.getenv(
                f"CDC_BATCH_SECONDS_{target_name.upper()}",
                DEFAULT_BATCH_SECONDS.get(target_name, 2.0),
            )
        )
        self.kinesis = aws.client("kinesis")
        self.dynamodb = aws.client("dynamodb")
        self.target = None

        self.run_id: int | None = None
        self.run_started: dt.datetime | None = None
        self.shards: list[str] = []
        self.iterators: dict[str, str] = {}
        self.checkpoints: dict[str, str] = {}
        self.heartbeats: dict[str, str] = {}

        self.events_seen = 0
        self.events_applied = 0
        self.last_lsn: str | None = None
        self.last_heartbeat: str | None = None

    # --- status ----------------------------------------------------------
    def status(self, **fields) -> None:
        try:
            upsert_cdc_status(self.name, **fields)
        except Exception:
            log.exception("Could not write cdc_status")

    # --- main loop -------------------------------------------------------
    def run_forever(self) -> None:
        ensure_control_schema()
        log.info("CDC applier for '%s' started (micro-batch %.1fs)", self.name, self.batch_seconds)

        while True:
            try:
                self.tick()
            except Exception as error:
                log.exception("Applier error")
                self.status(state="error", message=f"{type(error).__name__}: {error}"[:500])
                if self.target is not None:
                    self.target.close()
                    self.target = None
                self.iterators = {}
                time.sleep(5)

    def tick(self) -> None:
        run = latest_run()

        if not run or self.name not in run_targets(run):
            self.run_id = None
            self.status(
                state="idle", run_id=run["id"] if run else None,
                message="Not part of the current migration run",
            )
            time.sleep(3)
            return

        if self.name == "databricks" and not databricks_configured():
            self.status(state="not_configured", run_id=run["id"], message="Databricks credentials missing")
            time.sleep(10)
            return

        if run["status"] in ("preparing", "cancelled") or not target_full_load_done(run["id"], self.name):
            self.run_id = None
            self.status(
                state="waiting_for_full_load",
                run_id=run["id"],
                seconds_behind=(_now() - run["started_at"]).total_seconds(),
                events_applied=0,
                events_seen=0,
                message="Changes are buffered in Kinesis until this target's full load finishes",
            )
            time.sleep(3)
            return

        if self.run_id != run["id"]:
            self.start_replay(run)

        self.poll_and_apply()

    # --- stream positioning ------------------------------------------------
    def start_replay(self, run: dict) -> None:
        self.run_id = run["id"]
        self.run_started = run["started_at"]
        self.shards = [
            s["ShardId"] for s in self.kinesis.list_shards(StreamName=aws.CDC_STREAM)["Shards"]
        ]
        self.checkpoints = self.load_checkpoints()
        self.iterators = {shard: self.new_iterator(shard) for shard in self.shards}
        self.heartbeats = {}

        # Restore counters if this process restarted in the middle of a run.
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM cdc_status WHERE target = %s", (self.name,))
                row = fetch_one_dict(cursor) or {}
        finally:
            connection.close()

        same_run = row.get("run_id") == self.run_id and self.checkpoints
        self.events_seen = row.get("events_seen", 0) if same_run else 0
        self.events_applied = row.get("events_applied", 0) if same_run else 0
        self.last_heartbeat = row.get("last_heartbeat") if same_run else None

        if self.target is None:
            self.target = get_target(self.name)

        log.info(
            "Replaying run %s on %d shard(s) (%s)",
            self.run_id, len(self.shards),
            "from checkpoints" if self.checkpoints else "from run start",
        )
        self.status(
            state="catching_up", run_id=self.run_id,
            events_seen=self.events_seen, events_applied=self.events_applied,
            last_heartbeat=self.last_heartbeat, message=None,
        )

    def load_checkpoints(self) -> dict[str, str]:
        checkpoints = {}
        for shard in self.shards:
            item = self.dynamodb.get_item(
                TableName=aws.CHECKPOINT_TABLE,
                Key={"consumer": {"S": self.name}, "shard_id": {"S": shard}},
            ).get("Item")
            if item and int(item["run_id"]["N"]) == self.run_id:
                checkpoints[shard] = item["sequence_number"]["S"]
        return checkpoints

    def new_iterator(self, shard: str) -> str:
        if shard in self.checkpoints:
            return self.kinesis.get_shard_iterator(
                StreamName=aws.CDC_STREAM, ShardId=shard,
                ShardIteratorType="AFTER_SEQUENCE_NUMBER",
                StartingSequenceNumber=self.checkpoints[shard],
            )["ShardIterator"]

        # Everything committed after the run started must be replayed; the
        # margin covers transactions in flight at that moment. Replaying a
        # change that the full load already copied is harmless (idempotent).
        start = self.run_started - dt.timedelta(seconds=REPLAY_MARGIN_SECONDS)
        return self.kinesis.get_shard_iterator(
            StreamName=aws.CDC_STREAM, ShardId=shard,
            ShardIteratorType="AT_TIMESTAMP", Timestamp=start,
        )["ShardIterator"]

    def save_checkpoint(self, shard: str, sequence_number: str) -> None:
        self.dynamodb.put_item(
            TableName=aws.CHECKPOINT_TABLE,
            Item={
                "consumer": {"S": self.name},
                "shard_id": {"S": shard},
                "sequence_number": {"S": sequence_number},
                "run_id": {"N": str(self.run_id)},
                "updated_at": {"S": _now().isoformat()},
            },
        )
        self.checkpoints[shard] = sequence_number

    # --- polling & applying ------------------------------------------------
    def poll_and_apply(self) -> None:
        buffer: list[tuple[str, dict]] = []
        last_seq: dict[str, str] = {}
        deadline = time.monotonic() + self.batch_seconds
        caught_up = False

        while True:
            got_records = False
            for shard in self.shards:
                try:
                    response = self.kinesis.get_records(ShardIterator=self.iterators[shard], Limit=1000)
                except self.kinesis.exceptions.ExpiredIteratorException:
                    self.iterators[shard] = self.new_iterator(shard)
                    continue

                self.iterators[shard] = response["NextShardIterator"]
                records = response.get("Records", [])
                if records:
                    got_records = True
                    buffer.extend((shard, r) for r in records)
                    last_seq[shard] = records[-1]["SequenceNumber"]

            if not got_records:
                caught_up = True
            if len(buffer) >= MAX_BATCH_EVENTS or time.monotonic() >= deadline:
                break
            if not got_records:
                time.sleep(0.5)

        # Fence: a newer run resets the targets. Applying this run's batch
        # after that would write into the fresh tables ahead of the full load
        # (duplicates on engines without enforced keys). Drop it uncommitted;
        # the new run replays these changes from its own start.
        if not self.run_still_current():
            log.info("A newer migration run started; dropping uncommitted batch of %d record(s)", len(buffer))
            self.run_id = None
            return

        self.apply(buffer, last_seq, caught_up and len(buffer) < MAX_BATCH_EVENTS)

    def run_still_current(self) -> bool:
        run = latest_run()
        return bool(run) and run["id"] == self.run_id and run["status"] not in ("preparing", "cancelled")

    def apply(self, buffer: list[tuple[str, dict]], last_seq: dict[str, str], caught_up: bool) -> None:
        events = []
        heartbeats: dict[str, str] = {}
        newest_arrival = None

        for shard, record in buffer:
            payload = json.loads(record["Data"])
            if payload.get("type") == "heartbeat":
                heartbeats[shard] = payload["token"]
            else:
                events.append(payload)
            newest_arrival = record.get("ApproximateArrivalTimestamp") or newest_arrival

        change_count = 0
        if events:
            changes = build_changes(events)
            change_count = sum(len(c) for c in changes.values())
            for table in BUSINESS_TABLES:
                if table in changes:
                    self.target.apply_changes(table, changes[table])
            self.target.append_audit(events)
        self.target.after_batch()

        # Only after the target committed: move checkpoints and watermarks.
        for shard, sequence_number in last_seq.items():
            self.save_checkpoint(shard, sequence_number)
        self.heartbeats.update(heartbeats)

        tokens = {self.heartbeats.get(s) for s in self.shards}
        if len(tokens) == 1 and None not in tokens:
            self.last_heartbeat = tokens.pop()

        self.events_seen += len(buffer)
        self.events_applied += len(events)
        if events:
            newest = max(events, key=lambda e: lsn_to_int(e.get("lsn")))
            self.last_lsn = newest.get("lsn") or self.last_lsn

        if caught_up:
            seconds_behind = 0.0
        elif newest_arrival is not None:
            seconds_behind = max(0.0, (_now() - newest_arrival).total_seconds())
        else:
            seconds_behind = None

        fields = dict(
            state="in_sync" if caught_up else "catching_up",
            run_id=self.run_id,
            events_seen=self.events_seen,
            events_applied=self.events_applied,
            seconds_behind=seconds_behind,
            last_heartbeat=self.last_heartbeat,
            message=None,
        )
        if self.last_lsn:
            fields["last_applied_lsn"] = self.last_lsn
        if events:
            fields["last_event_at"] = _now()
        self.status(**fields)

        if events:
            log.info(
                "Applied %d event(s) -> %d change(s) [%s]",
                len(events), change_count,
                "in sync" if caught_up else "catching up",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="CDC applier (Kinesis -> target)")
    parser.add_argument("--target", required=True, choices=sorted(DEFAULT_BATCH_SECONDS))
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [applier:" + args.target + "] %(message)s",
    )
    # The Databricks connector logs every HTTP request at INFO; keep it quiet.
    for noisy in ("databricks.sql", "databricks.sdk", "urllib3", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    Applier(args.target).run_forever()


if __name__ == "__main__":
    main()
