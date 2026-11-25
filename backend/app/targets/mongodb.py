"""
MongoDB target (stand-in for Amazon DocumentDB): relational -> document.

Document model:
    customers  { _id, first_name, last_name, email, phone, created_at, updated_at }
    products   { _id, sku, name, category, price, stock_quantity, ... }
    orders     { _id, customer_id, status, total_amount, order_date, updated_at,
                 items:     [ { id, product_id, quantity, unit_price, created_at,
                                returns: [ { id, reason, quantity, status, created_at } ] } ],
                 payments:  [ { id, amount, status, payment_method, ... } ],
                 shipments: [ { id, status, carrier, tracking_number, ... } ] }

Seven relational tables become three collections. Child rows are embedded
in their order, so a CDC change to e.g. order_items updates an array element.
"""

import datetime as dt
import logging
from decimal import Decimal

from bson.decimal128 import Decimal128
from pymongo import ASCENDING, MongoClient

from app.config import mongodb_settings
from app.migration.reader import get_db_connection
from app.migration.schema import get_columns
from app.targets.base import Change, Target


log = logging.getLogger("targets.mongodb")

COLLECTIONS = ["customers", "products", "orders"]
ARRAY_FIELD = {"order_items": "items", "payments": "payments", "shipments": "shipments"}


def to_bson(value):
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return dt.datetime(value.year, value.month, value.day)
    return value


def to_doc(row: dict, id_field: str = "_id", drop: tuple = ()) -> dict:
    doc = {}
    for key, value in row.items():
        if key in drop:
            continue
        doc[id_field if key == "id" else key] = to_bson(value)
    return doc


def _rows(cursor) -> list[dict]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


