"""Migrate local menu images + hero banners into Emergent object storage so
they survive deploys and are readable from production.

- master_menu.image_url starting with /api/uploads/  -> uploaded to
  bongconnekt/menu/{item_id}.<ext>, image_url rewritten to /api/files/...
- hero banners -> bongconnekt/banners/hero-meal.png, hero-grocery.png
"""
import asyncio
import logging
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
load_dotenv("/app/backend/.env")  # populate os.environ BEFORE storage_client import

from motor.motor_asyncio import AsyncIOMotorClient

import storage_client as obj

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("migrate-img")
env = dotenv_values("/app/backend/.env")

UPLOADS = Path("/app/backend/uploads")
CT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


def local_path_for(url: str) -> Path | None:
    # /api/uploads/menu/xyz.png -> /app/backend/uploads/menu/xyz.png
    if not url or not url.startswith("/api/uploads/"):
        return None
    rel = url[len("/api/uploads/"):]
    p = UPLOADS / rel
    return p if p.exists() else None


async def main():
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]
    obj.init_storage()

    migrated = skipped = 0
    async for m in db.master_menu.find({}, {"_id": 0, "item_id": 1, "image_url": 1}):
        url = m.get("image_url") or ""
        lp = local_path_for(url)
        if not lp:
            skipped += 1
            continue
        ext = lp.suffix.lstrip(".").lower() or "png"
        dest = f"bongconnekt/menu/{m['item_id']}.{ext}"
        obj.put_object(dest, lp.read_bytes(), CT.get(ext, "image/png"))
        new_url = f"/api/files/{dest}"
        await db.master_menu.update_one({"item_id": m["item_id"]}, {"$set": {"image_url": new_url}})
        migrated += 1
        log.info(f"  ✓ {m['item_id']} -> {new_url}")

    # Hero banners
    for fname in ("hero-meal.png", "hero-grocery.png"):
        src = UPLOADS / "menu" / fname
        if src.exists():
            dest = f"bongconnekt/banners/{fname}"
            obj.put_object(dest, src.read_bytes(), "image/png")
            log.info(f"  ✓ banner -> /api/files/{dest}")

    log.info(f"DONE migrated={migrated} skipped(non-local)={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
