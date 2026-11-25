"""
CDC event decoding and per-key de-duplication.

Event format (produced by cdc-worker, one Kinesis record each):
    {"lsn": "0/1B82BB90", "table": "orders", "op": "U", "pk": 42,
     "row": {"id": "42", "total_amount": "760.57", ...},      # wal2json text values
     "types": {"id": "bigint", "total_amount": "numeric(12,2)", ...},
     "commit_ts": "2026-11-25 19:13:03.399775+00"}

Heartbeats (cutover watermark) look like {"type": "heartbeat", "token": "..."}.
"""

from app.migration.schema import BUSINESS_TABLES
from app.migration.type_mapping import from_wal2json
from app.targets.base import Change


def lsn_to_int(lsn: str | None) -> int:
    if not lsn:
        return 0
    high, low = lsn.split("/")
    return (int(high, 16) << 32) + int(low, 16)


def decode_row(event: dict) -> dict:
    types = event.get("types") or {}
    return {
        name: from_wal2json(value, types.get(name, "text"))
        for name, value in (event.get("row") or {}).items()
    }


def build_changes(events: list[dict]) -> dict[str, list[Change]]:
    """
    Collapses a micro-batch to the final state per (table, primary key).
    Events for one key are always on the same shard and in commit order, so
    the last one wins; replaying it as an upsert or delete is idempotent.
    """
    latest: dict[tuple[str, int], Change] = {}

    for event in events:
        table = event.get("table")
        if table not in BUSINESS_TABLES:
            continue
        pk = int(event["pk"])
        op = event["op"]
        row = decode_row(event) if op != "D" else {}
        latest[(table, pk)] = Change(op=op, pk=pk, row=row)

    grouped: dict[str, list[Change]] = {t: [] for t in BUSINESS_TABLES}
    for (table, _pk), change in latest.items():
        grouped[table].append(change)

    return {t: changes for t, changes in grouped.items() if changes}
