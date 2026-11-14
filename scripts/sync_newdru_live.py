"""Sync newdru.com LIVE selling prices + product images per shipping_mark.

- Preserves cogs_per_unit / buy_price from the earlier COGS import.
- Overwrites sell_price with the live newdru.com price.
- Overwrites mrp with max(existing mrp, live price).
- Sets images = [image_url] on every variant of that code.
- Clears `sell_below_cogs_flag` (recomputed from actual values below).
"""
from __future__ import annotations
import asyncio, csv, io, os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

CSV_DATA = """code,newdru_live_price,image_url
CASCAS,2495,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/MainImage_cda8c48e-ca10-4dde-8caf-c7eabbccffe8.png
SHUNAS,499,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/1_00a24c1b-1bde-48ec-b756-f859e06d8235.png
CAMPING,4887,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/CampGuard_Pro_1.jpg
BABIT,2195,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Main_Image_Black.png
BARCAR,3498,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/DriveSync_Pro_1.jpg
AMTER,3495,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/EcoGuard_Pro_1.jpg
SHUEYE,2995,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/artboard1.jpg
SHUVER,2999,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Rechargeable_Screwdriver_Kit-01.jpg
SHUTOVE,2097,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/71Ciq_GIJwL._SL1500.jpg
SUVICHAR,2497,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/CarMountChargerListing-01.jpg
NEWDRU,1950,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/4_2.jpg
SHUMASK,195,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Glow_Skin_Pro_1.jpg
COSHUBH,2297,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/MainGrey.png
PRISH,2995,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/MainImage_1463ce0b-e047-4ae0-aa82-16edc3e6af0a.png
SHUTRI,2197,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/1_72c9323e-d32d-472a-a701-062902e72026.png
MOSHU,2374,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/MosqGuard_Pro_1.jpg
SHUAL3,5495,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Listing-01.jpg
SUBH,14995,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/NewDru4k-2.png
SHUBOX,4999,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Boxing_Listing-01.jpg
SHUFA,2295,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Main_Brown.png
SHULAMP,990,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/NightBeam_Pro_1.jpg
PICPIC,1495,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/PicklePlay_Pro_1.jpg
SHUBALL,2497,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/HeroImage_ac0c454f-9ace-4cfe-b5d8-bce91ec8711a.png
BAPNA,1724,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/7xairpurifieramazonlistingimages-02.jpg
TOVISH,4999,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Newdru-Double-Burner-3.webp
SHURED3,11995,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/RadianceTherm_Pro_1.jpg
SHUAHUB,2374,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/MainImage.png
ROOROO,2995,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/01.png
ARMSH,1410,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Safe_Alert_Pro_1.jpg
KIDSHU,1285,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/mAIN_iMAGE.png
SHUHAS,499,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/black0001.png
SHUBRACE,999,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/Back_Support_Belt_1.jpg
KNIKNISH2,799,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/01.jpg
TRIPTRIP,2295,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/TripGrip_Pro_1.jpg
SHUTER,2870,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/1stImage.png
RANGER,4999,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/hf_20260704_212256_858c1998-4205-40cc-b9a6-45382c6b9f4d.png
MAGSHU,1490,https://cdn.shopify.com/s/files/1/0753/2675/0754/files/1_021f45ec-86d7-4ca8-9932-65e90541bce1.png
"""


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    reader = csv.DictReader(io.StringIO(CSV_DATA))
    price_updated, image_updated = 0, 0
    per_code = []
    codes_with_no_products = []
    for row in reader:
        code = row["code"].strip().upper()
        price = float(row["newdru_live_price"])
        img = row["image_url"].strip()
        variants = await db.products.find({"shipping_mark": code}, {"_id": 0, "id": 1, "mrp": 1}).to_list(1000)
        if not variants:
            codes_with_no_products.append(code); continue
        for p in variants:
            new_mrp = max(float(p.get("mrp") or 0.0), price)
            await db.products.update_one({"id": p["id"]}, {"$set": {
                "sell_price": price,
                "mrp": new_mrp,
                "images": [img],
                "sell_below_cogs_flag": False,
                "placeholder_pricing": False,
                "updated_at": now,
            }})
            price_updated += 1
            image_updated += 1
        per_code.append(f"  {code:<12} live=₹{price:<7.0f} variants={len(variants)}")

    # Now compute actual below-COGS from live values
    prods = await db.products.find(
        {"cogs_per_unit": {"$gt": 0}, "sell_price": {"$gt": 0}},
        {"_id": 0, "sku": 1, "cogs_per_unit": 1, "sell_price": 1}
    ).to_list(1000)
    still_below = [p for p in prods if p["sell_price"] < p["cogs_per_unit"]]

    total_products = await db.products.count_documents({})
    with_image = await db.products.count_documents({"images.0": {"$exists": True}})
    with_price = await db.products.count_documents({"sell_price": {"$gt": 0}, "cogs_per_unit": {"$gt": 0}})

    print("=" * 70)
    print(" NEWDRU LIVE PRICE + IMAGE SYNC — REPORT ")
    print("=" * 70)
    for l in per_code:
        print(l)
    if codes_with_no_products:
        print(f"\n(No matching products for codes: {codes_with_no_products})")
    print()
    print(f"Products updated (price)     : {price_updated}")
    print(f"Products updated (image)     : {image_updated}")
    print(f"Total products in DB         : {total_products}")
    print(f"Products with an image       : {with_image}")
    print(f"Products with price + COGS   : {with_price}")
    print(f"Sell price < COGS after sync : {len(still_below)}  {[p['sku'] for p in still_below]}")
    c.close()


if __name__ == "__main__":
    asyncio.run(main())
