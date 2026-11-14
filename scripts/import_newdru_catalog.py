"""One-shot Newdru catalog import (49 rows) — the definitive product master.

Matching rule:
  1. Try shipping_mark = code  AND  variant = variant (None-matches-None)
  2. Fallback: name contains code AND (variant match or both blank)
  3. Otherwise: create new SKU

Applies ONLY packaging + Amazon fields. Never touches pricing.
Sets stock:
  - BHIWANDI = warehouse_qty_rrc
  - AMAZON_FC = amazon_fba_sellable (only when non-blank)
Writes stock_movements ledger rows for changes.

Run:  python3 /app/scripts/import_newdru_catalog.py
"""
from __future__ import annotations
import asyncio
import csv
import io
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

import os
from motor.motor_asyncio import AsyncIOMotorClient


CSV_DATA = """match_name_original,code,product,variant,warehouse_qty_rrc,amazon_fnsku,amazon_asin,amazon_msku,amazon_fba_sellable,units_per_carton,carton_l_cm,carton_w_cm,carton_h_cm,carton_weight_kg,notes
AMTER – Pollution Detection Meter – 128 pcs/CTN_20 KG,AMTER,Pollution Detection Meter,,896,,,,,128,64,48,42,29.0,Not in FBA report
ARMSH – Safety Alarm BLACK,ARMSH,Safety Alarm,BLACK,400,X002A9R93N,B0DZ2TBK26,SafeAlert Pro-Alarm,788,200,40.7,35.2,21.2,8.85,ok
ARMSH – Safety Alarm BLUE,ARMSH,Safety Alarm,BLUE,200,X002EWCDE1,B0FSKV5JT9,SafeAlert Pro-Alarm-Blue,,200,40.7,35.2,21.2,8.85,ok
ARMSH – Safety Alarm PINK,ARMSH,Safety Alarm,PINK,400,,,,,200,40.7,35.2,21.2,8.85,confirm amazon colour
ARMSH – Safety Alarm WHITE,ARMSH,Safety Alarm,WHITE,200,X002EWD0JD,B0FSKWBQQQ,SafeAlert Pro-Alarm-White,,200,40.7,35.2,21.2,8.85,ok
BABIT Electric Bidet WHITE,BABIT,Electric Bidet,WHITE,27,,,,8,50,40,36,36,11.0,confirm amazon colour
BAPNA Portable Air Purifier BLACK,BAPNA,Portable Air Purifier,BLACK,1013,X0028ISEL7,B0DWXKFZH6,BAPNA-PureVibe_Air Purifier-Black,4,100,36.5,36,38.5,8.6,ok
BAPNA Portable Air Purifier RED,BAPNA,Portable Air Purifier,RED,54,,,,,100,36.5,36,38.5,8.6,confirm amazon colour
BARCAR Wireless Car Play,BARCAR,Wireless Car Play Adapter,,180,X0029B6CZD,B0F197DM5F,BARCAR_DriveSync-Adapter,6,180,30.5,30,41,0.02,ok
BUTANE GAS,BUTANE,Butane Gas Canister,,4000,,,,,,,,,,packaging TBD
CAMPING TENT BLUE,CAMPING,Camping Tent,BLUE,100,X0028ZT3BP,B0DZ2PX7Q8,CampGuard Pro-Tent,238,25,77,38,38,34.03,ok
CAMPING TENT OLIVE,CAMPING,Camping Tent,OLIVE GREEN,75,X002ANL3CR,B0F6YR9GHG,CampGuard Pro Tent_Silver-Olive,,25,77,38,38,34.03,ok
CASCAS Car Air Purifier GOLD,CASCAS,Car Air Purifier,GOLD,396,X0028GIBRL,B0DWN61MSL,CASCAS_AirPure Elite,120,60,56,34,63,16.3,ok
CASCAS Car Air Purifier SILVER,CASCAS,Car Air Purifier,SILVER,263,X0028GIBRL,B0DWN61MSL,CASCAS_AirPure Elite,,60,56,34,63,16.3,ok
COSHUBH Coffee Bean Grinder GRAY,COSHUBH,Coffee Bean Grinder,GRAY,240,X0028HVHNZ,B0DWST2X7N,COSHUBH_GrindMaster-Grey,228,48,52,35,50.5,0.26,ok
COSHUBH Coffee Bean Grinder WHITE,COSHUBH,Coffee Bean Grinder,WHITE,232,X0028I2XA5,B0DWSXRSWC,COSHUBH_GrindMaster-White,,48,52,35,50.5,0.26,ok
KIDSHU Wooden Drawing Board,KIDSHU,Wooden Drawing Board,,1070,X00291LRQR,B0DZ683VL8,KIDSHU_SketchBoard Pro,8,24,51,41,57,29.8,ok
KNIKNISH2 Knife Set,KNIKNISH2,Knife Set (Set of 3),,143,X00273F2FT,B0DQJBSMXS,XZ-CS90-WGMJ,96,50,54,32.5,27,15.0,ok
MAGSHU MagSafe Powerbank,MAGSHU,MagSafe Powerbank,,240,,,,,60,45.2,35.2,15.5,0.09,not in FBA
MOSHU Mosquito Repellent Light,MOSHU,Camping Mosquito Repellent Light,,1805,X002AENXLP,B0F54LBGT1,MosqGuard Pro-Black,12,50,56,38.5,24,13.5,ok
PICPIC Pickle Ball Trainer Set,PICPIC,Pickle Ball Trainer Set,,808,X0029BDP3P,B0F192K8L2,PICPIC_PicklePlay-Blue,36,24,55,45,40,8.54,ok
PRISH Mini Label Printer,PRISH,Mini Label Printer,,2229,,,,,50,34,25.5,30.5,8.0,not in FBA
ROOROO Car Rooftop Carrier,ROOROO,Car Rooftop Carrier,,463,X0028HJFDJ,B0DWSFHZ63,ROOROO_RoofSpace Pro,398,20,60,50,30,16.8,ok
SHUAHUB Car Rat Repellent,SHUAHUB,Car Rat Repellent,,178,,,,,,,,,,packaging TBD
SHUAL3 Alcohol Tester,SHUAL3,Alcohol Tester,,520,X0026J3R65,B0DJRLZYXQ,WR-3SB1-4515,776,240,50.5,31.5,50,14.9,primary (alt exists)
SHUBALL Pickle Ball Set PINK YELLOW,SHUBALL,Pickle Ball Set,PINK YELLOW,170,X0028A5NEV,B0DVT94JXZ,SHUBALL Design-1,87,20,56,43.5,45,14.0,ok
SHUBALL Pickle Ball Set BLUE PINK,SHUBALL,Pickle Ball Set,BLUE PINK,112,X0028A5PO9,B0DVTCSQYX,SHUBALL Design-2,,20,56,43.5,45,14.0,ok
SHUBALL Pickle Ball Set MULTY,SHUBALL,Pickle Ball Set,MULTY,165,X0028A5UKX,B0DVT9RYD9,SHUBALL Design-4,,20,56,43.5,45,14.0,ok
SHUBALL Pickle Ball Set BLUE,SHUBALL,Pickle Ball Set,BLUE,99,X0028A64L7,B0DVTFBZHL,SHUBALL Design-3,,20,56,43.5,45,14.0,ok
SHUBOX Boxing Machine,SHUBOX,Boxing Machine,,192,X002G8NX0V,B0G2B9RSM5,Boxing machine New,423,24,76.5,45,79,0.35,ok
SHUBRACE Back Brace,SHUBRACE,Back Brace,,3500,X002EOYTUZ,B0FRRRH9KR,SpineFlex Pro-Back Brace,161,100,104,90,25,18.0,ok
SHUEYE Eye Massager,SHUEYE,Eye Massager,,73,X0028QFUCF,B0DXVLMDSW,SHUEYE_EyeSpaPro,202,30,49,41.5,46,11.12,ppc approx
SHUFA Sofa Vacuum Cleaner,SHUFA,Sofa Vacuum Cleaner,,6,X00288Z0MN,B0DVLR1H21,SHUFA_Sofa Vacuum-Gold,34,24,55,50.5,53.5,21.9,ok
SHULAMP Headlamp Outdoor,SHULAMP,Headlamp Outdoor,,384,X0029BCCCZ,B0F198HKZT,SHULAMP_NightBeam,249,100,49,37,43,17.0,ok
SHUMASK Collagen Face Mask,SHUMASK,Collagen Face Mask,,17070,X002EJIPSH,B0FR441R84,SHUMASK_GlowSkinPro Pack1,14,460,54,41.5,24.5,16.19,primary (alt exists)
SHUNAS Nasal Magnet Strip,SHUNAS,Nasal Magnet Strip,,2400,X0029BA71D,B0F192D6GS,SHUNAS_BreatheEase Pro,380,200,39.5,38.5,46,11.0,ok
SHURED3 Red Light Therapy RED,SHURED3,Red Light Therapy,RED,414,X002A8HDDZ,B0F547P4FJ,RadianceTherm Pro-Black,28,10,46.5,44.5,31,14.32,ppc approx
SHUTER Digital Clamp Meter,SHUTER,Digital Clamp Meter,,567,,,,,50,43,23,53.3,13.5,not in FBA
SHUTOVE Portable Gas Stove,SHUTOVE,Portable Butane Gas Stove,,637,X00298IW2R,B0DZ6W3VMD,SHUTOVE_FlameGuard-Black,351,6,55,36,32,10.54,ppc approx
SHUTRI Selfie Light,SHUTRI,Selfie Light/Stick,,510,X0028AO43R,B0DVZLZB9R,SHUTRI_LumiTripod,66,50,47.2,37.2,25.8,22.16,ok
SHUVER Electric Screwdriver Set,SHUVER,Electric Screwdriver Set (47 tools),,509,X0028I0IF7,B0DWSZ23NG,SHUVER_FixIt Pro,2,40,48,37,47,0.32,ok
SUBH 4K Video Recorder,SUBH,4K Video Recorder,,240,X002ESWCLT,B0FS6P64LH,EpicShot Action Camera,60,30,46,39,29.5,8.8,ok
SUVICHAR Car Charging Mount,SUVICHAR,Magnetic Wireless Car Charging Mount,,731,X002867AEB,B0DV92P7CY,SUVICHAR-GlowCharge15w,132,,,,,,packaging TBD
TRIPTRIP Ipad Holder Tripod,TRIPTRIP,iPad Holder Tripod,,1680,,,,,30,68,35,42,17.83,not in FBA
SHUHAS Electric Gas Lighter BLUE,SHUHAS,Electric Gas Lighter,BLUE,200,,,,6,,,,,,confirm amazon colour
SHUHAS Electric Gas Lighter GOLD,SHUHAS,Electric Gas Lighter,GOLD,200,,,,,,,,,,confirm amazon colour
Newdru GlowPro Portable LED Light,NEWDRU,GlowPro Portable LED Light,,78,,,,,,,,,,not in FBA
Double Burner Camping Stove,TOVISH,Double Burner Camping Stove,,1000,,,,,4,67.5,57,33.5,17.0,new addition
Ranger Stove,RANGER,Ranger Stove,,1000,,,,,,,,,,new; packaging TBD
"""


