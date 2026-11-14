"""One-shot script that ingests the user's Bhiwandi stock from the two
uploaded Excel files and prints a warehouse-capacity report.

Sources:
  /tmp/bapana.xlsx      - current Bhiwandi (RRC) closing quantities per SKU
  /tmp/sb_orders.xlsx   - Shubham Bhai's incoming orders (has carton dims,
                          pcs-per-CTN, per shipping-mark)

Approach:
  1. Read BAPANA rows -> derive shipping_mark + variant + qty
  2. Build a shipping_mark -> {pcs_per_ctn, carton_dims_cm} map from SB ORDERS
  3. For any BAPANA row that has no dimensions match, fall back to the
     largest carton for that mark (or a conservative default).
  4. POST to /api/inventory/bulk-import as admin -> writes stock into
     LOC_BHIWANDI + returns capacity report.

Run:  python3 /app/scripts/import_bhiwandi_data.py
"""
from __future__ import annotations
import os
import re
import json
import sys
from pathlib import Path

import openpyxl
import httpx

BAPANA = Path("/tmp/bapana.xlsx")
SB_ORDERS = Path("/tmp/sb_orders.xlsx")

BACKEND_URL = None
for line in Path("/app/frontend/.env").read_text().splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BACKEND_URL = line.split("=", 1)[1].strip()
        break
assert BACKEND_URL, "REACT_APP_BACKEND_URL missing"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@newdru.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Newdru@2026")


# ---------- helpers ---------------------------------------------------------
def clean_str(v):
    if v is None:
        return None
    return str(v).strip() or None


