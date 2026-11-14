"""Unicommerce FC sync — CSV upload now + live-API stub for later.

Amazon FC (AMAZON_FC) and Flipkart FC (FLIPKART_FC) inventory is read-only in
this app; when Unicommerce creds arrive, `UnicommerceClient.pull_inventory()`
will fill the same collection.
"""
from __future__ import annotations
import io
import csv
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Depends
from pydantic import BaseModel

from models import (
    gen_id, now_iso, LOC_AMAZON_FC, LOC_FLIPKART_FC,
    ROLE_OWNER, ROLE_WH_MANAGER,
)
from auth import require_roles, get_current_user, audit
from security import secret_matches
from services import unicommerce as uc
from services import unicommerce_sync as ucs

router = APIRouter(prefix="/fc-sync", tags=["fc-sync"])

VALID_FC_CODES = {LOC_AMAZON_FC, LOC_FLIPKART_FC}


def _cred(k: str, default: str = "") -> str:
    return os.environ.get(k, default) or ""


def _unicommerce_mode() -> str:
    return uc.mode()


@router.get("/config")
async def config(request: Request, user: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    last = await db.sync_runs.find(
        {"source": "unicommerce"}, {"_id": 0}).sort("finished_at", -1).limit(5).to_list(5)
    return {
        "mode": _unicommerce_mode(),
        "tenant_set": bool(_cred("UNICOMMERCE_TENANT")),
        "api_user_set": bool(_cred("UNICOMMERCE_USER")),
        "password_set": bool(_cred("UNICOMMERCE_PASSWORD")),
        "facilities": uc.facility_map(),
        "push": uc.push_settings(),
        "inventory_every_minutes": ucs.INVENTORY_EVERY_MIN,
        "orders_every_minutes": ucs.ORDERS_EVERY_MIN,
        "supported_locations": sorted(VALID_FC_CODES),
        "recent_runs": last,
        "note": "CSV upload is always available. Live sync runs automatically when UNICOMMERCE_MODE=live.",
    }


@router.post("/csv")
async def upload_csv(
    request: Request,
    location_code: str = Form(...),
    file: UploadFile = File(...),
    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER)),
):
    """Accept CSV with columns: sku,quantity (extra columns ignored).

    - Matches SKU to product; unknown SKUs are reported in `unknown_skus`.
    - Sets the AMAZON_FC / FLIPKART_FC quantity ABSOLUTELY (not delta).
    - Sets `last_synced_at` on the row.
    """
    if location_code not in VALID_FC_CODES:
        raise HTTPException(400, f"location_code must be one of {sorted(VALID_FC_CODES)}")
    db = request.app.state.db
    raw = (await file.read()).decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "sku" not in [f.lower() for f in reader.fieldnames]:
        raise HTTPException(400, "CSV must have a 'sku' column")

    # Normalise header case
    field_map = {f.lower(): f for f in reader.fieldnames}
    sku_key = field_map["sku"]
    qty_key = field_map.get("quantity") or field_map.get("qty") or field_map.get("stock") or "quantity"

    now = now_iso()
    updated = 0
    unknown = []
    zeroed = []
    for row in reader:
        sku = (row.get(sku_key) or "").strip()
        if not sku: continue
        try: qty = int(float(row.get(qty_key) or 0))
        except Exception: qty = 0
        product = await db.products.find_one({"sku": sku})
        if not product:
            unknown.append(sku); continue
        r = await db.inventory.update_one(
            {"product_id": product["id"], "location_code": location_code},
            {"$set": {"quantity": qty, "last_synced_at": now, "updated_at": now}},
            upsert=True,
        )
        # Write a movement so history is complete (delta unknown → 'sync')
        await db.stock_movements.insert_one({
            "id": gen_id(),
            "product_id": product["id"], "sku": product["sku"],
            "location_code": location_code,
            "movement_type": "fc_sync",
            "quantity_delta": qty, "quantity_after": qty,
            "reason": f"CSV sync from Unicommerce ({file.filename})",
            "user_id": actor["id"], "user_name": actor.get("name"),
            "created_at": now,
        })
        updated += 1
        if qty == 0: zeroed.append(sku)

    await audit(db, actor, "fc_sync.csv", "fc_sync", None,
                {"location_code": location_code, "filename": file.filename,
                 "updated": updated, "unknown": len(unknown), "zeroed": len(zeroed)})

    return {
        "location_code": location_code,
        "filename": file.filename,
        "updated": updated,
        "unknown_skus": unknown[:50],
        "unknown_count": len(unknown),
        "zeroed": len(zeroed),
        "synced_at": now,
    }


def _live_client() -> uc.UnicommerceClient:
    if _unicommerce_mode() != "live":
        raise HTTPException(503, "Unicommerce live mode is off. Use CSV upload, or set UNICOMMERCE_MODE=live with the login details.")
    try:
        return uc.UnicommerceClient.from_env()
    except uc.UnicommerceError as e:
        raise HTTPException(503, str(e))


