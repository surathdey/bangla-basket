#!/usr/bin/env python3
"""Sweep expired TTL documents (replaces Mongo TTL indexes).

Postgres has no TTL indexes, so a scheduled job runs this script (e.g.
hourly via cron on the host, or a Compose sidecar -- see README):

    python scripts/sweep_expired.py \
        --pg-dsn postgresql://bangla:bangla@localhost:5432/banglabasket

Deletes rows whose ``expires_at`` (ISO string in ``doc``) is in the past
from: user_sessions, otp_challenges, password_resets.

DELIBERATELY NOT swept: export_files. The old code removed its TTL index
on purpose -- downloads expire LAZILY when read. Do not add it here.
"""
import argparse
import asyncio

import asyncpg

TABLES = ("user_sessions", "otp_challenges", "password_resets")


async def main_async(pg_dsn):
    pool = await asyncpg.create_pool(pg_dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            for table in TABLES:
                status = await conn.execute(
                    f'DELETE FROM "{table}" WHERE '
                    f"(doc ->> 'expires_at') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}T' "
                    f"AND (doc ->> 'expires_at')::timestamptz < now()")
                print(f"{table}: deleted {status.split()[-1]} expired rows")
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-dsn", required=True)
    args = parser.parse_args()
    asyncio.run(main_async(args.pg_dsn))


if __name__ == "__main__":
    main()
