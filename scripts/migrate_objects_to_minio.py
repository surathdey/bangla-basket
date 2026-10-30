#!/usr/bin/env python3
"""Copy catalog images from Emergent Managed Object Storage to MinIO.

The old storage has NO list API, so object paths are enumerated from the
database instead: every string in every Postgres document that looks like
an object-store reference (``/api/files/<path>`` or a bare
``bongconnekt/...`` path) is collected, then each object is downloaded
from the old store and uploaded to MinIO, with a byte-equality check
(download-after-upload compared to the original bytes).

Usage (run from the refactor root; needs asyncpg + boto3 + requests):
    pip install asyncpg boto3 requests
    EMERGENT_LLM_KEY='<key-from-the-old-deploy-env>' \\
    python scripts/migrate_objects_to_minio.py \
        --pg-dsn postgresql://bangla:bangla@localhost:5432/banglabasket \
        [--minio-endpoint http://localhost:9000] [--bucket bangla-basket] \
        [--dry-run]

Notes:
  * EMERGENT_LLM_KEY is used ONLY as the old storage's init key, read from
    the environment at run time. It is never written to any file or log.
  * The old store is only READ. MinIO uploads overwrite silently, so
    re-runs are safe; objects that already match byte-for-byte are skipped.
  * Local /app/backend/uploads files (delivery proofs, AI menu photos) are
    NOT object-store objects -- copy that directory separately (rsync) at
    cutover; this script covers only the object store.
  * GATED: rehearsal/cutover only, like the data migration.
"""
import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

import asyncpg
import boto3
import requests

OLD_BASE = "https://integrations.emergentagent.com/objstore/api/v1/storage"


def collect_paths(docs):
    """Recursively find object-store paths in decoded documents."""
    paths = set()

    def walk(value):
        if isinstance(value, str):
            if value.startswith("/api/files/"):
                paths.add(value[len("/api/files/"):])
            elif value.startswith("bongconnekt/"):
                paths.add(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for doc in docs:
        walk(doc)
    return paths


def old_storage_key():
    key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        sys.exit("EMERGENT_LLM_KEY is required (old storage init key). "
                 "Pass it via the environment for this run only.")
    resp = requests.post(f"{OLD_BASE}/init", json={"emergent_key": key},
                         timeout=30)
    resp.raise_for_status()
    return resp.json()["storage_key"]


async def main_async(args):
    pool = await asyncpg.create_pool(args.pg_dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT doc FROM grocery UNION ALL "
                "SELECT doc FROM master_menu UNION ALL "
                "SELECT doc FROM weekly_menus UNION ALL "
                "SELECT doc FROM thali_packages UNION ALL "
                "SELECT doc FROM catering_packages UNION ALL "
                "SELECT doc FROM business_settings")
        import json
        docs = [json.loads(r["doc"]) for r in rows]
    finally:
        await pool.close()
    paths = sorted(collect_paths(docs))
    print(f"found {len(paths)} object-store paths in the database")
    if args.dry_run:
        for p in paths:
            print(f"  would copy: {p}")
        return
    skey = old_storage_key()
    s3 = boto3.client(
        "s3", endpoint_url=args.minio_endpoint,
        aws_access_key_id=args.minio_access_key or None,
        aws_secret_access_key=args.minio_secret_key or None,
        region_name="us-east-1",
        config=boto3.session.Config(signature_version="s3v4"))
    copied = skipped = failed = 0
    for path in paths:
        try:
            resp = requests.get(f"{OLD_BASE}/objects/{path}",
                                headers={"X-Storage-Key": skey}, timeout=120)
            if resp.status_code == 404:
                print(f"  MISSING in old store (skipped): {path}")
                failed += 1
                continue
            resp.raise_for_status()
            data = resp.content
            try:
                existing = s3.get_object(Bucket=args.bucket, Key=path)
                if existing["Body"].read() == data:
                    skipped += 1
                    continue
            except Exception:
                pass  # not present (or unreadable) -> upload
            s3.put_object(Bucket=args.bucket, Key=path, Body=data)
            check = s3.get_object(Bucket=args.bucket, Key=path)["Body"].read()
            if check != data:
                print(f"  BYTE MISMATCH after upload: {path}")
                failed += 1
                continue
            copied += 1
        except Exception as e:
            print(f"  FAILED {path}: {e}")
            failed += 1
    print(f"done: copied={copied} already-identical={skipped} failed={failed}")
    print("(uploads were byte-compared after download, not just size-checked.)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-dsn", required=True)
    parser.add_argument("--minio-endpoint",
                        default=os.environ.get("MINIO_ENDPOINT",
                                               "http://localhost:9000"))
    parser.add_argument("--bucket",
                        default=os.environ.get("MINIO_BUCKET",
                                               "bangla-basket"))
    parser.add_argument("--minio-access-key",
                        default=os.environ.get("MINIO_ACCESS_KEY", ""))
    parser.add_argument("--minio-secret-key",
                        default=os.environ.get("MINIO_SECRET_KEY", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
