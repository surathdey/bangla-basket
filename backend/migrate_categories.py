"""Idempotent category restructure for Bangla Basket (Feature 5).

Consolidates scattered cut-type categories into clean "Fresh <Meat>" categories
and backfills Fish subcategories. Safe to re-run — it only matches the OLD
category names, so a second run is a no-op.

Mapping:
  Block Fish        -> Fresh Fish      (subcategory "Block")
  By Weight         -> Fresh Fish      (subcategory "By Weight")
  By Cut            -> Fresh Fish      (subcategory "Cut")
  Cut and Cleaned   -> Fresh Chicken / Fresh Beef / Fresh Goat  (by product title)
  Fresh Meat        -> Fresh Chicken   (Whole Chicken)
  Fresh Vegetable   -> Fresh Vegetable (unchanged, subcategory cleared)
"""
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

FISH_SUBCAT = {
    "Block Fish": "Block",
    "By Weight": "By Weight",
    "By Cut": "Cut",
}


def meat_from_title(title: str) -> str:
    t = (title or "").lower()
    if "chicken" in t:
        return "Fresh Chicken"
    if "beef" in t:
        return "Fresh Beef"
    if "goat" in t or "mutton" in t:
        return "Fresh Goat"
    if "lamb" in t:
        return "Fresh Lamb"
    return "Fresh Meat"


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "bongconnekt_db")]
    changed = 0

    # 1) Fish groups -> Fresh Fish + subcategory
    for old_cat, sub in FISH_SUBCAT.items():
        r = await db.grocery.update_many(
            {"category": old_cat},
            {"$set": {"category": "Fresh Fish", "subcategory": sub}},
        )
        changed += r.modified_count
        print(f"  {old_cat:16s} -> Fresh Fish / {sub}: {r.modified_count}")

    # 2) Cut and Cleaned -> split by title
    async for d in db.grocery.find({"category": "Cut and Cleaned"}, {"item_id": 1, "title": 1}):
        new_cat = meat_from_title(d.get("title", ""))
        await db.grocery.update_one(
            {"item_id": d["item_id"]},
            {"$set": {"category": new_cat, "subcategory": ""}},
        )
        changed += 1
        print(f"  Cut and Cleaned -> {new_cat}: {d.get('title')}")

    # 3) Fresh Meat (single whole chicken) -> Fresh Chicken
    r = await db.grocery.update_many(
        {"category": "Fresh Meat"},
        {"$set": {"category": "Fresh Chicken", "subcategory": ""}},
    )
    changed += r.modified_count
    print(f"  Fresh Meat -> Fresh Chicken: {r.modified_count}")

    # 4) Fresh Vegetable stays; just clear any stray subcategory
    await db.grocery.update_many(
        {"category": "Fresh Vegetable"},
        {"$set": {"subcategory": ""}},
    )

    # Report final state
    pipe = [
        {"$match": {"deleted_at": None}},
        {"$group": {"_id": {"c": "$category", "s": "$subcategory"}, "n": {"$sum": 1}}},
        {"$sort": {"_id.c": 1, "_id.s": 1}},
    ]
    print("\n--- Final categories ---")
    async for row in db.grocery.aggregate(pipe):
        c = row["_id"]["c"]
        s = row["_id"].get("s") or ""
        print(f"  {row['n']:4d}  {c}{(' / ' + s) if s else ''}")
    print(f"\nDone. {changed} products recategorized.")


if __name__ == "__main__":
    asyncio.run(main())
