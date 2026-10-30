"""Idempotent seed for the Thali Party Order module (Feature 5).

Creates the Veg and Non-Veg thali packages if they don't already exist.
Admin can edit every price / inclusion / minimum afterward.
"""
import asyncio
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

VEG = {
    "package_id": "th_veg_default",
    "name": "Veg Thali",
    "thali_type": "veg",
    "description": "A complete vegetarian party thali — rice, bread, dal, veg curries and a sweet.",
    "per_person_price_cents": 999,
    "protein_options": [],
    "includes": [
        "1 Rice",
        "1 Roti / 2 Luchi-Poori",
        "1 Dal",
        "2 Veg curries",
        "Sweet",
    ],
    "min_guests": 25,
    "image_url": "",
    "is_active": True,
    "sort_order": 0,
}

NON_VEG = {
    "package_id": "th_nonveg_default",
    "name": "Non-Veg Thali",
    "thali_type": "non_veg",
    "description": "A hearty non-veg party thali — pick your protein; served with rice, bread, dal, veg curry and a sweet.",
    "per_person_price_cents": 1199,  # fallback; protein price applies
    "protein_options": [
        {"option_id": "tp_mutton", "name": "Mutton", "price_cents": 1399},
        {"option_id": "tp_chicken", "name": "Chicken", "price_cents": 1199},
        {"option_id": "tp_fish", "name": "Fish", "price_cents": 1199},
    ],
    "includes": [
        "1 Rice",
        "1 Roti / 2 Luchi-Poori",
        "1 Dal",
        "1 Veg curry",
        "1 Mutton/Chicken/Fish curry",
        "Sweet",
    ],
    "min_guests": 25,
    "image_url": "",
    "is_active": True,
    "sort_order": 1,
}


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "bongconnekt_db")]
    for pkg in (VEG, NON_VEG):
        existing = await db.thali_packages.find_one({"package_id": pkg["package_id"]})
        if existing:
            print(f"  exists: {pkg['name']}")
            continue
        doc = {**pkg, "created_at": datetime.now(timezone.utc)}
        await db.thali_packages.insert_one(doc)
        print(f"  seeded: {pkg['name']}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
