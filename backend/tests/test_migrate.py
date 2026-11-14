"""The one-time Emergent -> Atlas copy merges safely into a database the new app already started on."""
import os
import sys

import mongomock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import migrate_db  # noqa: E402


def test_merge_keeps_old_accounts_and_highest_counter():
    client = mongomock.MongoClient()
    src, dst = client["old"], client["new"]
    src.users.insert_many([{"_id": 1, "id": "u-old", "email": "store@newdru.com", "role": "store_manager"},
                           {"_id": 2, "id": "u-cash", "email": "cashier@newdru.com", "role": "cashier"}])
    src.counters.insert_one({"_id": "invoice_26", "seq": 412})
    src.sales.insert_many([{"_id": i, "invoice_no": f"NW-26-{i:05d}", "cashier_id": "u-old"} for i in range(1, 6)])
    src.rate_limits.insert_one({"_id": "x"})
    # new app already started: starter login + fresh counter
    dst.users.insert_one({"_id": 99, "id": "u-new", "email": "store@newdru.com", "role": "store_manager"})
    dst.counters.insert_one({"_id": "invoice_26", "seq": 3})

    assert migrate_db.run(src, dst, write=False) == 0
    assert dst.sales.count_documents({}) == 0                        # dry run changes nothing
    assert migrate_db.run(src, dst, write=True) == 0
    assert dst.users.find_one({"email": "store@newdru.com"})["id"] == "u-old"
    assert dst.users.count_documents({}) == 2
    assert dst.counters.find_one({"_id": "invoice_26"})["seq"] == 412
    assert dst.sales.count_documents({}) == 5
    assert "rate_limits" not in dst.list_collection_names()
    assert migrate_db.run(src, dst, write=True) == 0                 # safe to run twice
    assert dst.sales.count_documents({}) == 5 and dst.users.count_documents({}) == 2
