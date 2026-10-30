"""Provider tests for backend/pgdb.py against a real local Postgres.

Setup (see README "Verification"): start a throwaway Postgres cluster and
apply schema.sql, then run:
    BB_TEST_DSN=postgresql://bangla:bangla@127.0.0.1:54399/banglabasket_test \\
        python -m pytest tests/test_pgdb.py -q

Every test truncates all tables first, so tests are independent and order
does not matter. No test touches MongoDB, the network, or any live system.
"""
import asyncio
import os
import re
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from pgdb import PgDatabase, TABLES  # noqa: E402

DSN = os.environ.get(
    "BB_TEST_DSN",
    "postgresql://bangla:bangla@127.0.0.1:54399/banglabasket_test")
NOW = datetime.now(timezone.utc)


def run(coro):
    return asyncio.run(coro)


async def _truncate(pool):
    async with pool.acquire() as conn:
        for table in TABLES:
            await conn.execute(f'DELETE FROM "{table}"')


async def _fresh_db():
    """New pool + truncated tables, in the caller's loop."""
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    await _truncate(pool)
    return PgDatabase(DSN, pool=pool)



def test_insert_find_one_and_datetimes():
    async def _t():
        db = await _fresh_db()
        try:
            doc = {"user_id": "user_1", "email": "a@example.com", "name": "A",
                   "created_at": NOW, "first_login_at": None}
            res = await db.users.insert_one(doc)
            assert res.inserted_id == doc["_id"]
            got = await db.users.find_one({"user_id": "user_1"})
            assert got["email"] == "a@example.com"
            assert isinstance(got["created_at"], datetime)
            assert got["created_at"] == NOW
            assert got["first_login_at"] is None
            assert got["_id"] == doc["_id"]
            # Projection strips _id, like the old {"_id": 0} projections.
            pub = await db.users.find_one({"user_id": "user_1"}, {"_id": 0})
            assert "_id" not in pub
            assert pub["user_id"] == "user_1"
        finally:
            await db.close()
    run(_t())


