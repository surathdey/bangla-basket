"""Migrate grocery images off ephemeral container disk into Emergent Object
Storage (persistent + shared across instances/environments), and rewrite DB
image URLs from /api/uploads/grocery/* to /api/files/bongconnekt/grocery/*.

Idempotent: re-running only touches docs that still reference /api/uploads/.
"""
import asyncio
import os
import re
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()
import storage_client as _obj  # noqa: E402

UPLOADS = Path("/app/backend/uploads")
CT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
RX = re.compile(r"/api/uploads/grocery/([A-Za-z0-9_.\-]+)")


def migrate_url(url, uploaded, missing):
    if not isinstance(url, str):
        return url
    m = RX.search(url)
    if not m:
        return url
    name = m.group(1)
    src = UPLOADS / "grocery" / name
    path = f"{_obj.APP_NAME}/grocery/{name}"
    if name not in uploaded:
        if src.exists():
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else "jpg"
            _obj.put_object(path, src.read_bytes(), CT.get(ext, "image/jpeg"))
            uploaded.add(name)
        else:
            missing.add(name)
            return url
    return f"/api/files/{path}"


async def main():
    _obj.init_storage()
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "bongconnekt_db")]
    uploaded, missing = set(), set()
    changed = 0

    cursor = db.grocery.find({"$or": [
        {"image_url": {"$regex": "/api/uploads/grocery/"}},
        {"images": {"$regex": "/api/uploads/grocery/"}},
        {"variants.image_url": {"$regex": "/api/uploads/grocery/"}},
    ]})
    async for d in cursor:
        upd = {}
        if isinstance(d.get("image_url"), str):
            nu = migrate_url(d["image_url"], uploaded, missing)
            if nu != d["image_url"]:
                upd["image_url"] = nu
        if isinstance(d.get("images"), list):
            new_imgs = [migrate_url(u, uploaded, missing) for u in d["images"]]
            if new_imgs != d["images"]:
                upd["images"] = new_imgs
        if isinstance(d.get("variants"), list):
            vs = d["variants"]
            touched = False
            for v in vs:
                if isinstance(v, dict) and isinstance(v.get("image_url"), str):
                    nv = migrate_url(v["image_url"], uploaded, missing)
                    if nv != v["image_url"]:
                        v["image_url"] = nv
                        touched = True
            if touched:
                upd["variants"] = vs
        if upd:
            await db.grocery.update_one({"item_id": d["item_id"]}, {"$set": upd})
            changed += 1

    print(f"docs updated: {changed}")
    print(f"files uploaded to object storage: {len(uploaded)}")
    if missing:
        print(f"WARNING missing local files (left unchanged): {len(missing)}")
        for mm in list(missing)[:20]:
            print("  missing:", mm)
    remaining = await db.grocery.count_documents({"image_url": {"$regex": "/api/uploads/grocery/"}})
    print(f"grocery docs still on /api/uploads image_url: {remaining}")


if __name__ == "__main__":
    asyncio.run(main())
