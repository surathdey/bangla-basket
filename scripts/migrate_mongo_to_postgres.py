#!/usr/bin/env python3
"""Migrate Bangla Basket data from MongoDB to Postgres (rehearsal/cutover).

READS from Mongo (never writes to it) and writes to the target Postgres
database (which must already have schema.sql applied -- the Docker
entrypoint does this, or run ``psql $DATABASE_URL -f schema.sql`` first).

Usage (run from the refactor root; needs pymongo + asyncpg installed):
    pip install pymongo asyncpg
    python scripts/migrate_mongo_to_postgres.py \
        --mongo-uri mongodb://localhost:27017 \
        --mongo-db bongconnekt_db \
        --pg-dsn postgresql://bangla:bangla@localhost:5432/banglabasket \
        [--collections users orders grocery] [--truncate] [--verify N]

Behaviour:
  * Documents are copied in Mongo natural order (insertion order), so the
    Postgres ``seq`` column preserves first-match semantics.
  * ``_id`` ObjectIds become their hex string (the provider generates hex
    ids for new documents, and serializers strip ``_id`` either way).
  * Datetimes become ISO-8601 strings in JSONB; the provider converts the
    per-table datetime fields back to datetimes on read.
  * Re-runs are safe: rows whose business-ID primary key already exists
    are skipped (ON CONFLICT DO NOTHING), unless --truncate is given.
  * --verify N re-reads N documents per collection from both databases and
    deep-compares them (minus ``_id``, keys sorted). Any mismatch aborts
    with a non-zero exit code.

GATED: do not run this against the production Postgres until the migration
rehearsal (plan Phase 4) is approved. It never touches the live MongoDB
beyond reading it.
"""
import argparse
import asyncio
import json
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from pgdb import TABLES  # noqa: E402

try:
    import asyncpg  # noqa: E402
    from bson import ObjectId  # noqa: E402
    from pymongo import MongoClient  # noqa: E402
except ImportError as e:
    sys.exit(f"missing dependency for migration only (not the server): {e}\n"
             "Run: pip install pymongo asyncpg")


def _json_default(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _normalize(doc):
    """Mongo document -> JSON-plain document (for comparison + storage)."""
    return json.loads(json.dumps(doc, default=_json_default))


def _pk_values(table, doc):
    pk_fields = TABLES[table][0]
    if not pk_fields:
        return [uuid.uuid4().hex]  # points_ledger surrogate
    values = []
    for field in pk_fields:
        value = doc.get(field)
        if value is None:
            raise ValueError(f"{table}: document missing PK field {field!r}: "
                             f"{str(doc)[:200]}")
        values.append(value)
    return values


def _pk_columns(table):
    return TABLES[table][0] or ["ledger_id"]


async def migrate(mongo_uri, mongo_db, pg_dsn, collections, truncate,
                  verify_n):
    mongo = MongoClient(mongo_uri)
    mdb = mongo[mongo_db]
    pool = await asyncpg.create_pool(pg_dsn, min_size=1, max_size=4)
    try:
        for table in collections:
            cols = _pk_columns(table)
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
            if truncate:
                async with pool.acquire() as conn:
                    await conn.execute(f'DELETE FROM "{table}"')
            cursor = mdb[table].find()
            inserted = skipped = 0
            batch = []
            mongo_docs = []
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for doc in cursor:
                        norm = _normalize(doc)
                        batch.append((*_pk_values(table, norm),
                                      json.dumps(norm, ensure_ascii=False)))
                        mongo_docs.append(norm)
                        if len(batch) >= 500:
                            status = await conn.executemany(
                                f'INSERT INTO "{table}" ({col_list}, doc) '
                                f"VALUES ({placeholders}, "
                                f"${len(cols) + 1}::jsonb) "
                                f"ON CONFLICT DO NOTHING",
                                batch)
                            inserted += int(status.split()[-1])
                            batch = []
                    if batch:
                        status = await conn.executemany(
                            f'INSERT INTO "{table}" ({col_list}, doc) '
                            f"VALUES ({placeholders}, "
                            f"${len(cols) + 1}::jsonb) "
                            f"ON CONFLICT DO NOTHING",
                            batch)
                        inserted += int(status.split()[-1])
            skipped = len(mongo_docs) - inserted
            print(f"{table}: mongo={len(mongo_docs)} "
                  f"inserted={inserted} skipped(existing)={skipped}")
            if verify_n and mongo_docs:
                step = max(1, len(mongo_docs) // verify_n)
                sample = mongo_docs[::step][:verify_n]
                async with pool.acquire() as conn:
                    for want in sample:
                        pk = _pk_values(table, want)
                        cond = " AND ".join(
                            f'"{c}" = ${i + 1}'
                            for i, c in enumerate(cols))
                        row = await conn.fetchrow(
                            f'SELECT doc FROM "{table}" WHERE {cond}',
                            *pk)
                        assert row is not None, \
                            f"{table}: migrated row missing for {pk}"
                        got = json.loads(row["doc"])
                        want_cmp = {k: v for k, v in want.items()
                                    if k != "_id"}
                        got_cmp = {k: v for k, v in got.items()
                                   if k != "_id"}
                        assert want_cmp == got_cmp, \
                            (f"{table}: mismatch for {pk}\n"
                             f"mongo={json.dumps(want_cmp, sort_keys=True)[:500]}\n"
                             f"pg   ={json.dumps(got_cmp, sort_keys=True)[:500]}")
                print(f"{table}: verified {len(sample)} sampled documents OK")
    finally:
        await pool.close()
        mongo.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--mongo-db", required=True)
    parser.add_argument("--pg-dsn", required=True)
    parser.add_argument("--collections", nargs="*", default=sorted(TABLES),
                        choices=sorted(TABLES))
    parser.add_argument("--truncate", action="store_true",
                        help="delete target rows first (rehearsal re-runs)")
    parser.add_argument("--verify", type=int, default=0, metavar="N",
                        help="deep-compare N sampled docs per collection")
    args = parser.parse_args()
    asyncio.run(migrate(args.mongo_uri, args.mongo_db, args.pg_dsn,
                        args.collections, args.truncate, args.verify))
    print("migration done")


if __name__ == "__main__":
    main()