def test_filters():
    async def _t():
        db = await _fresh_db()
        try:
            await db.grocery.insert_one(
                {"item_id": "g1", "category": "Fish", "price_cents": 500,
                 "is_active": True, "deleted_at": None})
            await db.grocery.insert_one(
                {"item_id": "g2", "category": "Fish", "price_cents": 1500,
                 "is_active": True})
            await db.grocery.insert_one(
                {"item_id": "g3", "category": "Rice", "price_cents": 300,
                 "is_active": False, "deleted_at": None})
            # $eq / $ne (Mongo semantics: None equality matches null AND
            # missing; $ne None matches neither).
            rows = await db.grocery.find({"category": "Fish"}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g2"]
            rows = await db.grocery.find({"deleted_at": None}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g2", "g3"]
            rows = await db.grocery.find(
                {"deleted_at": {"$ne": None}}).to_list()
            assert rows == []
            # $in / $nin (None inside $nin excludes null AND missing).
            rows = await db.grocery.find(
                {"item_id": {"$in": ["g1", "g3"]}}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g3"]
            rows = await db.grocery.find(
                {"deleted_at": {"$nin": [None, ""]}}).to_list()
            assert rows == []
            # Numeric comparisons (text extraction must NOT compare as text:
            # 1500 > 500 numerically, and "500" < "1500" lexicographically).
            rows = await db.grocery.find(
                {"price_cents": {"$gt": 1000}}).to_list()
            assert [r["item_id"] for r in rows] == ["g2"]
            rows = await db.grocery.find(
                {"price_cents": {"$lt": 1000}}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g3"]
            # $regex (case-insensitive, re.escape'd input like the search code).
            rows = await db.grocery.find(
                {"category": {"$regex": re.compile(re.escape("fis"),
                                                   re.IGNORECASE)}}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g2"]
            # $or / $and.
            rows = await db.grocery.find(
                {"$or": [{"category": "Rice"}, {"price_cents": 500}]}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g3"]
            rows = await db.grocery.find(
                {"$and": [{"is_active": True},
                          {"price_cents": {"$gte": 500}}]}).to_list()
            assert sorted(r["item_id"] for r in rows) == ["g1", "g2"]
            # Boolean filter.
            rows = await db.grocery.find({"is_active": False}).to_list()
            assert [r["item_id"] for r in rows] == ["g3"]
            assert await db.grocery.count_documents({}) == 3
        finally:
            await db.close()
    run(_t())


def test_dotted_array_filter_and_positional_projection():
    async def _t():
        db = await _fresh_db()
        try:
            await db.weekly_menus.insert_one({
                "week_start": "2026-11-01",
                "items": [{"item_id": "m1", "name": "One"},
                          {"item_id": "m2", "name": "Two"}],
                "lines": [{"line_id": "l1", "master_item_id": "m1",
                           "stock_used": 0}]})
            # Dotted filter matches the document...
            doc = await db.weekly_menus.find_one({"items.item_id": "m2"})
            assert doc is not None
            # ...and the positional projection keeps ONLY the matching element.
            doc = await db.weekly_menus.find_one(
                {"items.item_id": "m2"}, {"_id": 0, "items.$": 1})
            assert doc == {"items": [{"item_id": "m2", "name": "Two"}]}
            doc = await db.weekly_menus.find_one(
                {"lines.master_item_id": "m1"}, {"_id": 0, "lines.$": 1})
            assert doc["lines"][0]["line_id"] == "l1"
        finally:
            await db.close()
    run(_t())


def test_sort_limit_skip():
    async def _t():
        db = await _fresh_db()
        try:
            for i, price in enumerate([300, 100, 200]):
                await db.grocery.insert_one(
                    {"item_id": f"g{i}", "price_cents": price,
                     "title": f"T{i}", "sort_order": 3 - i})
            rows = await db.grocery.find({}).sort(
                [("price_cents", 1)]).to_list()
            assert [r["item_id"] for r in rows] == ["g1", "g2", "g0"]
            rows = await db.grocery.find({}).sort("sort_order", -1).limit(2).to_list()
            assert [r["item_id"] for r in rows] == ["g0", "g1"]
            rows = await db.grocery.find({}).sort(
                [("price_cents", 1)]).skip(1).limit(1).to_list()
            assert [r["item_id"] for r in rows] == ["g2"]
            # to_list(n) caps on top of the cursor limit.
            rows = await db.grocery.find({}).limit(3).to_list(2)
            assert len(rows) == 2
            # async-for respects the cursor limit.
            seen = []
            async for row in db.grocery.find({}).sort([("price_cents", 1)]):
                seen.append(row["item_id"])
            assert seen == ["g1", "g2", "g0"]
        finally:
            await db.close()
    run(_t())


def test_updates():
    async def _t():
        db = await _fresh_db()
        try:
            await db.users.insert_one(
                {"user_id": "u1", "loyalty_points": 10,
                 "default_address": {"city": "Milton"},
                 "integrations": {"email": {}}})
            # $set (incl. dotted nested creation) + $inc.
            res = await db.users.update_one(
                {"user_id": "u1"},
                {"$set": {"integrations.email.recipient": "x@example.com",
                          "name": "New"},
                 "$inc": {"loyalty_points": 5}})
            assert (res.matched_count, res.modified_count) == (1, 1)
            got = await db.users.find_one({"user_id": "u1"})
            assert got["integrations"]["email"]["recipient"] == "x@example.com"
            assert got["loyalty_points"] == 15
            # No-op $set reports modified 0 (Stripe webhook depends on this).
            res = await db.users.update_one(
                {"user_id": "u1"}, {"$set": {"name": "New"}})
            assert (res.matched_count, res.modified_count) == (1, 0)
            # $unset really removes the key (absent, not null).
            await db.users.update_one(
                {"user_id": "u1"}, {"$unset": {"default_address": ""}})
            got = await db.users.find_one({"user_id": "u1"})
            assert "default_address" not in got
            # $push single + $each, then $pull by element field.
            await db.orders.insert_one(
                {"order_id": "o1", "tracking_events": [],
                 "items_snapshot": [{"item_id": "a"}, {"item_id": "b"}]})
            await db.orders.update_one(
                {"order_id": "o1"},
                {"$push": {"tracking_events": {"$each": [
                    {"ts": "2026-10-30T00:00:00+00:00", "event": "placed"},
                    {"ts": "2026-10-30T01:00:00+00:00", "event": "paid"}]}}})
            await db.orders.update_one(
                {"order_id": "o1"},
                {"$pull": {"items_snapshot": {"item_id": "a"}}})
            got = await db.orders.find_one({"order_id": "o1"})
            assert [e["event"] for e in got["tracking_events"]] == ["placed", "paid"]
            assert got["items_snapshot"] == [{"item_id": "b"}]
            # Positional $inc on a matched array element.
            await db.weekly_menus.insert_one({
                "week_start": "2026-11-01",
                "lines": [{"line_id": "l1", "master_item_id": "m1",
                           "stock_used": 2},
                          {"line_id": "l2", "master_item_id": "m2",
                           "stock_used": 0}]})
            await db.weekly_menus.update_one(
                {"week_start": "2026-11-01", "lines.master_item_id": "m2"},
                {"$inc": {"lines.$.stock_used": 3}})
            got = await db.weekly_menus.find_one({"week_start": "2026-11-01"})
            assert got["lines"][0]["stock_used"] == 2
            assert got["lines"][1]["stock_used"] == 3
            # update_many touches every match.
            await db.grocery.insert_one({"item_id": "g1", "is_active": True})
            await db.grocery.insert_one({"item_id": "g2", "is_active": True})
            res = await db.grocery.update_many(
                {"is_active": True}, {"$set": {"is_active": False}})
            assert (res.matched_count, res.modified_count) == (2, 2)
        finally:
            await db.close()
    run(_t())


def test_upsert_and_replace():
    async def _t():
        db = await _fresh_db()
        try:
            res = await db.user_sessions.update_one(
                {"session_token": "sess_1"},
                {"$set": {"user_id": "u1", "created_at": NOW,
                          "expires_at": NOW + timedelta(days=7)}},
                upsert=True)
            assert res.upserted_id is not None
            got = await db.user_sessions.find_one({"session_token": "sess_1"})
            assert got["user_id"] == "u1"
            assert isinstance(got["expires_at"], datetime)
            # replace_one preserves _id when the replacement lacks it.
            await db.master_menu.insert_one(
                {"item_id": "m1", "name": "Old", "created_at": NOW})
            old = await db.master_menu.find_one({"item_id": "m1"})
            res = await db.master_menu.replace_one(
                {"item_id": "m1"},
                {"item_id": "m1", "name": "New", "created_at": NOW})
            assert (res.matched_count, res.modified_count) == (1, 1)
            got = await db.master_menu.find_one({"item_id": "m1"})
            assert got["name"] == "New" and got["_id"] == old["_id"]
            # replace_one upsert inserts the replacement.
            res = await db.master_menu.replace_one(
                {"item_id": "m9"},
                {"item_id": "m9", "name": "Nine"}, upsert=True)
            assert res.matched_count == 0
            assert await db.master_menu.find_one({"item_id": "m9"}) is not None
        finally:
            await db.close()
    run(_t())


def test_delete_first_match_only_and_find_one_and_update():
    async def _t():
        db = await _fresh_db()
        try:
            await db.password_resets.insert_one(
                {"token_hash": "t1", "used_at": None,
                 "expires_at": NOW + timedelta(hours=1)})
            await db.password_resets.insert_one(
                {"token_hash": "t2", "used_at": None,
                 "expires_at": NOW + timedelta(hours=1)})
            # delete_one removes only the first inserted match.
            res = await db.password_resets.delete_one({"used_at": None})
            assert res.deleted_count == 1
            assert await db.password_resets.find_one(
                {"token_hash": "t1"}) is None
            assert await db.password_resets.find_one(
                {"token_hash": "t2"}) is not None
            # find_one_and_update returns the PRE-update document.
            old = await db.password_resets.find_one_and_update(
                {"token_hash": "t2"}, {"$set": {"used_at": NOW}})
            assert old["used_at"] is None
            got = await db.password_resets.find_one({"token_hash": "t2"})
            assert got["used_at"] == NOW
            # Datetime filter on the SQL side (sweeper / reset-expiry queries).
            rows = await db.password_resets.find(
                {"expires_at": {"$gt": NOW + timedelta(minutes=30)}}).to_list()
            assert [r["token_hash"] for r in rows] == ["t2"]
            res = await db.password_resets.delete_many({})
            assert res.deleted_count == 1
        finally:
            await db.close()
    run(_t())


def test_aggregates():
    async def _t():
        db = await _fresh_db()
        try:
            await db.grocery.insert_one(
                {"item_id": "g1", "category": "Fish", "is_active": True,
                 "deleted_at": None})
            await db.grocery.insert_one(
                {"item_id": "g2", "category": "Fish", "is_active": True,
                 "deleted_at": None})
            await db.grocery.insert_one(
                {"item_id": "g3", "category": "Rice", "is_active": True,
                 "deleted_at": None})
            await db.grocery.insert_one(
                {"item_id": "g4", "category": "Rice", "is_active": False,
                 "deleted_at": None})
            rows = await db.grocery.aggregate([
                {"$match": {"is_active": {"$ne": False}, "deleted_at": None}},
                {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ]).to_list(500)
            assert rows == [{"_id": "Fish", "count": 2},
                            {"_id": "Rice", "count": 1}]
            # Orders revenue: _id None + $sum of a field; empty input -> no rows.
            agg = await db.orders.aggregate([
                {"$match": {"status": {"$ne": "pending_payment"}}},
                {"$group": {"_id": None, "sum": {"$sum": "$total_cents"}}},
            ]).to_list(1)
            assert agg == []
            await db.orders.insert_one(
                {"order_id": "o1", "user_id": "u1", "status": "delivered",
                 "total_cents": 1000, "created_at": NOW})
            await db.orders.insert_one(
                {"order_id": "o2", "user_id": "u1", "status": "pending_payment",
                 "total_cents": 500, "created_at": NOW})
            await db.orders.insert_one(
                {"order_id": "o3", "user_id": "u2", "status": "delivered",
                 "total_cents": 700, "created_at": NOW - timedelta(days=1)})
            agg = await db.orders.aggregate([
                {"$match": {"status": {"$ne": "pending_payment"}}},
                {"$group": {"_id": None, "sum": {"$sum": "$total_cents"}}},
            ]).to_list(1)
            assert agg == [{"_id": None, "sum": 1700}]
            # Per-user stats: $sort then $group with $sum + $first.
            stats = {}
            async for row in db.orders.aggregate([
                {"$match": {"user_id": {"$in": ["u1", "u2"]},
                            "status": {"$ne": "pending_payment"}}},
                {"$sort": {"created_at": -1}},
                {"$group": {"_id": "$user_id",
                            "total_orders": {"$sum": 1},
                            "total_spent_cents": {"$sum": "$total_cents"},
                            "last_order_date": {"$first": "$created_at"},
                            "last_order_status": {"$first": "$status"}}},
            ]):
                stats[row["_id"]] = row
            assert stats["u1"]["total_orders"] == 1
            assert stats["u1"]["total_spent_cents"] == 1000
            assert stats["u1"]["last_order_status"] == "delivered"
            assert stats["u2"]["total_spent_cents"] == 700
        finally:
            await db.close()
    run(_t())


def test_string_datetimes_stay_strings():
    """Fields the code stores as strings must NOT become datetimes."""
    async def _t():
        db = await _fresh_db()
        try:
            await db.weekly_menus.insert_one({
                "week_start": "2026-11-01",
                "created_at": "2026-10-30T05:31:17.167000+00:00",
                "items": []})
            got = await db.weekly_menus.find_one({"week_start": "2026-11-01"})
            # WeeklyMenu.created_at is a model datetime, so the provider DOES
            # convert it (matching Pydantic parsing on model load).
            assert isinstance(got["created_at"], datetime)
            await db.orders.insert_one({
                "order_id": "o1",
                "tracking_events": [{"ts": "2026-10-30T01:00:00+00:00",
                                     "event": "paid"}],
                "created_at": NOW})
            got = await db.orders.find_one({"order_id": "o1"})
            assert isinstance(got["tracking_events"][0]["ts"], str)
            assert isinstance(got["created_at"], datetime)
        finally:
            await db.close()
    run(_t())


def test_users_email_partial_unique_and_startup_cleanup():
    async def _t():
        db = await _fresh_db()
        try:
            await db.users.insert_one(
                {"user_id": "u1", "email": "dup@example.com"})
            with pytest.raises(asyncpg.UniqueViolationError):
                await db.users.insert_one(
                    {"user_id": "u2", "email": "dup@example.com"})
            # Two email-less users coexist (partial index ignores NULLs).
            await db.users.insert_one({"user_id": "u3"})
            await db.users.insert_one({"user_id": "u4"})
            # The startup cleanup (email:null -> $unset) removes the key.
            await db.users.insert_one(
                {"user_id": "u5", "email": None})
            res = await db.users.update_many(
                {"email": None}, {"$unset": {"email": 1}})
            assert res.matched_count == 3  # u3, u4 (missing) + u5 (null)
            got = await db.users.find_one({"user_id": "u5"})
            assert "email" not in got
        finally:
            await db.close()
    run(_t())


def test_index_shims():
    async def _t():
        db = await _fresh_db()
        try:
            assert await db.users.create_index("user_id", unique=True) == "user_id_1"
            assert await db.coupon_redemptions.create_index(
                [("code", 1), ("user_id", 1)]) == "code_1_user_id_1"
            info = await db.users.index_information()
            assert info["email_1"]["partialFilterExpression"] == {
                "email": {"$type": "string"}}
            # No TTL anywhere, so no startup drop branch can fire.
            for coll in ("user_sessions", "otp_challenges", "password_resets",
                         "export_files"):
                info = await getattr(db, coll).index_information()
                for idx in info.values():
                    assert "expireAfterSeconds" not in idx
            assert await db.users.drop_index("email_1") is True
        finally:
            await db.close()
    run(_t())


def test_unknown_collection():
    async def _t():
        db = await _fresh_db()
        try:
            with pytest.raises(AttributeError):
                db.does_not_exist
        finally:
            await db.close()
    run(_t())