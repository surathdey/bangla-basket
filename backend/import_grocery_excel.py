"""Rebuild the grocery catalog from the tenant's uploaded catalogue Excel.

- Groups rows by Product ID -> one product with a `variants` list.
- Joins product images/descriptions from the existing db.grocery (matched by
  source_id == Product ID) so we keep the photos already imported.
- Preserves meal-plan / combo products from the previous import under a
  "Meal Plans" category (marked featured) so the storefront's Meal Plan tile
  and Best Sellers row have content.
- Marks featured items for the homepage "Best Sellers / New Items" row.

Run: python import_grocery_excel.py /path/to/catalogue.xlsx
"""
import asyncio
import os
import sys
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import openpyxl
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

XLSX = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cat.xlsx"
MEAL_KEYWORDS = ["meal plan", "weekly", "combo", "kachi", "polao", "biryani",
                 "people)", "person)", "feast", "platter", "thali"]


def cents(x):
    try:
        return int(round(float(x) * 100))
    except Exception:
        return 0


def to_source_id(v):
    try:
        return str(int(float(v)))
    except Exception:
        return str(v or "").strip()


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    # 1) image/description map from the current catalog (before rebuild)
    img_map = {}
    meal_docs = []
    async for d in db.grocery.find({}, {"_id": 0}):
        sid = str(d.get("source_id") or "")
        if sid and d.get("image_url"):
            img_map[sid] = {
                "image_url": d.get("image_url", ""),
                "images": d.get("images", []),
                "description": d.get("description", ""),
            }
        title = (d.get("title") or "").lower()
        if any(k in title for k in MEAL_KEYWORDS):
            meal_docs.append(d)
    print(f"image map entries: {len(img_map)}  |  meal-plan candidates: {len(meal_docs)}")

    # 2) parse Excel -> grouped products
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))[1:]
    groups = defaultdict(list)
    order = []
    for r in rows:
        pid = to_source_id(r[14])
        if pid not in groups:
            order.append(pid)
        groups[pid].append(r)

    docs = []
    for pid in order:
        vs = groups[pid]
        first = vs[0]
        title = str(first[2] or "").strip()
        if not title:
            continue
        category = str(first[0] or "Grocery & Pantry").strip()
        all_cats = str(first[1] or "").strip()
        vendor = str(first[11] or "").strip()
        purl = str(first[17] or "").strip()
        variants = []
        prices = []
        on_sale = False
        for r in vs:
            vtitle = str(r[3] or "Standard").strip() or "Standard"
            p = cents(r[4])
            comp = cents(r[5])
            avail = str(r[9] or "").strip().lower() == "yes"
            if str(r[8] or "").strip().lower() == "yes":
                on_sale = True
            variants.append({
                "variant_id": to_source_id(r[15]),
                "title": vtitle,
                "price_cents": p,
                "compare_at_cents": comp,
                "available": avail,
                "sku": str(r[12] or "").strip(),
                "weight_g": int(r[13]) if r[13] else 0,
            })
            if p > 0:
                prices.append((avail, p, comp))
        has_variants = len(variants) > 1 or (variants and variants[0]["title"] != "Standard")
        # default price: cheapest available, else cheapest
        avail_prices = [x for x in prices if x[0]]
        pick = min(avail_prices or prices, key=lambda x: x[1]) if prices else (True, 0, 0)
        joined = img_map.get(pid, {})
        docs.append({
            "item_id": f"gr_{uuid.uuid4().hex[:12]}",
            "title": title,
            "handle": "",
            "description": joined.get("description", ""),
            "category": category,
            "all_categories": all_cats,
            "price_cents": pick[1],
            "compare_at_cents": pick[2],
            "unit": "",
            "image_url": joined.get("image_url", ""),
            "images": joined.get("images", []),
            "vendor": vendor,
            "tags": [],
            "variants": variants,
            "has_variants": bool(has_variants),
            "on_sale": on_sale,
            "in_stock": any(v["available"] for v in variants),
            "is_active": True,
            "is_featured": False,
            "sort_order": 0,
            "source_id": pid,
            "product_url": purl,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "deleted_at": None,
        })

    # 3) meal plans from previous import (keep them, category "Meal Plans", featured)
    meal_out = []
    seen_titles = set()
    for d in meal_docs:
        t = (d.get("title") or "").strip()
        if not t or t.lower() in seen_titles:
            continue
        seen_titles.add(t.lower())
        meal_out.append({
            "item_id": d.get("item_id") or f"gr_{uuid.uuid4().hex[:12]}",
            "title": t,
            "handle": d.get("handle", ""),
            "description": d.get("description", ""),
            "category": "Meal Plans",
            "all_categories": "Meal Plans",
            "price_cents": d.get("price_cents", 0),
            "compare_at_cents": d.get("compare_at_cents", 0),
            "unit": d.get("unit", ""),
            "image_url": d.get("image_url", ""),
            "images": d.get("images", []),
            "vendor": d.get("vendor", ""),
            "tags": d.get("tags", []),
            "variants": [],
            "has_variants": False,
            "on_sale": d.get("compare_at_cents", 0) > d.get("price_cents", 0),
            "in_stock": True,
            "is_active": True,
            "is_featured": True,
            "sort_order": 0,
            "source_id": d.get("source_id", ""),
            "product_url": "",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "deleted_at": None,
        })

    # 4) featured best sellers: meal plans + first on-sale grocery items
    onsale = [d for d in docs if d["on_sale"] and d["image_url"]][:10]
    for d in onsale:
        d["is_featured"] = True

    all_docs = docs + meal_out
    # 5) rebuild collection (catalog data, not user data)
    await db.grocery.delete_many({})
    if all_docs:
        # insert in batches
        for i in range(0, len(all_docs), 500):
            await db.grocery.insert_many(all_docs[i:i + 500])
    await db.grocery.create_index("item_id", unique=True)
    await db.grocery.create_index("source_id")
    await db.grocery.create_index("category")

    total = await db.grocery.count_documents({"deleted_at": None})
    withimg = await db.grocery.count_documents({"deleted_at": None, "image_url": {"$ne": ""}})
    feat = await db.grocery.count_documents({"is_featured": True})
    multi = await db.grocery.count_documents({"has_variants": True})
    cats = await db.grocery.aggregate([
        {"$match": {"deleted_at": None}},
        {"$group": {"_id": "$category", "c": {"$sum": 1}}},
        {"$sort": {"c": -1}},
    ]).to_list(100)
    print(f"\nTOTAL={total}  with_image={withimg}  featured={feat}  variant_products={multi}")
    print(f"grocery products from excel={len(docs)}  meal_plans={len(meal_out)}")
    for c in cats:
        print(f"  {c['c']:5d}  {c['_id']}")


if __name__ == "__main__":
    asyncio.run(main())