class MongoTarget(Target):
    name = "mongodb"
    batch_size = 5000

    def __init__(self):
        self.settings = mongodb_settings()
        self._client = None
        # Return events whose order item has not arrived yet (cross-shard
        # ordering); retried on the next micro-batches.
        self._pending_returns: list[tuple[Change, int]] = []

    # --- connection ------------------------------------------------------
    @property
    def db(self):
        if self._client is None:
            self._client = MongoClient(self.settings["uri"], serverSelectionTimeoutMS=10000)
        return self._client[self.settings["database"]]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # --- lifecycle -------------------------------------------------------
    def prepare(self, reset: bool) -> None:
        if reset:
            for name in COLLECTIONS:
                self.db.drop_collection(name)

        orders = self.db["orders"]
        orders.create_index([("customer_id", ASCENDING)])
        orders.create_index([("items.id", ASCENDING)])
        orders.create_index([("items.returns.id", ASCENDING)])
        orders.create_index([("payments.id", ASCENDING)])
        orders.create_index([("shipments.id", ASCENDING)])

    # --- full load -------------------------------------------------------
    def load_units(self) -> list[str]:
        # order_items, payments, shipments and returns are embedded in orders.
        return list(COLLECTIONS)

    def truncate_after(self, table: str, last_id: int) -> None:
        self.db[table].delete_many({"_id": {"$gt": int(last_id)}})

    def _order_documents(self, orders: list[dict]) -> list[dict]:
        low, high = orders[0]["id"], orders[-1]["id"]
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM order_items WHERE order_id BETWEEN %s AND %s ORDER BY id",
                    (low, high),
                )
                items = _rows(cursor)
                cursor.execute(
                    "SELECT r.* FROM returns r JOIN order_items oi ON oi.id = r.order_item_id "
                    "WHERE oi.order_id BETWEEN %s AND %s ORDER BY r.id",
                    (low, high),
                )
                returns = _rows(cursor)
                cursor.execute(
                    "SELECT * FROM payments WHERE order_id BETWEEN %s AND %s ORDER BY id",
                    (low, high),
                )
                payments = _rows(cursor)
                cursor.execute(
                    "SELECT * FROM shipments WHERE order_id BETWEEN %s AND %s ORDER BY id",
                    (low, high),
                )
                shipments = _rows(cursor)
        finally:
            connection.close()

        returns_by_item: dict[int, list] = {}
        for r in returns:
            returns_by_item.setdefault(r["order_item_id"], []).append(
                to_doc(r, id_field="id", drop=("order_item_id",))
            )

        docs = {o["id"]: {**to_doc(o), "items": [], "payments": [], "shipments": []} for o in orders}

        for item in items:
            if item["order_id"] in docs:
                sub = to_doc(item, id_field="id", drop=("order_id",))
                sub["returns"] = returns_by_item.get(item["id"], [])
                docs[item["order_id"]]["items"].append(sub)
        for p in payments:
            if p["order_id"] in docs:
                docs[p["order_id"]]["payments"].append(to_doc(p, id_field="id", drop=("order_id",)))
        for s in shipments:
            if s["order_id"] in docs:
                docs[s["order_id"]]["shipments"].append(to_doc(s, id_field="id", drop=("order_id",)))

        return list(docs.values())

    def load_batch(self, table: str, columns: list[str], rows: list[tuple], run_id: int) -> None:
        if not rows:
            return
        records = [dict(zip(columns, row)) for row in rows]
        if table == "orders":
            docs = self._order_documents(records)
        else:
            docs = [to_doc(r) for r in records]
        self.db[table].insert_many(docs, ordered=False)

    # --- CDC -------------------------------------------------------------
    def apply_changes(self, table: str, changes: list[Change]) -> None:
        if table in ("customers", "products"):
            self._apply_top_level(table, changes)
        elif table == "orders":
            self._apply_orders(changes)
        elif table in ARRAY_FIELD:
            self._apply_array(table, changes)
        elif table == "returns":
            self._apply_returns(changes)

    def after_batch(self) -> None:
        if self._pending_returns:
            self._retry_pending_returns()

    def _apply_top_level(self, table: str, changes: list[Change]) -> None:
        coll = self.db[table]
        for c in changes:
            if c.op == "D":
                coll.delete_one({"_id": c.pk})
            else:
                coll.replace_one({"_id": c.pk}, to_doc({**c.row, "id": c.pk}), upsert=True)

    def _apply_orders(self, changes: list[Change]) -> None:
        orders = self.db["orders"]
        for c in changes:
            if c.op == "D":
                orders.delete_one({"_id": c.pk})
                continue
            fields = to_doc({**c.row, "id": c.pk})
            fields.pop("_id", None)
            # $set keeps the embedded arrays; $setOnInsert creates them for new orders.
            orders.update_one(
                {"_id": c.pk},
                {"$set": fields, "$setOnInsert": {"items": [], "payments": [], "shipments": []}},
                upsert=True,
            )

    def _apply_array(self, table: str, changes: list[Change]) -> None:
        field = ARRAY_FIELD[table]
        orders = self.db["orders"]
        for c in changes:
            if c.op == "D":
                orders.update_many({f"{field}.id": c.pk}, {"$pull": {field: {"id": c.pk}}})
                continue

            order_id = c.row.get("order_id")
            sub = to_doc({**c.row, "id": c.pk}, id_field="id", drop=("order_id",))

            if table == "order_items":
                # Update fields in place so the item's embedded returns survive.
                set_fields = {f"items.$.{k}": v for k, v in sub.items()}
                result = orders.update_one({"_id": order_id, "items.id": c.pk}, {"$set": set_fields})
                if result.matched_count:
                    continue
                orders.update_many({"items.id": c.pk}, {"$pull": {"items": {"id": c.pk}}})
                sub["returns"] = []
            else:
                orders.update_many({f"{field}.id": c.pk}, {"$pull": {field: {"id": c.pk}}})

            # Upsert creates a skeleton order if the child arrived first;
            # the order's own change fills in the rest.
            orders.update_one({"_id": order_id}, {"$push": {field: sub}}, upsert=True)

    def _apply_returns(self, changes: list[Change]) -> None:
        for c in changes:
            self._apply_one_return(c, attempts=0)

    def _apply_one_return(self, c: Change, attempts: int) -> None:
        # Returns are nested two levels deep (orders.items[].returns[]). Each
        # target has exactly one CDC applier, so a read-modify-write of the
        # order's items array is safe and works on MongoDB and DocumentDB alike.
        orders = self.db["orders"]

        holder = orders.find_one({"items.returns.id": c.pk}, {"items": 1})
        if holder:
            items = holder["items"]
            for item in items:
                item["returns"] = [r for r in item.get("returns", []) if r.get("id") != c.pk]
            orders.update_one({"_id": holder["_id"]}, {"$set": {"items": items}})

        if c.op == "D":
            return

        item_id = c.row.get("order_item_id")
        sub = to_doc({**c.row, "id": c.pk}, id_field="id", drop=("order_item_id",))
        parent = orders.find_one({"items.id": item_id}, {"items": 1})
        if parent:
            items = parent["items"]
            for item in items:
                if item.get("id") == item_id:
                    item.setdefault("returns", []).append(sub)
            orders.update_one({"_id": parent["_id"]}, {"$set": {"items": items}})
        else:
            if attempts < 50:
                self._pending_returns.append((c, attempts + 1))
            else:
                log.error("Dropping return %s: order item %s never arrived", c.pk, item_id)

    def _retry_pending_returns(self) -> None:
        pending, self._pending_returns = self._pending_returns, []
        for change, attempts in pending:
            self._apply_one_return(change, attempts)

    # --- validation ------------------------------------------------------
    def _aggregate_one(self, pipeline: list) -> dict:
        result = list(self.db["orders"].aggregate(pipeline))
        return result[0] if result else {}

    def count(self, table: str) -> int:
        if table in COLLECTIONS:
            return self.db[table].count_documents({})
        if table in ARRAY_FIELD:
            field = ARRAY_FIELD[table]
            r = self._aggregate_one([
                {"$group": {"_id": None, "n": {"$sum": {"$size": {"$ifNull": [f"${field}", []]}}}}}
            ])
            return int(r.get("n", 0))
        if table == "returns":
            r = self._aggregate_one([
                {"$unwind": "$items"},
                {"$group": {"_id": None, "n": {"$sum": {"$size": {"$ifNull": ["$items.returns", []]}}}}},
            ])
            return int(r.get("n", 0))
        raise ValueError(table)

    def sum_column(self, table: str, column: str):
        if table in COLLECTIONS:
            pipeline = [{"$group": {"_id": None, "s": {"$sum": f"${column}"}}}]
            result = list(self.db[table].aggregate(pipeline))
        else:
            field = ARRAY_FIELD[table]
            result = list(self.db["orders"].aggregate([
                {"$unwind": f"${field}"},
                {"$group": {"_id": None, "s": {"$sum": f"${field}.{column}"}}},
            ]))
        if not result:
            return None
        value = result[0]["s"]
        return value.to_decimal() if hasattr(value, "to_decimal") else value

    def orphans(self, child: str, fk: str, parent: str, parent_key: str) -> int:
        orders = self.db["orders"]
        if (child, fk) == ("orders", "customer_id"):
            refs = set(orders.distinct("customer_id"))
            refs.discard(None)
            return len(refs - set(self.db["customers"].distinct("_id")))
        if (child, fk) == ("order_items", "product_id"):
            refs = set(orders.distinct("items.product_id"))
            refs.discard(None)
            return len(refs - set(self.db["products"].distinct("_id")))
        if parent == "orders":
            # Embedded children cannot reference a missing order, except via
            # a skeleton order (child arrived, order row never did).
            field = ARRAY_FIELD[child]
            return orders.count_documents(
                {"customer_id": {"$exists": False}, f"{field}.0": {"$exists": True}}
            )
        # returns -> order_items: embedded inside their item, so always resolved.
        return 0

    def fetch_rows(self, table: str, ids: list[int]) -> dict[int, dict]:
        ids = [int(i) for i in ids]
        names = [c.name for c in get_columns(table)]

        def flatten(doc: dict, extra: dict | None = None) -> dict:
            record = {"id": doc.get("id", doc.get("_id"))}
            record.update(extra or {})
            for n in names:
                if n not in record:
                    record[n] = doc.get(n)
            return {n: record.get(n) for n in names}

        if table in COLLECTIONS:
            projection = {"items": 0, "payments": 0, "shipments": 0} if table == "orders" else None
            return {
                d["_id"]: flatten(d)
                for d in self.db[table].find({"_id": {"$in": ids}}, projection)
            }

        if table in ARRAY_FIELD:
            field = ARRAY_FIELD[table]
            pipeline = [
                {"$match": {f"{field}.id": {"$in": ids}}},
                {"$unwind": f"${field}"},
                {"$match": {f"{field}.id": {"$in": ids}}},
                {"$project": {"order_id": "$_id", "sub": f"${field}"}},
            ]
            return {
                r["sub"]["id"]: flatten(r["sub"], {"order_id": r["order_id"]})
                for r in self.db["orders"].aggregate(pipeline)
            }

        if table == "returns":
            pipeline = [
                {"$match": {"items.returns.id": {"$in": ids}}},
                {"$unwind": "$items"},
                {"$unwind": "$items.returns"},
                {"$match": {"items.returns.id": {"$in": ids}}},
                {"$project": {"item_id": "$items.id", "sub": "$items.returns"}},
            ]
            return {
                r["sub"]["id"]: flatten(r["sub"], {"order_item_id": r["item_id"]})
                for r in self.db["orders"].aggregate(pipeline)
            }

        raise ValueError(table)
