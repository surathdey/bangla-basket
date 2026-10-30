"""One-time grocery catalog seed. Idempotent by source_id.
Run: python seed_grocery.py
"""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
from grocery_import import build_grocery_docs


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await db.grocery.create_index("item_id", unique=True)
    await db.grocery.create_index("source_id")
    await db.grocery.create_index("category")
    docs = build_grocery_docs()
    print("fetched+transformed:", len(docs))
    ins = upd = 0
    for d in docs:
        d["updated_at"] = datetime.now(timezone.utc)
        d.setdefault("deleted_at", None)
        existing = await db.grocery.find_one({"source_id": d["source_id"]}, {"_id": 0, "item_id": 1, "created_at": 1})
        if existing:
            d["item_id"] = existing["item_id"]
            d["created_at"] = existing.get("created_at", d["created_at"])
            await db.grocery.update_one({"source_id": d["source_id"]}, {"$set": d})
            upd += 1
        else:
            await db.grocery.insert_one(d)
            ins += 1
    total = await db.grocery.count_documents({"deleted_at": None})
    from collections import Counter
    cats = await db.grocery.aggregate([
        {"$match": {"deleted_at": None}},
        {"$group": {"_id": "$category", "c": {"$sum": 1}}},
        {"$sort": {"c": -1}},
    ]).to_list(100)
    print(f"inserted={ins} updated={upd} total_active={total}")
    for c in cats:
        print(f"  {c['c']:4d}  {c['_id']}")


if __name__ == "__main__":
    asyncio.run(main())