@router.post("/pull")
async def pull_live(request: Request, location_code: Optional[str] = None,
                    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    """Pull stock now from Unicommerce for one mapped location (or all mapped)."""
    client = _live_client()
    locations = [location_code.upper()] if location_code else None
    try:
        result = await ucs.sync_inventory(request.app.state.db, client, locations, actor)
    except uc.UnicommerceError as e:
        raise HTTPException(502, str(e))
    await audit(request.app.state.db, actor, "fc_sync.unicommerce_pull", "fc_sync", None,
                {k: {"changed": v["changed"], "unknown": v["unknown_count"]} for k, v in result["locations"].items()})
    return result


@router.post("/orders/pull")
async def pull_orders(request: Request, since_minutes: int = 1440,
                      actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Pull marketplace orders updated in the last N minutes (max 1440)."""
    client = _live_client()
    try:
        return await ucs.sync_orders(request.app.state.db, client, since_minutes, actor)
    except uc.UnicommerceError as e:
        raise HTTPException(502, str(e))


@router.get("/orders/summary")
async def orders_summary(request: Request, days: int = 7,
                         actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Orders by channel and status for the last N days (from synced Unicommerce data)."""
    db = request.app.state.db
    days = max(1, min(int(days), 90))
    since = (datetime.now(timezone.utc).timestamp() - days * 86400) * 1000
    rows = await db.unicommerce_orders.find({}, {"_id": 0, "channel": 1, "status": 1, "uc_created": 1}).to_list(200_000)
    out: dict = {}
    for r in rows:
        created = r.get("uc_created")
        if isinstance(created, (int, float)) and created < since:
            continue
        ch = r.get("channel") or "UNKNOWN"
        st = r.get("status") or "UNKNOWN"
        out.setdefault(ch, {}).setdefault(st, 0)
        out[ch][st] += 1
    return {"days": days, "by_channel": out, "total": sum(sum(v.values()) for v in out.values())}


@router.get("/mapping")
async def get_mapping(request: Request, actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    """Current app SKU -> Unicommerce SKU links."""
    db = request.app.state.db
    rows = await db.products.find({"unicommerce_skus.0": {"$exists": True}},
                                  {"_id": 0, "sku": 1, "name": 1, "unicommerce_skus": 1}).to_list(5000)
    return {"mapped_products": len(rows), "rows": rows}


@router.post("/mapping/import")
async def import_mapping(request: Request, file: UploadFile = File(...), replace: bool = Form(True),
                         actor: dict = Depends(require_roles(ROLE_OWNER))):
    """CSV columns: app_sku, unicommerce_sku, units (units optional, default 1).
    Rows with an empty unicommerce_sku are ignored. replace=true resets each
    listed product's links to exactly what the file says."""
    db = request.app.state.db
    raw = (await file.read()).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(raw))
    cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
    if "app_sku" not in cols or "unicommerce_sku" not in cols:
        raise HTTPException(400, "CSV needs columns app_sku and unicommerce_sku (and optional units)")
    links: dict = {}
    for row in reader:
        a = (row.get(cols["app_sku"]) or "").strip()
        u = (row.get(cols["unicommerce_sku"]) or "").strip()
        if not a or not u:
            continue
        try:
            units = max(1, int(float(row.get(cols.get("units", ""), "") or 1)))
        except ValueError:
            units = 1
        links.setdefault(a, []).append({"sku": u, "units": units})
    updated, unknown = 0, []
    for a, maps in links.items():
        p = await db.products.find_one({"sku": a}, {"_id": 0, "id": 1, "unicommerce_skus": 1})
        if not p:
            unknown.append(a); continue
        new = maps if replace else (p.get("unicommerce_skus") or []) + maps
        await db.products.update_one({"id": p["id"]}, {"$set": {"unicommerce_skus": new, "updated_at": now_iso()}})
        updated += 1
    await audit(db, actor, "fc_sync.mapping_import", "product", None, {"updated": updated, "unknown": len(unknown)})
    return {"updated_products": updated, "unknown_app_skus": unknown}


@router.get("/push/preview")
async def push_preview(request: Request, actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Shows exactly what a stock push would change in Unicommerce. Changes nothing."""
    client = _live_client()
    try:
        return await ucs.push_plan(request.app.state.db, client)
    except uc.UnicommerceError as e:
        raise HTTPException(502, str(e))


class PushConfirm(BaseModel):
    confirm: bool = False


@router.post("/push")
async def push_now(body: PushConfirm, request: Request, actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Send app stock to Unicommerce (REPLACE). Owner only, needs confirm=true and
    UNICOMMERCE_PUSH_ENABLED=true. Unicommerce then updates marketplace listings."""
    if not body.confirm:
        raise HTTPException(400, "Open the preview first, then send confirm=true.")
    client = _live_client()
    try:
        result = await ucs.push_inventory(request.app.state.db, client, actor)
    except uc.UnicommerceError as e:
        raise HTTPException(502, str(e))
    await audit(request.app.state.db, actor, "fc_sync.unicommerce_push", "fc_sync", None,
                {"sent": result["sent"], "ok": result["ok"], "failed": len(result["failed"])})
    return result


@router.get("/runs")
async def sync_runs(request: Request, limit: int = 20,
                    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    return await db.sync_runs.find({"source": "unicommerce"}, {"_id": 0}).sort(
        "finished_at", -1).limit(max(1, min(int(limit), 100))).to_list(100)


# ---- Scheduler hook (called every 5 minutes by the Cloudflare Worker cron) ----
internal = APIRouter(prefix="/internal", tags=["internal"])


@internal.post("/cron")
async def cron(request: Request):
    expected = os.environ.get("CRON_SECRET")
    if not secret_matches(request.headers.get("x-cron-token"), expected):
        raise HTTPException(401, "Unauthorized")
    db = request.app.state.db
    await db.settings.update_one({"_id": "scheduler_heartbeat"}, {"$set": {"at": now_iso()}}, upsert=True)
    out = {"unicommerce": await ucs.run_due(db)}
    from routes.shipping import refresh_active
    from services import scheduled
    out["shiprocket"] = await refresh_active(db)
    out["shopify"] = await scheduled.shopify_orders_if_due(db)
    return out


@internal.post("/backup")
async def backup(request: Request):
    """Nightly full backup, called only by the Cloudflare Worker (cron secret).
    Returns gzipped extended-JSON of every collection; the Worker stores it in a
    private R2 bucket in Shubham's Cloudflare account."""
    expected = os.environ.get("CRON_SECRET")
    if not secret_matches(request.headers.get("x-cron-token"), expected):
        raise HTTPException(401, "Unauthorized")
    import gzip
    from bson import json_util
    from fastapi.responses import Response
    db = request.app.state.db
    names = sorted(n for n in await db.list_collection_names()
                   if not n.startswith("system.") and n not in {"rate_limits", "login_attempts"})
    buf = io.BytesIO()
    counts = {}
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        gz.write(b'{"format":"newdru-backup-v1","created_at":' + json_util.dumps(now_iso()).encode() + b',"collections":{')
        for i, name in enumerate(names):
            if i:
                gz.write(b",")
            gz.write(json_util.dumps(name).encode() + b":[")
            n = 0
            async for doc in db[name].find({}):
                if n:
                    gz.write(b",")
                gz.write(json_util.dumps(doc).encode())
                n += 1
            gz.write(b"]")
            counts[name] = n
        gz.write(b"}}")
    data = buf.getvalue()
    await db.sync_runs.insert_one({"id": gen_id(), "source": "backup", "kind": "nightly", "ok": True,
                                   "started_at": now_iso(), "finished_at": now_iso(), "by": "scheduler",
                                   "result": {"bytes": len(data), "collections": counts}})
    return Response(content=data, media_type="application/gzip",
                    headers={"X-Backup-Collections": str(len(counts)),
                             "X-Backup-Documents": str(sum(counts.values()))})


# ---- Owner-only "is everything still running?" panel ----
system = APIRouter(prefix="/system", tags=["system"])

# (label, sync_runs source, kind, how many minutes before it counts as late)
_JOBS = [
    ("Unicommerce stock pull", "unicommerce", "inventory", 90),
    ("Unicommerce orders", "unicommerce", "orders", 180),
    ("Shopify orders", "shopify", "orders", 180),
    ("Nightly backup", "backup", "nightly", 26 * 60),
]


def _age_min(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - t).total_seconds() // 60)
    except ValueError:
        return None


@system.get("/health")
async def system_health(request: Request, actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    hb = await db.settings.find_one({"_id": "scheduler_heartbeat"}) or {}
    hb_age = _age_min(hb.get("at"))
    jobs = []
    for label, source, kind, late_after in _JOBS:
        last = await db.sync_runs.find_one({"source": source, "kind": kind},
                                           {"_id": 0, "ok": 1, "finished_at": 1, "result": 1},
                                           sort=[("finished_at", -1)])
        ok_last = await db.sync_runs.find_one({"source": source, "kind": kind, "ok": True},
                                              {"_id": 0, "finished_at": 1}, sort=[("finished_at", -1)])
        age = _age_min((ok_last or {}).get("finished_at"))
        if last is None:
            state = "never"
        elif not last.get("ok"):
            state = "failing"
        elif age is not None and age > late_after:
            state = "late"
        else:
            state = "ok"
        err = None
        if last and not last.get("ok"):
            r = last.get("result") or {}
            err = str(r.get("error") or r)[:200]
        jobs.append({"name": label, "state": state, "last_success": (ok_last or {}).get("finished_at"),
                     "minutes_ago": age, "error": err})
    return {
        "scheduler": {"state": "never" if hb_age is None else ("ok" if hb_age <= 15 else "late"),
                      "last_beat": hb.get("at"), "minutes_ago": hb_age},
        "jobs": jobs,
    }
