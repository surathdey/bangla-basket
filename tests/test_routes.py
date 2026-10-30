"""Route-parity + boot/shape tests for the ported backend.

Setup: same throwaway Postgres as test_pgdb.py (schema.sql applied), then:
    BB_TEST_DSN=postgresql://bangla:bangla@127.0.0.1:54399/banglabasket_test \\
        python -m pytest tests/test_routes.py -q

Environment for the app under test is set here BEFORE importing server.py
(dev placeholders only -- never real secrets). The app's own pool is
created lazily inside the TestClient's event loop; seeding uses a
separate PgDatabase instance (its own pool) so no pool is ever shared
across event loops.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
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
from pgdb import PgDatabase, TABLES  # noqa: E402

DSN = os.environ["DATABASE_URL"]
NOW = datetime.now(timezone.utc)
REPO_ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


async def _truncate_and_seed():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    db = PgDatabase(DSN, pool=pool)
    try:
        async with pool.acquire() as conn:
            for table in TABLES:
                await conn.execute(f'DELETE FROM "{table}"')
        await db.grocery.insert_one({
            "item_id": "g1", "title": "Rui Fish", "category": "Fish",
            "subcategory": "Fresh", "price_cents": 899,
            "is_active": True, "deleted_at": None, "image_url": "",
            "all_categories": ["Fish"], "created_at": NOW,
            "updated_at": NOW})
        await db.grocery.insert_one({
            "item_id": "g2", "title": "Basmati Rice", "category": "Rice",
            "subcategory": "", "price_cents": 499,
            "is_active": True, "deleted_at": None, "image_url": "",
            "all_categories": ["Rice"], "created_at": NOW,
            "updated_at": NOW})
    finally:
        await pool.close()


def test_openapi_route_inventory_matches():
    """Booted app's routes == upstream 139-route inventory minus /dev/seed.

    The inventory records router paths WITHOUT the /api prefix; OpenAPI
    records full paths. /api/files/{path:path} is include_in_schema=False
    so it is absent from OpenAPI -- asserted separately via app.routes.
    """
    inventory = json.loads(
        (Path(__file__).resolve().parent
         / "route_inventory_upstream.json").read_text())
    expected = {(r["method"], r["path"]) for r in inventory
                if r["path"] != "/dev/seed"}
    # The inventory covers @api (router) routes only. Three /api routes are
    # registered directly on the app (@app) in both upstream and this port;
    # they belong in the expected set too.
    app_level = {("GET", "/exports/{token}"),
                 ("GET", "/invoice/{order_id}"),
                 ("GET", "/track/{order_id}")}
    ported_src = (Path(__file__).resolve().parent.parent
                  / "backend" / "server.py").read_text()
    for _, path in app_level:
        assert f'@app.get("/api{path}")' in ported_src
    expected_openapi = ({(m, p) for (m, p) in expected
                         if p != "/files/{path:path}"} | app_level)
    with TestClient(server.app) as client:
        spec = client.get("/openapi.json").json()
    actual = set()
    for path, methods in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in methods:
            actual.add((method.upper(), path[len("/api"):]))
    assert actual == expected_openapi, (
        "missing:", sorted(expected_openapi - actual),
        "extra:", sorted(actual - expected_openapi))
    # The schema-hidden files route still exists on the app. FastAPI
    # 0.110 keeps included-router routes behind an _IncludedRouter entry
    # (original_router), so walk one level down.
    def _iter_routes(routes):
        for r in routes:
            orig = getattr(r, "original_router", None)
            if orig is not None:
                yield from _iter_routes(orig.routes)
            else:
                yield r

    assert any(getattr(r, "path", "") == "/api/files/{path:path}"
               for r in _iter_routes(server.app.routes))


def test_boot_health_guest_and_grocery_shapes():
    run(_truncate_and_seed())
    with TestClient(server.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        # Guest session flow (exercises user + session inserts).
        guest = client.post("/api/auth/guest")
        assert guest.status_code == 200, guest.text
        body = guest.json()
        token = body["session_token"]
        assert body["user"]["role"] == "guest"

        # /auth/me without a token is 401; with the guest token it works.
        assert client.get("/api/auth/me").status_code == 401
        me = client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["user_id"] == body["user"]["user_id"]

        # Grocery list: seeded items, no _id leakage, serializer shape kept.
        res = client.get("/api/grocery")
        assert res.status_code == 200, res.text
        payload = res.json()
        items = payload["items"]
        assert isinstance(items, list) and len(items) == 2
        assert payload["total"] == 2
        for item in items:
            assert "_id" not in item
            assert "all_categories" not in item  # stripped by serializer
        assert sorted(i["item_id"] for i in items) == ["g1", "g2"]

        # Categories aggregate (real $match/$group/$sort pipeline).
        cats = client.get("/api/grocery/categories")
        assert cats.status_code == 200, cats.text
        assert cats.json()["total"] == 2
        names = {c["category"] for c in cats.json()["categories"]}
        assert names == {"Fish", "Rice"}


def test_lazy_modules_import():
    import drive_client  # noqa: F401
    import email_client  # noqa: F401
    import exports  # noqa: F401
    import platform_client  # noqa: F401
    import billing_client  # noqa: F401
    import settings_crypto  # noqa: F401
    import twilio_client  # noqa: F401
    assert email_client.is_configured() is False  # no RESEND_API_KEY in tests
