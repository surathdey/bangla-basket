"""One-off: fill image + description for master_menu dishes missing them.

Only sets short_description, full_description and image_url. The existing
veg_type / category / cuisine / spice_level are PRESERVED (never overwritten).
"""
import asyncio
import logging
from datetime import datetime, timezone

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

import menu_ai

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("enrich")

env = dotenv_values("/app/backend/.env")


async def main():
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    q = {"$or": [
        {"image_url": {"$in": [None, ""]}},
        {"image_url": {"$exists": False}},
        {"short_description": {"$in": [None, ""]}},
        {"short_description": {"$exists": False}},
    ]}
    docs = [d async for d in db.master_menu.find(q, {"_id": 0})]
    log.info(f"found {len(docs)} dishes to enrich")

    for d in docs:
        name = d.get("name", "")
        iid = d.get("item_id")
        price = int(d.get("default_price_cents") or 0)
        cuisine = d.get("cuisine") or "bengali"
        set_fields = {"updated_at": datetime.now(timezone.utc)}

        # Text (descriptions only — keep existing classification)
        if not d.get("short_description") or not d.get("full_description"):
            txt = await menu_ai.enrich_text(name, price)
            set_fields["short_description"] = txt.get("short_description", "")
            set_fields["full_description"] = txt.get("full_description", "")
            short_hint = set_fields["short_description"]
        else:
            short_hint = d.get("short_description", "")

        # Image
        if not d.get("image_url"):
            img = await menu_ai.enrich_image(name, short_hint, cuisine)
            if img:
                set_fields["image_url"] = img

        await db.master_menu.update_one({"item_id": iid}, {"$set": set_fields})
        log.info(f"  ✓ {name}: img={'Y' if set_fields.get('image_url') else 'skip/none'} "
                 f"sdesc={'Y' if set_fields.get('short_description') else 'kept'}")

    log.info("DONE")


if __name__ == "__main__":
    asyncio.run(main())
