"""Seed GTA delivery pricing zones from gta_delivery_zones.csv.

Groups the CSV by (Region, Municipality) → one pricing zone per municipality,
with all its FSAs as postal_prefixes. Idempotent: matches existing zones by
(region, name) and PRESERVES any surcharge/enabled/zone_id an admin already set —
only refreshes the postal_prefixes + region.

Run:  cd /app/backend && python seed_gta_zones.py
"""
import asyncio
import csv
import os
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "bongconnekt_db")
CSV_PATH = os.path.join(os.path.dirname(__file__), "gta_delivery_zones.csv")


def normalize(s: str) -> str:
    return "".join((s or "").split()).upper()


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    groups: "OrderedDict[tuple, list]" = OrderedDict()
    with open(CSV_PATH) as f:
        for row in csv.DictReader(f):
            region = row["Region"].strip()
            muni = row["Municipality"].strip()
            fsa = normalize(row["FSA"])
            groups.setdefault((region, muni), [])
            if fsa and fsa not in groups[(region, muni)]:
                groups[(region, muni)].append(fsa)

    created, updated = 0, 0
    for (region, muni), fsas in groups.items():
        prefixes = sorted(set(fsas))
        existing = await db.pricing_zones.find_one({"region": region, "name": muni})
        if not existing:
            # Fall back to name-only match (older zones without region).
            existing = await db.pricing_zones.find_one({"name": muni, "region": {"$in": [None, ""]}})
        if existing:
            await db.pricing_zones.update_one(
                {"zone_id": existing["zone_id"]},
                {"$set": {"region": region, "name": muni, "postal_prefixes": prefixes,
                          "updated_at": datetime.now(timezone.utc)}},
            )
            updated += 1
        else:
            zid = "pz_" + uuid.uuid4().hex[:10]
            await db.pricing_zones.insert_one({
                "zone_id": zid, "name": muni, "region": region,
                "postal_prefixes": prefixes, "surcharge_cents": 0, "enabled": True,
                "updated_at": datetime.now(timezone.utc),
            })
            created += 1

    total = await db.pricing_zones.count_documents({})
    print(f"Seed complete. created={created} updated={updated} zones_now={total}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
