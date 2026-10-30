"""Import Master Menu + Weekly Package from menu_export.json.

- Downloads each master item image and re-hosts it under this project's own
  storage (/app/backend/uploads/menu -> served at /api/uploads/menu/...).
- Rebuilds db.master_menu (60 items) and db.weekly_menus (1 weekly plan with a
  composition-priced package).  Idempotent: clears and re-imports.

Run: python import_menu.py /path/to/menu_export.json
"""
import asyncio, os, sys, json, uuid, urllib.request
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/tmp/menu_export.json"
UPLOADS = Path("/app/backend/uploads/menu")
UPLOADS.mkdir(parents=True, exist_ok=True)

VEG_MAP = {"vegetarian": "vegetarian", "eggitarian": "eggitarian",
           "nonvegetarian": "non-vegetarian", "non-vegetarian": "non-vegetarian"}


def rehost(url: str) -> str:
    """Download image into our uploads/menu; return local /api/uploads path. Falls back to source URL on failure."""
    if not url:
        return ""
    try:
        ext = os.path.splitext(url.split("?")[0])[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            ext = ".png"
        name = f"mi_{uuid.uuid4().hex[:16]}{ext}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        (UPLOADS / name).write_bytes(data)
        return f"/api/uploads/menu/{name}"
    except Exception as e:
        print(f"  ! image download failed ({e}) — keeping source url")
        return url


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    data = json.load(open(SRC))
    mm = data["master_menu"]
    wms = data["weekly_menus"]

    # ---- Master items ----
    await db.master_menu.delete_many({})
    name_to_id = {}
    now = datetime.now(timezone.utc)
    docs = []
    for i, m in enumerate(mm):
        item_id = f"mi_{uuid.uuid4().hex[:10]}"
        img = rehost(m.get("image_url", ""))
        docs.append({
            "item_id": item_id,
            "name": m["name"],
            "short_description": m.get("short_description", ""),
            "full_description": m.get("full_description", ""),
            "category": m.get("category", "main"),
            "cuisine": m.get("cuisine", "bengali"),
            "default_price_cents": int(round(float(m.get("price_cad", 0)) * 100)),
            "cost_price_cents": 0,
            "image_url": img,
            "extra_images": [],
            "veg_type": VEG_MAP.get(str(m.get("veg_type", "")).lower(), "vegetarian"),
            "spice_level": m.get("spice_level", "medium"),
            "allergens": m.get("allergens", []),
            "is_active": bool(m.get("is_active", True)),
            "always_available": bool(m.get("always_available", False)),
            "prep_notes": "", "kitchen_notes": "", "display_order": i,
            "created_at": now, "updated_at": now,
        })
        name_to_id[m["name"]] = item_id
        print(f"  [{i+1}/{len(mm)}] {m['name']} -> {img[:48]}")
    await db.master_menu.insert_many(docs)

    def ids(names):
        return [name_to_id[n] for n in names if n in name_to_id]

    # ---- Weekly menus ----
    await db.weekly_menus.delete_many({})
    for w in wms:
        ws = w["week_start"]
        we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
        visible = set(w.get("alacarte_visible_items", []))
        # lines: one per master item, visibility from alacarte_visible_items
        lines = []
        for i, d in enumerate(docs):
            lines.append({
                "line_id": f"wl_{uuid.uuid4().hex[:10]}",
                "master_item_id": d["item_id"],
                "price_override_cents": None,
                "availability": "available",
                "stock_limit": None, "stock_used": 0,
                "is_featured": False, "display_order": i,
                "is_visible": d["name"] in visible,
            })
        pkg = None
        p = w.get("package") or {}
        comp_ids = ids(w.get("complimentary_items", []))
        if w.get("package_enabled") and p:
            surch = {}
            for nm, cad in (p.get("item_surcharges_cad") or {}).items():
                if nm in name_to_id:
                    surch[name_to_id[nm]] = int(round(float(cad) * 100))
            elig = p.get("eligible_items", [])
            eligible_ids = [d["item_id"] for d in docs] if elig == "ALL" else ids(elig)
            pkg = {
                "package_id": f"wpkg_{uuid.uuid4().hex[:10]}",
                "name": p.get("name", "Weekly Combo"),
                "description": p.get("description", ""),
                "price_cents": int(round(float(p.get("flat_price_cad", 0)) * 100)),
                "pick_count": int(p.get("pick_count", 3)),
                "eligible_master_ids": eligible_ids,
                "item_surcharges_cents": surch,
                "image_url": "",
                "pricing_mode": p.get("pricing_mode", "flat"),
                "veg_price_cents": int(round(float(p.get("veg_price_cad", 0)) * 100)),
                "mixed_price_cents": int(round(float(p.get("mixed_price_cad", 0)) * 100)),
                "nonveg_price_cents": int(round(float(p.get("nonveg_price_cad", 0)) * 100)),
                "complimentary_master_ids": comp_ids,
            }
        await db.weekly_menus.insert_one({
            "menu_id": f"menu_{uuid.uuid4().hex[:10]}",
            "week_start": ws, "week_end": we, "title": w.get("title", "Weekly Menu"),
            "description": "", "banner_image_url": "",
            "items": [], "lines": lines,
            "complimentary_master_ids": comp_ids,
            "published": True, "status": "published",
            "alacarte_enabled": bool(w.get("alacarte_enabled", False)),
            "package_enabled": bool(w.get("package_enabled", False)),
            "package": pkg,
            "created_at": now,
        })

    # ---- Confirm ----
    mcount = await db.master_menu.count_documents({})
    wcount = await db.weekly_menus.count_documents({})
    wm0 = await db.weekly_menus.find_one({}, {"_id": 0})
    pk = wm0.get("package") or {}
    id_to_name = {v: k for k, v in name_to_id.items()}
    print("\n===== IMPORT COMPLETE =====")
    print(f"master_menu items : {mcount}")
    print(f"weekly_menus      : {wcount}")
    print(f"weekly plan title : {wm0.get('title')}  (week_start {wm0.get('week_start')})")
    print(f"package           : {pk.get('name')}  pick {pk.get('pick_count')}  mode {pk.get('pricing_mode')}")
    print(f"  veg     : ${pk.get('veg_price_cents',0)/100:.2f}")
    print(f"  mixed   : ${pk.get('mixed_price_cents',0)/100:.2f}")
    print(f"  non-veg : ${pk.get('nonveg_price_cents',0)/100:.2f}")
    print(f"  eligible items    : {len(pk.get('eligible_master_ids', []))}")
    print(f"  complimentary     : {[id_to_name.get(x) for x in pk.get('complimentary_master_ids', [])]}")
    imgok = await db.master_menu.count_documents({"image_url": {"$regex": "^/api/uploads/menu/"}})
    print(f"  images re-hosted  : {imgok}/{mcount}")


if __name__ == "__main__":
    asyncio.run(main())
