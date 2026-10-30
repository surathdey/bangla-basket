"""One-off: load the 14th Sept Weekly Meal Plan from the poster.

Adds any missing dishes to the Master Menu, then sets this week's plan
(eligible picks, Mutton Qorma +$5 surcharge, complimentary Bhorta + Dal).
Idempotent: matches master items by exact name so re-runs don't duplicate.
"""
import asyncio, os, uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).with_name(".env"))
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
NOW = datetime.now(timezone.utc)
MENU_ID = "menu_dc0f9a8185"


async def ensure_master(name, veg_type, category, price_cents):
    """Return item_id for `name`, creating the master item if missing."""
    doc = await db.master_menu.find_one({"name": name}, {"_id": 0, "item_id": 1})
    if doc:
        return doc["item_id"]
    item_id = f"mi_{uuid.uuid4().hex[:10]}"
    await db.master_menu.insert_one({
        "item_id": item_id, "name": name, "short_description": "", "full_description": "",
        "category": category, "cuisine": "bengali", "default_price_cents": price_cents,
        "cost_price_cents": 0, "image_url": "", "extra_images": [], "veg_type": veg_type,
        "spice_level": "medium", "allergens": [], "is_active": True, "always_available": False,
        "prep_notes": "", "kitchen_notes": "", "display_order": 0,
        "created_at": NOW, "updated_at": NOW,
    })
    print(f"  + added master: {name}  ({item_id})")
    return item_id


async def main():
    # --- Veg picks (in poster order) ---
    chanar   = await ensure_master("Chanar Dalna", "vegetarian", "main-veg", 1599)
    niramish = await ensure_master("Niramis Badhakopi", "vegetarian", "main-veg", 1599)
    palong   = await ensure_master("Palong Ghonto", "vegetarian", "main-veg", 1599)
    begun    = await ensure_master("Begun Basanti Shorshey Diye", "vegetarian", "main-veg", 1599)
    fulkopi  = await ensure_master("Fulkopi Aloo Dalna", "vegetarian", "main-veg", 1599)

    # --- Non-veg picks (in poster order) ---
    doi_rui  = await ensure_master("Doi Rui", "non-vegetarian", "main-non-veg", 1699)
    topshey  = await ensure_master("Tomato diye Topshey Mach Jhal", "non-vegetarian", "main-non-veg", 1699)
    chicken  = await ensure_master("Chicken Aloo Jhol", "non-vegetarian", "main-non-veg", 1699)
    hansher  = await ensure_master("Desi Hansher Dim Kosha Aloo Diye", "eggitarian", "main-non-veg", 1699)
    katla    = await ensure_master("Katla Mach er Muri Ghonto", "non-vegetarian", "main-non-veg", 1699)
    mutton   = await ensure_master("Mutton Qorma", "non-vegetarian", "main-non-veg", 1999)

    # --- Complimentary ---
    bhorta   = await ensure_master("Bhorta of the Week", "vegetarian", "side", 0)
    dal      = await ensure_master("Dal of the Week", "vegetarian", "side", 0)

    eligible = [chanar, niramish, palong, begun, fulkopi,
                doi_rui, topshey, chicken, hansher, katla, mutton]
    complimentary = [bhorta, dal]

    wm = await db.weekly_menus.find_one({"menu_id": MENU_ID})
    if not wm:
        raise SystemExit(f"weekly menu {MENU_ID} not found")

    # Rebuild lines: keep every existing line but hide all, then turn ON the picks.
    lines = wm.get("lines") or []
    by_master = {ln["master_item_id"]: ln for ln in lines}
    for ln in lines:
        ln["is_visible"] = False
    order = 0
    for mid in eligible:
        ln = by_master.get(mid)
        if ln:
            ln["is_visible"] = True
            ln["availability"] = "available"
            ln["display_order"] = order
        else:
            lines.append({
                "line_id": f"wl_{uuid.uuid4().hex[:10]}", "master_item_id": mid,
                "price_override_cents": None, "availability": "available",
                "stock_limit": None, "stock_used": 0, "is_featured": False,
                "display_order": order, "is_visible": True,
            })
        order += 1

    pkg = wm.get("package") or {}
    pkg.update({
        "name": "This Week's Combo",
        "description": "Choose one plan: 5 Veg ($64.99), 3 Veg + 3 Non-Veg ($69.99), or 5 Non-Veg ($79.99). Max 2 of any dish.",
        "pricing_mode": "composition",
        "pick_count": 5,
        "veg_price_cents": 6499,
        "mixed_price_cents": 6999,
        "nonveg_price_cents": 7999,
        # Fixed-composition plans: 5 veg / (3 veg + 3 non-veg) / 5 non-veg; max 2 of a dish.
        "veg_pick_count": 5,
        "nonveg_pick_count": 5,
        "mixed_veg_count": 3,
        "mixed_nonveg_count": 3,
        "max_per_dish": 2,
        "eligible_master_ids": eligible,
        "item_surcharges_cents": {mutton: 500},  # Mutton Qorma +$5
        "complimentary_master_ids": complimentary,
    })

    await db.weekly_menus.update_one({"menu_id": MENU_ID}, {"$set": {
        "title": "Weekly Meal Plan — 14th Sept",
        "lines": lines,
        "package": pkg,
        "package_enabled": True,
        "complimentary_master_ids": complimentary,
        "updated_at": NOW,
    }})

    print(f"\nUpdated {MENU_ID}: {len(eligible)} eligible picks, "
          f"surcharge Mutton Qorma +$5, complimentary Bhorta + Dal.")


asyncio.run(main())
