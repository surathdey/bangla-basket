"""Key-route response-shape checks: menu, thali, cart/order, loyalty.

Seeds are prefixed ``k`` (kg1, km1, ktp1, kcust1) so they never collide
with the ids other test files use; no truncate here, because this file
runs alphabetically before test_pgdb.py and must not leave rows that
break its inserts.

Run with the same throwaway Postgres as the other test files:
    BB_TEST_DSN=postgresql://bangla:bangla@127.0.0.1:54399/banglabasket_test \
        python -m pytest tests/test_key_routes.py -q
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-dev-only-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-dev-only-password")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "BB_TEST_DSN",
        "postgresql://bangla:bangla@127.0.0.1:54399/banglabasket_test"))
os.environ.setdefault("UPLOADS_DIR", "/tmp/bb-test-uploads")
os.environ.setdefault("MINIO_ENDPOINT", "http://127.0.0.1:9")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from pgdb import PgDatabase  # noqa: E402

DSN = os.environ["DATABASE_URL"]
NOW = datetime.now(timezone.utc)


def _sunday_of(d):
    return d - timedelta(days=(d.weekday() + 1) % 7)


async def _seed():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    db = PgDatabase(DSN, pool=pool)
    try:
        # Idempotent re-runs: clear this file's own rows first.
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM grocery WHERE item_id = 'kg1'")
            await conn.execute(
                "DELETE FROM master_menu WHERE item_id = 'km1'")
            await conn.execute(
                "DELETE FROM thali_packages WHERE package_id = 'ktp1'")
            await conn.execute(
                "DELETE FROM weekly_menus WHERE week_start = $1",
                _sunday_of(NOW.date()).isoformat())
            await conn.execute(
                "DELETE FROM users WHERE user_id = 'kcust1'")
            await conn.execute(
                "DELETE FROM user_sessions "
                "WHERE session_token = 'tok-kcust1'")
        await db.grocery.insert_one({
            "item_id": "kg1", "title": "Katla Fish", "category": "Fish",
            "price_cents": 500, "is_active": True, "deleted_at": None,
            "image_url": "", "created_at": NOW, "updated_at": NOW})
        await db.master_menu.insert_one({
            "item_id": "km1", "name": "Mutton Kosha",
            "default_price_cents": 1200, "is_active": True,
            "short_description": "Slow-cooked mutton",
            "category": "curry", "veg_type": "non-veg",
            "spice_level": "medium", "image_url": "",
            "created_at": NOW, "updated_at": NOW})
        await db.thali_packages.insert_one({
            "package_id": "ktp1", "name": "Veg Thali",
            "is_active": True, "sort_order": 1,
            "per_person_price_cents": 999, "created_at": NOW})
        await db.weekly_menus.insert_one({
            "week_start": _sunday_of(NOW.date()).isoformat(),
            "published": True, "status": "published",
            "lines": [{"line_id": "kl1", "master_item_id": "km1",
                       "is_visible": True}],
            "created_at": NOW, "updated_at": NOW})
        await db.users.insert_one({
            "user_id": "kcust1", "email": "kcust@example.com",
            "name": "Key Customer",
            "role": "customer", "loyalty_points": 100,
            "created_at": NOW})
        await db.user_sessions.insert_one({
            "session_token": "tok-kcust1", "user_id": "kcust1",
            "created_at": NOW,
            "expires_at": NOW + timedelta(days=7)})
    finally:
        await db.close()


def _no_id(obj):
    # Exact-key check (not a substring scan: "line_id" is legitimate).
    if isinstance(obj, dict):
        assert "_id" not in obj, "leaked _id in response"
        for v in obj.values():
            _no_id(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_id(v)


def test_menu_thali_order_and_loyalty_shapes():
    asyncio.run(_seed())
    with TestClient(server.app) as client:
        # Menu: current week hydrates lines against master_menu.
        menu = client.get("/api/menu/current")
        assert menu.status_code == 200, menu.text
        body = menu.json()
        _no_id(body)
        assert body["week_start"] == _sunday_of(NOW.date()).isoformat()
        assert body["items"][0]["name"] == "Mutton Kosha"
        assert body["items"][0]["price_cents"] == 1200

        # Thali: list + detail, no _id.
        thali = client.get("/api/thali")
        assert thali.status_code == 200, thali.text
        _no_id(thali.json())
        assert any(p["package_id"] == "ktp1"
                   for p in thali.json())
        detail = client.get("/api/thali/ktp1")
        assert detail.status_code == 200
        assert detail.json()["package_id"] == "ktp1"
        _no_id(detail.json())

        # Guest checkout (COD): cart -> order shape, integer cents.
        guest = client.post("/api/auth/guest")
        assert guest.status_code == 200, guest.text
        token = guest.json()["session_token"]
        order_body = {
            "items": [{"kind": "grocery", "ref_id": "kg1",
                       "quantity": 2}],
            "address": {"line1": "1 Test St", "city": "Milton",
                        "province": "ON", "postal_code": "L9T 1A1"},
            "slot": {"date": "2026-11-06", "window": "friday_evening"},
            "phone": "6470000000", "payment_method": "cod"}
        order = client.post("/api/orders", json=order_body, headers={
            "Authorization": f"Bearer {token}"})
        assert order.status_code == 200, order.text
        o = order.json()
        _no_id(o)
        assert o["order_id"].startswith("ord_")
        assert o["subtotal_cents"] == 1000
        assert o["items_snapshot"][0]["line_total_cents"] == 1000
        assert o["status"] == "confirmed"
        assert o["payment_status"] == "cod_pending"
        assert isinstance(o["delivery_fee_cents"], int)
        assert isinstance(o["tax_cents"], int)

        fetched = client.get(f"/api/orders/{o['order_id']}", headers={
            "Authorization": f"Bearer {token}"})
        assert fetched.status_code == 200
        assert fetched.json()["order_id"] == o["order_id"]
        _no_id(fetched.json())

        # Loyalty: a customer COD order earns points (default 1 pt/$).
        cust_order = client.post("/api/orders", json={
            **order_body,
            "items": [{"kind": "grocery", "ref_id": "kg1",
                       "quantity": 1}]}, headers={
            "Authorization": "Bearer tok-kcust1"})
        assert cust_order.status_code == 200, cust_order.text
        co = cust_order.json()
        assert co["points_awarded"] == 5  # $5.00 subtotal x 1 pt/$
        me = client.get("/api/auth/me", headers={
            "Authorization": "Bearer tok-kcust1"})
        assert me.status_code == 200
        assert "loyalty_points" in me.json()
        _no_id(me.json())
