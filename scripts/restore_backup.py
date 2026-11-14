"""Restore a NEWDRU Ops nightly backup into a MongoDB database.

Backups live in the private Cloudflare R2 bucket "newdru-backups"
(Cloudflare dashboard > R2 > newdru-backups > newdru-ops/YYYY-MM-DD.json.gz).

Usage (dry run first — it only prints what it would restore):
    TARGET="mongodb+srv://user:pass@cluster/..." TARGET_DB=newdru_restore \
        python scripts/restore_backup.py 2026-11-15.json.gz
Add --restore to write. Restoring into a database that already has data is
refused unless you also pass --replace (which empties each collection first).
Tip: restore into a NEW database name, check it, then point the app at it.
"""
import gzip
import os
import sys

from bson import json_util
from pymongo import MongoClient


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write, replace = "--restore" in sys.argv, "--replace" in sys.argv
    if len(args) != 1:
        sys.exit(__doc__)
    with gzip.open(args[0], "rt", encoding="utf-8") as f:
        data = json_util.loads(f.read())
    if data.get("format") != "newdru-backup-v1":
        sys.exit("Not a NEWDRU backup file.")
    cols = data["collections"]
    print(f"Backup from {data.get('created_at')}: "
          + ", ".join(f"{k}={len(v)}" for k, v in sorted(cols.items())))
    if not write:
        print("Dry run only. Add --restore to write.")
        return
    url, name = os.environ.get("TARGET"), os.environ.get("TARGET_DB")
    if not url or not name:
        sys.exit("Set TARGET (Mongo URL) and TARGET_DB (database name).")
    db = MongoClient(url)[name]
    busy = [c for c in cols if db[c].estimated_document_count()]
    if busy and not replace:
        sys.exit(f"Target already has data in: {', '.join(busy)}. Use a new TARGET_DB or add --replace.")
    for c, docs in cols.items():
        if replace:
            db[c].delete_many({})
        if docs:
            db[c].insert_many(docs)
        print(f"restored {c}: {len(docs)}")
    print("Done. Indexes are rebuilt automatically when the app starts.")


if __name__ == "__main__":
    main()