def parse_pcs(v):
    """'120 Pcs' -> 120 ; 1000 -> 1000 ; '5000 Set' -> 5000 ; '1000 pcs' -> 1000."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"([\d,]+)", str(v))
    return int(m.group(1).replace(",", "")) if m else None


def parse_units_per_carton(v):
    """PCS/CTN can be '48/40' (multiple carton types) or 100 or '50/300/200'.
    We take the largest (the master carton) so cubic-fill is conservative.
    Ignore datetime.datetime values (Excel format weirdness)."""
    import datetime as dt
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    parts = re.findall(r"\d+", str(v))
    if not parts:
        return None
    return max(int(x) for x in parts)


def parse_dims(v):
    """'54*44*42' or '54x44x42' or '54*44*42/ 1-48*37*28' -> (L,W,H)
    Take the first (master carton) triplet. Returns dict or None."""
    if v is None:
        return None
    s = str(v)
    s = s.replace("Ⅹ", "*").replace("x", "*").replace("X", "*").replace("×", "*")
    m = re.search(r"(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    L, W, H = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return {"length_cm": L, "width_cm": W, "height_cm": H}


# ---------- SB ORDERS -> shipping-mark ➜ dims map --------------------------
def load_shipping_mark_dims():
    """Returns dict: mark -> {pcs_per_ctn, carton_dims, weight_kg_per_ctn, name}
    If a mark repeats (multiple shipments), keep the one with the LARGEST carton
    volume (so worst-case cubic estimate).
    """
    wb = openpyxl.load_workbook(SB_ORDERS, data_only=True)
    ws = wb["Sheet1"]
    marks: dict[str, dict] = {}
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i < 3:
            continue  # skip title + header
        mark = clean_str(row[0])
        prod_name = clean_str(row[1])
        if not mark:
            continue
        mark = mark.upper()
        upc = parse_units_per_carton(row[3])
        dims = parse_dims(row[5])
        weight = row[6]
        try:
            weight = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            weight = None
        vol = 0.0
        if dims:
            vol = dims["length_cm"] * dims["width_cm"] * dims["height_cm"]
        current = marks.get(mark)
        if current is None or vol > current.get("_vol", 0):
            marks[mark] = {
                "pcs_per_ctn": upc,
                "carton_dims": dims,
                "carton_weight_g": (weight * 1000) if weight else None,
                "name_hint": prod_name,
                "_vol": vol,
            }
    for m in marks.values():
        m.pop("_vol", None)
    return marks


# ---------- BAPANA -> ingest lines -----------------------------------------
COLOR_RE = re.compile(
    r"\b(BLACK|BLUE|PINK|WHITE|GOLD|SILVER|GRAY|GREEN|RED|MULTY|YELLOW|OLIVE)\b",
    re.IGNORECASE,
)

def derive_mark_and_variant(product_name: str):
    """'BAPNA (PORTABLE AIR PURIFIER) BLACK_20 KG' -> ('BAPNA','BLACK')
    'AMTER – Pollution Detection Meter – 128 pcs/CTN_20 KG' -> ('AMTER', None)
    'SHUBALL (X0028A5UKX (MULTY )_20 KG' -> ('SHUBALL','MULTY')
    """
    name = product_name.strip()
    # Shipping mark is the first ALL-CAPS token
    m = re.match(r"^([A-Z][A-Z0-9]{2,})", name)
    mark = m.group(1) if m else None
    variant = None
    cm = COLOR_RE.search(name)
    if cm:
        variant = cm.group(1).upper()
    return mark, variant


def load_bapana_items(mark_dims: dict):
    wb = openpyxl.load_workbook(BAPANA, data_only=True)
    ws = wb["Sheet1"]
    items = []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i == 1:
            continue  # header
        prod_name = clean_str(row[0])
        qty = row[3]
        if not prod_name or qty is None:
            continue
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            continue
        mark, variant = derive_mark_and_variant(prod_name)
        # Clean the display name (strip trailing _20 KG etc.)
        display = re.sub(r"_\d+\s*kg\b.*$", "", prod_name, flags=re.IGNORECASE).strip()
        # SKU: MARK-VARIANT-SLUG(rest)
        slug_source = display
        if mark and slug_source.upper().startswith(mark):
            slug_source = slug_source[len(mark):].strip(" -–—():")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", slug_source).strip("-").upper()[:40] or "ITEM"
        parts = [p for p in [mark, variant, slug] if p]
        sku = "-".join(parts) if parts else display[:40]
        sku = re.sub(r"-+", "-", sku).strip("-")

        dims_row = mark_dims.get(mark or "", {})
        item = {
            "sku": sku,
            "name": display,
            "shipping_mark": mark,
            "variant": variant,
            "quantity": qty,
            "units_per_carton": dims_row.get("pcs_per_ctn") or 1,
            "carton_dimensions": dims_row.get("carton_dims"),
            "carton_weight_g": dims_row.get("carton_weight_g"),
            "brand": "Newdru",
            "category": (dims_row.get("name_hint") or display).split("(")[0].strip(),
            "reference": "bhiwandi-initial-ingest",
        }
        items.append(item)
    return items


# ---------- orchestrator ---------------------------------------------------
def main():
    print(f"[*] Loading SB ORDERS shipping-mark dims from {SB_ORDERS}")
    marks = load_shipping_mark_dims()
    print(f"    -> {len(marks)} shipping marks with dim data")

    print(f"[*] Loading BAPANA closing qtys from {BAPANA}")
    items = load_bapana_items(marks)
    print(f"    -> {len(items)} SKUs to ingest")
    missing_dims = [i["sku"] for i in items if not i.get("carton_dimensions")]
    if missing_dims:
        print(f"    !! {len(missing_dims)} SKUs have no carton-dim match:")
        for s in missing_dims:
            print(f"       - {s}")

    print(f"[*] Authenticating as {ADMIN_EMAIL} on {BACKEND_URL}")
    with httpx.Client(base_url=BACKEND_URL, timeout=60) as client:
        r = client.post("/api/auth/login",
                        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        r.raise_for_status()
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        body = {
            "target_location": "BHIWANDI",
            "mode": "set",
            "auto_create_products": True,
            "stack_height_m": 2.4,
            "aisle_factor": 1.6,
            "items": items,
        }
        print("[*] POST /api/inventory/bulk-import ...")
        r = client.post("/api/inventory/bulk-import", json=body, headers=headers)
        if r.status_code >= 400:
            print("!! import failed:", r.status_code, r.text[:500])
            sys.exit(1)
        result = r.json()

    print()
    print("=" * 70)
    print(" WAREHOUSE INGEST REPORT — BHIWANDI ")
    print("=" * 70)
    print(f"Products created: {len(result['created_products'])}")
    print(f"Products updated: {len(result['updated_products'])}")
    print(f"Stock rows written: {len(result['stock_updates'])}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
        for e in result["errors"][:10]:
            print(f"   - {e}")

    cap = result["capacity_analysis"]
    t = cap["totals"]
    a = cap["assumptions"]
    print()
    print("--- CAPACITY vs 1000 sqft (92.9 m²) ---------------------------------")
    print(f"SKUs                        : {t['sku_count']}")
    print(f"Total units                 : {t['total_units']:,}")
    print(f"Total cartons (master)      : {t['total_cartons']:,}")
    print(f"Total cubic volume          : {t['total_volume_m3']:.2f} m³")
    print(f"Stack height assumed        : {a['stack_height_m']} m (≈ 8 ft)")
    print(f"Aisle overhead              : {a['aisle_factor']}x")
    print(f"Floor area — bare           : {t['floor_area_bare_m2']:.2f} m²")
    print(f"Floor area — with aisle     : {t['floor_area_with_aisle_m2']:.2f} m² "
          f"(≈ {t['floor_area_with_aisle_sqft']:.0f} sqft)")
    print(f"Utilization of 1000 sqft    : {t['utilization_of_1000sqft_pct']:.1f}%")
    print(f"Fits in 1000 sqft (2.4m st) : {'YES ✅' if t['fits_in_1000sqft'] else 'NO ❌'}")
    if cap["skus_missing_carton_dims"]:
        print(f"\n(SKUs without carton dims — not counted in volume: "
              f"{len(cap['skus_missing_carton_dims'])})")
    print()
    # Save a JSON copy for reference
    out = Path("/app/memory/bhiwandi_capacity_report.json")
    out.parent.mkdir(exist_ok=True, parents=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"Full report saved to {out}")


if __name__ == "__main__":
    main()
