"""Copy every collection from the old database (Emergent) into the new one (MongoDB Atlas).

Safe to run after the new app has already started (it creates starter logins and
counters on first start) and safe to run twice: documents are merged, not duplicated.

    SOURCE_MONGO_URL=...  SOURCE_DB=...  TARGET_MONGO_URL=...  TARGET_DB=... \
        python3 scripts/migrate_db.py            # dry run: counts only, changes nothing
    ... python3 scripts/migrate_db.py --copy     # real copy (merge)

How it merges:
  * users       matched by email; the old app's account replaces the starter one
                (so old bills still point at the right cashier). Anyone with the
                old public demo password is forced to pick a new one at first sign-in.
  * counters    the higher number wins, so new invoice / credit-note numbers never clash
  * everything else: matched by _id and replaced (re-running just refreshes it)
  * rate_limits, login_attempts: skipped (temporary data)

Connection strings come from environment variables only. Afterwards, change the
Atlas database password (it was used here) and every staff password.
"""
import argparse
import os
import sys

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

SKIP = {"rate_limits", "login_attempts"}


def copy_users(src, dst, write: bool) -> dict:
    stats = {"replaced_starter": 0, "copied": 0}
    for u in src.users.find({}):
        email = (u.get("email") or "").lower().strip()
        existing = dst.users.find_one({"email": email}) if email else None
        if existing:
            stats["replaced_starter"] += 1
            if write:
                dst.users.delete_one({"_id": existing["_id"]})
        else:
            stats["copied"] += 1
        if write:
            dst.users.replace_one({"_id": u["_id"]}, u, upsert=True)
    return stats


def copy_counters(src, dst, write: bool) -> dict:
    stats = {"merged": 0}
    for c in src.counters.find({}):
        cur = dst.counters.find_one({"_id": c["_id"]}) or {}
        seq = max(int(c.get("seq") or 0), int(cur.get("seq") or 0))
        stats["merged"] += 1
        if write:
            dst.counters.update_one({"_id": c["_id"]}, {"$set": {"seq": seq}}, upsert=True)
    return stats


def copy_generic(src, dst, name: str, write: bool) -> dict:
    stats = {"docs": 0, "conflicts": 0}
    for doc in src[name].find({}, no_cursor_timeout=True):
        stats["docs"] += 1
        if write:
            try:
                dst[name].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            except DuplicateKeyError:
                stats["conflicts"] += 1
    return stats


def run(src, dst, write: bool) -> int:
    names = sorted(n for n in src.list_collection_names() if not n.startswith("system."))
    print(f"{len(names)} collections found in source")
    problems = 0
    for name in names:
        if name in SKIP:
            print(f"  {name:28} skipped (temporary data)")
            continue
        n_src = src[name].estimated_document_count()
        if name == "users":
            st = copy_users(src, dst, write)
        elif name == "counters":
            st = copy_counters(src, dst, write)
        else:
            st = copy_generic(src, dst, name, write)
        n_dst = dst[name].count_documents({})
        flag = ""
        if st.get("conflicts"):
            problems += 1
            flag = f"  {st['conflicts']} CONFLICT(S): same SKU/barcode/number already in target, check by hand"
        print(f"  {name:28} source={n_src:>7}  target now={n_dst:>7}  {st}{flag}")
    print(("DONE" if not problems else f"DONE WITH {problems} PROBLEM(S): check above") if write
          else "Dry run only, nothing changed. Add --copy to copy.")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", action="store_true", help="actually copy (default is a dry run)")
    args = ap.parse_args()
    try:
        src = MongoClient(os.environ["SOURCE_MONGO_URL"])[os.environ["SOURCE_DB"]]
        dst = MongoClient(os.environ["TARGET_MONGO_URL"])[os.environ["TARGET_DB"]]
    except KeyError as e:
        print(f"Missing environment variable {e}")
        return 2
    return run(src, dst, args.copy)


if __name__ == "__main__":
    sys.exit(main())
