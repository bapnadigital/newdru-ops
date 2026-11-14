"""One-shot: apply Newdru COGS + newdru.com sell prices from master sheet.

For every product whose shipping_mark = <code>, set:
  - buy_price       = cogs_incl_gst (GST-inclusive landed cost)
  - cogs_per_unit   = cogs_incl_gst (price floor used by POS)
  - sell_price      = newdru_sell_price
  - mrp             = max(existing mrp, newdru_sell_price)
  - placeholder_pricing = False

MAGSHU intentionally skipped (no COGS yet — stays placeholder).
"""
from __future__ import annotations
import asyncio
import csv
import io
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
from motor.motor_asyncio import AsyncIOMotorClient

# Cost prices are confidential and must never be committed to GitHub.
# Pass the master-sheet CSV (columns: code,cogs_incl_gst,newdru_sell_price,sell_below_cogs)
# as the first argument:  python3 scripts/apply_newdru_pricing.py /secure/path/pricing.csv
import sys
CSV_DATA = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else ""
if not CSV_DATA:
    raise SystemExit("Usage: apply_newdru_pricing.py <pricing.csv>  (keep the CSV off GitHub)")


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    reader = csv.DictReader(io.StringIO(CSV_DATA))
    total_updated = 0
    below_cogs_products = []
    per_code_summary = []
    now = datetime.now(timezone.utc).isoformat()
    for row in reader:
        code = row["code"].strip().upper()
        cogs = float(row["cogs_incl_gst"])
        sell = float(row["newdru_sell_price"])
        below = row["sell_below_cogs"].strip().lower() == "true"
        cursor = db.products.find({"shipping_mark": code}, {"_id": 0, "id": 1, "sku": 1, "mrp": 1})
        variants = await cursor.to_list(1000)
        if not variants:
            per_code_summary.append(f"  {code:<12} — no matching products, skipped")
            continue
        for p in variants:
            new_mrp = max(float(p.get("mrp") or 0.0), sell)
            await db.products.update_one({"id": p["id"]}, {"$set": {
                "buy_price": cogs,
                "cogs_per_unit": cogs,
                "sell_price": sell,
                "mrp": new_mrp,
                "placeholder_pricing": False,
                "sell_below_cogs_flag": below,
                "updated_at": now,
            }})
            total_updated += 1
            if below:
                below_cogs_products.append(p["sku"])
        per_code_summary.append(f"  {code:<12} → cogs={cogs:<7} sell={sell:<7} variants={len(variants):<3}{'  ⚠ below-cogs' if below else ''}")

    total_products = await db.products.count_documents({})
    placeholder = await db.products.count_documents({"placeholder_pricing": True})
    real_priced = await db.products.count_documents({"placeholder_pricing": {"$ne": True}, "cogs_per_unit": {"$gt": 0}})

    print()
    print("=" * 70)
    print(" NEWDRU PRICING APPLY — REPORT ")
    print("=" * 70)
    for line in per_code_summary:
        print(line)
    print()
    print(f"Products updated             : {total_updated}")
    print(f"Total products in DB         : {total_products}")
    print(f"Still placeholder_pricing    : {placeholder}   (expect MAGSHU + any without matching code)")
    print(f"With real pricing + COGS     : {real_priced}")
    print(f"Sell price < COGS (flagged)  : {below_cogs_products}")
    c.close()


if __name__ == "__main__":
    asyncio.run(main())
