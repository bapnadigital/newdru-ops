"""Nightly backup endpoint: secret-protected, complete, and restorable."""
import gzip
import importlib
import os
import sys
import uuid

import pytest
from bson import json_util
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def app(monkeypatch):
    import motor.motor_asyncio
    from mongomock_motor import AsyncMongoMockClient
    monkeypatch.setenv("MONGO_URL", "mongodb://x")
    monkeypatch.setenv("DB_NAME", f"bk_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "Owner-Test-Pass-2026")
    monkeypatch.setenv("SEED_PASSWORD", "Seed-Test-Pass-2026")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CRON_SECRET", "c" * 40)
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="https://t") as c:
        yield c, server


def test_backup_needs_secret(app):
    c, _ = app
    assert c.post("/api/internal/backup").status_code == 401
    assert c.post("/api/internal/backup", headers={"X-Cron-Token": "wrong"}).status_code == 401


def test_backup_contains_data_and_skips_noise(app):
    c, server = app
    async def seed():
        await server.db.products.insert_one({"id": "p1", "sku": "S1", "name": "Mitt"})
        await server.db.rate_limits.insert_one({"key": "x"})
    c.portal.call(seed)
    r = c.post("/api/internal/backup", headers={"X-Cron-Token": "c" * 40})
    assert r.status_code == 200
    data = json_util.loads(gzip.decompress(r.content).decode())
    assert data["format"] == "newdru-backup-v1"
    assert data["collections"]["products"][0]["sku"] == "S1"
    assert "users" in data["collections"]
    assert "rate_limits" not in data["collections"]
