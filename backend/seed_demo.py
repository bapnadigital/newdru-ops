"""Seed demo data for Newdru. Idempotent — safe to run multiple times."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from models import gen_id, now_iso, ROLE_OWNER
from services.pricing import compute_pricing


SAMPLE_PRODUCTS = [
    {"sku": "ND-T001", "name": "Newdru Classic Tee — Black", "brand": "Newdru", "category": "Apparel",
     "variant": "M", "mrp": 999, "gst_rate": 12, "hsn": "6109", "channel_scope": "offline_only",
     "buy_price": 448, "units_per_carton": 12, "unit_weight_g": 200},
    {"sku": "ND-T002", "name": "Newdru Classic Tee — White", "brand": "Newdru", "category": "Apparel",
     "variant": "L", "mrp": 999, "gst_rate": 12, "hsn": "6109", "channel_scope": "offline_only",
     "buy_price": 448, "units_per_carton": 12, "unit_weight_g": 200},
    {"sku": "ND-J005", "name": "Newdru Slim Fit Jeans", "brand": "Newdru", "category": "Apparel",
     "variant": "32", "mrp": 2499, "gst_rate": 12, "hsn": "6203", "channel_scope": "offline_only",
     "buy_price": 1120, "units_per_carton": 6, "unit_weight_g": 620},
    {"sku": "ND-H010", "name": "Power Your Style Hoodie", "brand": "Newdru", "category": "Apparel",
     "variant": "M", "mrp": 1999, "gst_rate": 12, "hsn": "6110", "channel_scope": "online_offline",
     "barcode": "X001ABCDE1", "buy_price": 896, "units_per_carton": 6, "unit_weight_g": 480},
    {"sku": "ND-C020", "name": "Newdru Canvas Cap", "brand": "Newdru", "category": "Accessories",
     "variant": "One-Size", "mrp": 499, "gst_rate": 12, "hsn": "6505", "channel_scope": "offline_only",
     "buy_price": 224, "units_per_carton": 24, "unit_weight_g": 90},
    {"sku": "ND-S030", "name": "Newdru Snap Backpack", "brand": "Newdru", "category": "Accessories",
     "variant": "20L", "mrp": 3499, "gst_rate": 18, "hsn": "4202", "channel_scope": "online_offline",
     "barcode": "X002FGHIJ2", "buy_price": 1770, "units_per_carton": 4, "unit_weight_g": 900},
]

INITIAL_STOCK = {  # sku -> {location: qty}
    "ND-T001": {"STORE": 24, "BHIWANDI": 180},
    "ND-T002": {"STORE": 18, "BHIWANDI": 160},
    "ND-J005": {"STORE": 8, "BHIWANDI": 60},
    "ND-H010": {"STORE": 12, "BHIWANDI": 80},
    "ND-C020": {"STORE": 3, "BHIWANDI": 200},   # low stock in Store
    "ND-S030": {"STORE": 4, "BHIWANDI": 40},
}


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    admin = await db.users.find_one({"role": ROLE_OWNER})
    now = now_iso()

    for pdata in SAMPLE_PRODUCTS:
        existing = await db.products.find_one({"sku": pdata["sku"]})
        buy = pdata["buy_price"]
        gst = pdata["gst_rate"]
        pr = compute_pricing(buy, gst, None)
        doc = {
            **pdata,
            "sell_price": pr["recommended_sell_price"],
            "status": "active",
            "images": [],
            "barcode_type": "FNSKU" if pdata.get("barcode") else "CODE128",
            "barcode": pdata.get("barcode") or f"NW{pdata['sku'].replace('-','')}"[:14],
            "updated_at": now,
        }
        if existing:
            await db.products.update_one({"sku": pdata["sku"]}, {"$set": doc})
            pid = existing["id"]
        else:
            doc["id"] = gen_id()
            doc["created_at"] = now
            await db.products.insert_one(doc)
            pid = doc["id"]

        for loc, qty in INITIAL_STOCK.get(pdata["sku"], {}).items():
            existing_inv = await db.inventory.find_one({"product_id": pid, "location_code": loc})
            if existing_inv:
                continue
            await db.inventory.insert_one({
                "id": gen_id(), "product_id": pid, "location_code": loc,
                "quantity": qty, "low_stock_threshold": 5, "last_synced_at": now,
            })
            await db.stock_movements.insert_one({
                "id": gen_id(), "product_id": pid, "sku": pdata["sku"],
                "location_code": loc, "movement_type": "seed",
                "quantity_delta": qty, "reason": "initial seed",
                "user_id": admin["id"] if admin else None,
                "user_name": admin["name"] if admin else "system",
                "created_at": now,
            })

    print("Seeded", len(SAMPLE_PRODUCTS), "products with initial stock.")


if __name__ == "__main__":
    asyncio.run(main())
