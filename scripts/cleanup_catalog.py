"""Clean-up:
 1. DELETE pre-existing fake seed products (sku like 'ND-*' with no shipping_mark).
 2. Rename SKUs to `SHIPPING_MARK[-VARIANT]` on all real catalog rows.
 3. Rewrite names to `Product — Variant` style.
 4. Delete synthetic test customers (email ends with @shopify.example).
 5. Print counts + sample SKUs.
"""
from __future__ import annotations
import asyncio, os, re
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


def clean_variant(v):
    if not v: return None
    return re.sub(r"\s+", "-", v.strip().upper()).replace("---", "-")


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]

    print("=" * 70)
    print("  NEWDRU DB CLEAN-UP")
    print("=" * 70)

    total_before = await db.products.count_documents({})
    print(f"Products before: {total_before}")

    # 1. Delete test/fake products (ND-* pattern, no shipping_mark)
    del_query = {"$or": [
        {"sku": {"$regex": r"^ND-[A-Z0-9]+$"}, "shipping_mark": {"$in": [None, ""]}},
        {"sku": {"$regex": r"^ND-[A-Z0-9]+$"}, "shipping_mark": {"$exists": False}},
    ]}
    to_delete = await db.products.find(del_query, {"_id": 0, "id": 1, "sku": 1}).to_list(1000)
    print(f"\nDeleting {len(to_delete)} fake seed products:")
    for p in to_delete:
        print(f"   - {p['sku']}")
    if to_delete:
        pids = [p["id"] for p in to_delete]
        await db.products.delete_many({"id": {"$in": pids}})
        await db.inventory.delete_many({"product_id": {"$in": pids}})
        await db.stock_movements.delete_many({"product_id": {"$in": pids}})

    # 2. Rename SKUs + fix names for the real catalog
    real = await db.products.find(
        {"shipping_mark": {"$nin": [None, ""]}},
        {"_id": 0, "id": 1, "sku": 1, "shipping_mark": 1, "variant": 1, "category": 1, "name": 1}
    ).to_list(1000)

    print(f"\nRenaming SKUs & names for {len(real)} real products:")
    seen_skus = set()
    renamed_count = 0
    now = datetime.now(timezone.utc).isoformat()
    for p in real:
        code = p["shipping_mark"].strip().upper()
        variant = clean_variant(p.get("variant"))
        new_sku = f"{code}-{variant}" if variant else code
        # Ensure uniqueness on collision (shouldn't happen but be safe)
        base = new_sku; i = 2
        while new_sku in seen_skus:
            new_sku = f"{base}-{i}"; i += 1
        seen_skus.add(new_sku)

        # Product display name = Category (product) — Variant
        product_name = (p.get("category") or p.get("name") or code).strip()
        product_name = re.sub(r"\s*—.*$", "", product_name)  # strip any earlier " — VARIANT" suffix
        product_name = re.sub(r"\s*\(.*?\)\s*", " ", product_name).strip()
        product_name = re.sub(r"\s{2,}", " ", product_name)
        display = f"{product_name} — {variant.title().replace('-', ' ')}" if variant else product_name

        patch = {"sku": new_sku, "name": display, "updated_at": now}
        # For products where barcode was the old ugly SKU (no FNSKU), update to new SKU
        old_prod = await db.products.find_one({"id": p["id"]}, {"_id": 0, "barcode": 1, "barcode_type": 1})
        if (old_prod or {}).get("barcode_type") != "FNSKU":
            patch["barcode"] = new_sku
        await db.products.update_one({"id": p["id"]}, {"$set": patch})
        renamed_count += 1
        if renamed_count <= 8:
            print(f"   {p['sku']:<48}  →  {new_sku:<20}  {display}")

    if renamed_count > 8:
        print(f"   … {renamed_count - 8} more")

    # 3. Delete synthetic test customers
    del_cust = await db.customers.delete_many(
        {"email": {"$regex": r"@shopify\.example$"}}
    )
    print(f"\nDeleted synthetic test customers: {del_cust.deleted_count}")

    # ------- Report -------
    total_after = await db.products.count_documents({})
    real_after = await db.products.count_documents({"shipping_mark": {"$nin": [None, ""]}})
    orphans = await db.products.count_documents({"shipping_mark": {"$in": [None, ""]}})
    customers_now = await db.customers.count_documents({})

    print()
    print("-" * 70)
    print(f"Products after cleanup   : {total_after}")
    print(f"  ↳ with shipping_mark   : {real_after}")
    print(f"  ↳ orphans (should = 0) : {orphans}")
    print(f"Customers now            : {customers_now}")

    # Show a few sample clean SKUs
    print(f"\nSample clean SKUs:")
    sample = await db.products.find(
        {}, {"_id": 0, "sku": 1, "name": 1, "shipping_mark": 1}
    ).sort("sku", 1).limit(12).to_list(12)
    for p in sample:
        print(f"   {p['sku']:<22}  {p['name']}")

    c.close()


if __name__ == "__main__":
    asyncio.run(main())
