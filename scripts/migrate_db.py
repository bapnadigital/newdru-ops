"""Copy every collection from the old database (Emergent) to the new one (MongoDB Atlas).

Run ONCE during the move to mynewdru.in, at a quiet time (stop using the POS for
~10 minutes). Connection strings are read from environment variables only, so
nothing secret is typed into a file or committed:

    SOURCE_MONGO_URL=...  SOURCE_DB=...  TARGET_MONGO_URL=...  TARGET_DB=... \
        python3 scripts/migrate_db.py            # dry run: counts only
    ... python3 scripts/migrate_db.py --copy     # real copy

After the copy, change the Atlas database password (the old one was used here).
Refuses to overwrite a target collection that already has data unless --force.
"""
import argparse
import os
import sys

from pymongo import MongoClient

BATCH = 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", action="store_true", help="actually copy (default is a dry run)")
    ap.add_argument("--force", action="store_true", help="allow copying into non-empty collections")
    args = ap.parse_args()

    try:
        src = MongoClient(os.environ["SOURCE_MONGO_URL"])[os.environ["SOURCE_DB"]]
        dst = MongoClient(os.environ["TARGET_MONGO_URL"])[os.environ["TARGET_DB"]]
    except KeyError as e:
        print(f"Missing environment variable {e}")
        return 2

    names = sorted(n for n in src.list_collection_names() if not n.startswith("system."))
    print(f"{len(names)} collections found in source")
    problems = 0
    for name in names:
        n_src = src[name].estimated_document_count()
        n_dst = dst[name].estimated_document_count()
        line = f"  {name:32} source={n_src:>8}  target={n_dst:>8}"
        if not args.copy:
            print(line)
            continue
        if n_dst and not args.force:
            print(line + "  SKIPPED (target not empty; use --force)")
            problems += 1
            continue
        batch = []
        for doc in src[name].find({}, no_cursor_timeout=True):
            batch.append(doc)
            if len(batch) >= BATCH:
                dst[name].insert_many(batch, ordered=False)
                batch = []
        if batch:
            dst[name].insert_many(batch, ordered=False)
        n_after = dst[name].count_documents({})
        ok = n_after >= n_src
        problems += 0 if ok else 1
        print(f"  {name:32} copied {n_src:>8} -> {n_after:>8}  {'OK' if ok else 'MISMATCH'}")

    if args.copy:
        print("DONE" if not problems else f"DONE WITH {problems} PROBLEM(S): check above")
    else:
        print("Dry run only. Add --copy to copy.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
