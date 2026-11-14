"""Newdru main FastAPI app. Loads env, mounts routers, seeds admin+indexes."""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from auth import hash_password, verify_password
from security import SecurityHeadersMiddleware, MaxBodySizeMiddleware
from models import ROLE_OWNER, gen_id, now_iso
from routes.auth_routes import router as auth_router
from routes.users import router as users_router
from routes.products import router as products_router
from routes.inventory import router as inventory_router
from routes.stock import router as stock_router
from routes.pos import router as pos_router
from routes.customers import router as customers_router
from routes.reports import router as reports_router
from routes.labels import router as labels_router
from routes.integrations_routes import router as integrations_router
from routes.pinelabs import router as pinelabs_router
from routes.b2b import router as b2b_router
from routes.fc_sync import router as fc_sync_router, internal as internal_router
from routes.messaging_routes import router as messaging_router
from routes.bulk_import import router as bulk_import_router
from routes.planner import router as planner_router
from routes.warranty import router as warranty_router
from routes.shopify_sync import router as shopify_router
from routes.help import router as help_router

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("newdru")

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

APP_ENV = os.environ.get("APP_ENV", "development").lower()
IS_PROD = APP_ENV == "production"

# Fail closed: a weak or missing signing key would let anyone forge logins.
if IS_PROD and len(os.environ.get("JWT_SECRET", "")) < 32:
    raise RuntimeError("JWT_SECRET must be set to a random value of at least 32 characters in production")

# API docs list every endpoint; keep them off in production unless explicitly enabled.
_docs = os.environ.get("ENABLE_API_DOCS", "false" if IS_PROD else "true").lower() == "true"
app = FastAPI(title="Newdru API", version="0.2.0",
              docs_url="/api/docs" if _docs else None,
              redoc_url=None,
              openapi_url="/api/openapi.json" if _docs else None)
app.state.db = db

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"service": "newdru", "status": "ok"}


@api_router.get("/health")
async def health():
    return {"status": "healthy", "time": now_iso()}


api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(products_router)
api_router.include_router(inventory_router)
api_router.include_router(stock_router)
api_router.include_router(pos_router)
api_router.include_router(customers_router)
api_router.include_router(reports_router)
api_router.include_router(labels_router)
api_router.include_router(integrations_router)
api_router.include_router(pinelabs_router)
api_router.include_router(b2b_router)
api_router.include_router(fc_sync_router)
api_router.include_router(internal_router)
api_router.include_router(messaging_router)
api_router.include_router(bulk_import_router)
api_router.include_router(planner_router)
api_router.include_router(warranty_router)
api_router.include_router(shopify_router)
api_router.include_router(help_router)

app.include_router(api_router)

# CORS: only explicitly listed origins. The production app serves the frontend
# and the API from the same domain, so no cross-origin access is needed at all.
# A wildcard with credentials would let any website read staff data.
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",")
            if o.strip() and o.strip() != "*"]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origins=_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MaxBodySizeMiddleware)

# Serve the built React app from the same origin when FRONTEND_BUILD_DIR is set.
_frontend_dir = Path(os.environ.get("FRONTEND_BUILD_DIR", "")) if os.environ.get("FRONTEND_BUILD_DIR") else None
if _frontend_dir and _frontend_dir.is_dir():
    _frontend_root = _frontend_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (_frontend_root / full_path).resolve()
        if full_path and candidate.is_file() and _frontend_root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_frontend_root / "index.html",
                            headers={"Cache-Control": "no-cache"})


async def seed_admin_and_indexes():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.products.create_index("sku", unique=True)
    await db.products.create_index("barcode")
    await db.products.create_index("id", unique=True)
    await db.inventory.create_index([("product_id", 1), ("location_code", 1)], unique=True)
    await db.stock_movements.create_index("created_at")
    await db.stock_movements.create_index("product_id")
    await db.sales.create_index("invoice_no", unique=True)
    await db.sales.create_index("created_at")
    await db.sales.create_index("cashier_id")
    await db.sales.create_index("client_ref", sparse=True)
    await db.customers.create_index("phone", sparse=True)
    await db.customers.create_index("email", sparse=True)
    await db.customers.create_index("id", unique=True)
    await db.transfers.create_index("id", unique=True)
    await db.audit_logs.create_index("created_at")
    await db.login_attempts.create_index("identifier")
    await db.rate_limits.create_index("expires_at", expireAfterSeconds=0)
    await db.sync_runs.create_index([("source", 1), ("kind", 1), ("finished_at", -1)])
    await db.unicommerce_orders.create_index("code", unique=True)
    # Warranty indexes
    await db.warranty_registrations.create_index("warranty_id", unique=True, sparse=True)
    await db.warranty_registrations.create_index("email")
    await db.warranty_registrations.create_index("sku")
    await db.warranty_registrations.create_index("created_at")
    await db.warranty_activity.create_index("created_at")
    await db.warranty_activity.create_index("warranty_id")
    await db.warranty_activity.create_index("event")
    await db.warranty_claims.create_index("warranty_id")
    await db.warranty_claims.create_index("status")

    # Seed the 3 starter accounts ONLY if they do not exist yet.
    # Passwords are never overwritten on restart, so a password the owner
    # changes in Users stays changed. Set SEED_PASSWORD in backend/.env to
    # choose the first-time password (defaults to the old demo value).
    # To force-reset the starter accounts (demo/preview only), set
    # SEED_RESET_PASSWORDS=true.
    seed_pw = os.environ.get("SEED_PASSWORD", "Newdru@2026")
    force_reset = os.environ.get("SEED_RESET_PASSWORDS", "false").lower() == "true"
    demo_users = [
        {"email": os.environ.get("ADMIN_EMAIL", "admin@newdru.com").lower(),
         "password": os.environ.get("ADMIN_PASSWORD", seed_pw),
         "name": "Newdru Admin", "role": "owner"},
        {"email": "store@newdru.com", "password": seed_pw,
         "name": "Store User", "role": "store_manager"},
        {"email": "warehouse@newdru.com", "password": seed_pw,
         "name": "Warehouse User", "role": "warehouse_manager"},
    ]
    for du in demo_users:
        existing = await db.users.find_one({"email": du["email"]})
        if existing is None:
            await db.users.insert_one({
                "id": gen_id(),
                "email": du["email"],
                "password_hash": hash_password(du["password"]),
                "name": du["name"], "role": du["role"], "active": True,
                "created_at": now_iso(),
            })
            logger.info("Seeded starter user %s (%s)", du["email"], du["role"])
        elif force_reset and not verify_password(du["password"], existing["password_hash"]):
            await db.users.update_one(
                {"email": du["email"]},
                {"$set": {"password_hash": hash_password(du["password"])}},
            )
            logger.warning("SEED_RESET_PASSWORDS=true: reset password for %s", du["email"])


@app.on_event("startup")
async def startup():
    try:
        await seed_admin_and_indexes()
        logger.info("Newdru startup complete")
    except Exception as e:
        logger.exception("Startup error: %s", e)


@app.on_event("shutdown")
async def shutdown():
    client.close()
