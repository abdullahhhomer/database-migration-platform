"""
Common interface every migration target implements.

The orchestrator (full load), the CDC applier and the validator only talk to
this interface, so adding another engine means adding one class.
"""

from dataclasses import dataclass, field


@dataclass
class Change:
    """One CDC change after per-key de-duplication within a micro-batch."""
    op: str                 # 'I', 'U' or 'D'
    pk: int
    row: dict = field(default_factory=dict)   # full new row for I/U, empty for D


class Target:
    name = "base"

    # Rows read from Postgres per full-load batch for this target.
    batch_size = 5000

    # --- lifecycle -------------------------------------------------------
    def prepare(self, reset: bool) -> None:
        """Creates database/schemas/tables. With reset=True drops existing data."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    # --- full load -------------------------------------------------------
    def load_units(self) -> list[str]:
        """Source tables this target full-loads (MongoDB embeds some)."""
        raise NotImplementedError

    def truncate_after(self, table: str, last_id: int) -> None:
        """Removes rows past a job's checkpoint before resuming it."""
        raise NotImplementedError

    def load_batch(self, table: str, columns: list[str], rows: list[tuple], run_id: int) -> None:
        raise NotImplementedError

    # --- CDC -------------------------------------------------------------
    def apply_changes(self, table: str, changes: list[Change]) -> None:
        raise NotImplementedError

    def append_audit(self, events: list[dict]) -> None:
        """Optional raw change log (only the lakehouse keeps one)."""

    def after_batch(self) -> None:
        """Called after every applied micro-batch (e.g. to retry deferred changes)."""

    # --- validation ------------------------------------------------------
    def count(self, table: str) -> int:
        raise NotImplementedError

    def sum_column(self, table: str, column: str):
        raise NotImplementedError

    def duplicate_ids(self, table: str) -> int | None:
        """None when the engine enforces primary keys itself."""
        return None

    def orphans(self, child: str, fk: str, parent: str, parent_key: str) -> int:
        raise NotImplementedError

    def fetch_rows(self, table: str, ids: list[int]) -> dict[int, dict]:
        raise NotImplementedError

    # --- cutover ---------------------------------------------------------
    def add_constraints(self) -> None:
        pass

    def drop_constraints(self) -> None:
        pass