def parse_float(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_int(v):
    f = parse_float(v)
    return int(f) if f is not None else None


def slug_sku(code, variant, product):
    parts = [code]
    if variant:
        parts.append(variant.replace(" ", "-"))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", product).strip("-").upper()[:40]
    parts.append(slug or "ITEM")
    s = "-".join(parts)
    return re.sub(r"-+", "-", s).strip("-")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def find_existing(db, code, variant):
    """Locate a product for (code, variant). variant '' or None both mean 'no variant'."""
    v = variant if variant else None
    # 1st try: shipping_mark + variant exact
    query = {"shipping_mark": code}
    if v is None:
        query["$or"] = [{"variant": None}, {"variant": ""}, {"variant": {"$exists": False}}]
    else:
        query["variant"] = v
    doc = await db.products.find_one(query, {"_id": 0})
    if doc:
        return doc

    # 2nd try: SKU starts with the code AND variant appears in SKU (or absence match)
    regex = re.escape(code)
    if v:
        vupper = v.upper().replace(" ", "-")
        pat = f"^{regex}[-_].*{re.escape(vupper.split('-')[0])}"
    else:
        pat = f"^{regex}[-_]"
    doc = await db.products.find_one({"sku": {"$regex": pat}}, {"_id": 0})
    if doc:
        return doc

    # 3rd try: name contains code and variant
    name_q = {"name": {"$regex": re.escape(code), "$options": "i"}}
    if v:
        name_q["variant"] = v
    return await db.products.find_one(name_q, {"_id": 0})


async def set_location_qty(db, product, loc_code, qty, actor_name="catalog-import"):
    """Overwrite absolute quantity at loc_code + write ledger row for the delta."""
    now = now_iso()
    existing_inv = await db.inventory.find_one(
        {"product_id": product["id"], "location_code": loc_code}
    )
    current_qty = int((existing_inv or {}).get("quantity", 0))
    new_qty = int(qty)
    delta = new_qty - current_qty
    await db.inventory.update_one(
        {"product_id": product["id"], "location_code": loc_code},
        {
            "$set": {"quantity": new_qty, "last_synced_at": now},
            "$setOnInsert": {"id": str(uuid.uuid4()), "low_stock_threshold": 5},
        },
        upsert=True,
    )
    if delta != 0:
        await db.stock_movements.insert_one({
            "id": str(uuid.uuid4()),
            "product_id": product["id"],
            "sku": product["sku"],
            "location_code": loc_code,
            "movement_type": "catalog_import",
            "quantity_delta": delta,
            "reason": "Newdru catalog CSV import",
            "reference_id": "newdru-catalog-v1",
            "user_id": None,
            "user_name": actor_name,
            "created_at": now,
        })
    return current_qty, new_qty


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    reader = csv.DictReader(io.StringIO(CSV_DATA))
    rows = list(reader)
    print(f"[*] {len(rows)} CSV rows to process")

    created, updated = [], []
    warehouse_units_total = 0
    fnsku_count = 0
    fba_units_total = 0
    errors = []

    for i, row in enumerate(rows, start=2):
        try:
            code = (row["code"] or "").strip()
            product_name = (row["product"] or "").strip()
            variant = (row.get("variant") or "").strip() or None
            fnsku = (row.get("amazon_fnsku") or "").strip() or None
            asin = (row.get("amazon_asin") or "").strip() or None
            msku = (row.get("amazon_msku") or "").strip() or None
            notes = (row.get("notes") or "").strip() or None
            wh_qty = parse_int(row.get("warehouse_qty_rrc")) or 0
            fba_qty = parse_int(row.get("amazon_fba_sellable"))

            upc = parse_int(row.get("units_per_carton"))
            L = parse_float(row.get("carton_l_cm"))
            W = parse_float(row.get("carton_w_cm"))
            H = parse_float(row.get("carton_h_cm"))
            wt_kg = parse_float(row.get("carton_weight_kg"))

            carton_dims = None
            if L and W and H:
                carton_dims = {"length_cm": L, "width_cm": W, "height_cm": H}

            unit_weight_g = None
            carton_weight_g = None
            if wt_kg is not None:
                carton_weight_g = wt_kg * 1000
                if upc and upc > 0:
                    unit_weight_g = round(carton_weight_g / upc, 3)

            existing = await find_existing(db, code, variant)

            display_name = product_name if not variant else f"{product_name} — {variant}"

            # Build the field set (only overwrite fields we have data for; keep others intact)
            patch = {
                "name": display_name,
                "brand": "Newdru",
                "category": product_name,
                "variant": variant,
                "shipping_mark": code,
                "amazon_fnsku": fnsku,
                "amazon_asin": asin,
                "amazon_msku": msku,
                "notes": notes,
                "updated_at": now_iso(),
            }
            if upc is not None:
                patch["units_per_carton"] = upc
            if carton_dims:
                patch["carton_dimensions"] = carton_dims
            if carton_weight_g is not None:
                patch["carton_weight_g"] = carton_weight_g
            if unit_weight_g is not None:
                patch["unit_weight_g"] = unit_weight_g
            # barcode: use FNSKU when we have one; else leave existing
            if fnsku:
                patch["barcode"] = fnsku
                patch["barcode_type"] = "FNSKU"
                patch["channel_scope"] = "online_offline"
            else:
                # keep whatever exists; for new inserts we'll set defaults below
                pass

            if existing is None:
                # Create new SKU
                sku = slug_sku(code, variant, product_name)
                new_doc = {
                    "id": str(uuid.uuid4()),
                    "sku": sku,
                    "mrp": 0.0,
                    "gst_rate": 18.0,
                    "hsn": None,
                    "images": [],
                    "status": "active",
                    "buy_price": 0.0,
                    "sell_price": 0.0,
                    "placeholder_pricing": True,
                    "created_at": now_iso(),
                    **patch,
                }
                new_doc.setdefault("barcode", sku)
                new_doc.setdefault("barcode_type", "CODE128" if not fnsku else "FNSKU")
                new_doc.setdefault("channel_scope", "online_offline" if fnsku else "offline_only")
                new_doc.setdefault("units_per_carton", upc or 1)
                await db.products.insert_one(new_doc)
                created.append({"sku": sku, "code": code, "variant": variant})
                existing = new_doc
            else:
                await db.products.update_one({"id": existing["id"]}, {"$set": patch})
                updated.append({"sku": existing["sku"], "code": code, "variant": variant})
                existing.update(patch)

            # ------- stock writes ---------
            if wh_qty >= 0:
                await set_location_qty(db, existing, "BHIWANDI", wh_qty)
                warehouse_units_total += wh_qty
            if fba_qty is not None:
                await set_location_qty(db, existing, "AMAZON_FC", fba_qty)
                fba_units_total += fba_qty
            if fnsku:
                fnsku_count += 1

        except Exception as ex:
            errors.append({"row": i, "error": str(ex)})

    print()
    print("=" * 70)
    print(" NEWDRU CATALOG IMPORT — REPORT ")
    print("=" * 70)
    print(f"Updated : {len(updated)}")
    print(f"Created : {len(created)}   {[c['code'] + (':' + (c['variant'] or '')) for c in created]}")
    print(f"Errors  : {len(errors)}    {errors[:5]}")
    print()
    print(f"Total Bhiwandi units set : {warehouse_units_total:,}")
    print(f"Total Amazon FC units set: {fba_units_total:,}")
    print(f"Products with FNSKU      : {fnsku_count} / {len(rows)}")

    total_products = await db.products.count_documents({})
    placeholder = await db.products.count_documents({"placeholder_pricing": True})
    print(f"Total products in DB now : {total_products}   (placeholder-pricing: {placeholder})")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
