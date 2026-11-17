"""Nightly backfill: re-capture Stripe fees for paid card payments whose fee
is missing (the balance transaction lagged the ~8s retry window at payment
time, so _capture_stripe_fee gave up). Idempotent — only touches
payment_transactions rows with status "paid" and no stripe_fee_cents; uses
the production _capture_stripe_fee path, which writes fee+net to BOTH the
transaction row (Overview card) and the orders row (drill-down table).
Safe to run repeatedly.

Usage (inside the backend container):
    python /app/backend/backfill_stripe_fees.py [--dry-run]
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app/backend")

from server import _capture_stripe_fee, db, log  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="list candidates without calling Stripe")
    args = parser.parse_args()

    checked = backfilled = failed = 0
    async for tx in db.payment_transactions.find(
        {"status": "paid", "stripe_fee_cents": None}, {"_id": 0}
    ):
        checked += 1
        session_id = tx.get("session_id")
        order_id = tx.get("order_id")
        if not session_id or not order_id:
            log.warning(
                f"fee backfill: tx missing session/order id, skipping: {tx}")
            failed += 1
            continue
        order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
        if not order:
            log.warning(f"fee backfill: order {order_id} not found, skipping")
            failed += 1
            continue
        if args.dry_run:
            print(f"would backfill: order {order_id} session {session_id}")
            continue
        try:
            await _capture_stripe_fee(session_id, order_id, order)
        except Exception as e:
            log.warning(f"fee backfill: order {order_id} failed: {e}")
            failed += 1
            continue
        after = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
        if isinstance(after.get("stripe_fee_cents"), int):
            backfilled += 1
            print(
                f"backfilled: order {order_id} "
                f"fee {after['stripe_fee_cents']} "
                f"net {after.get('stripe_net_cents')}")
        else:
            log.warning(
                f"fee backfill: order {order_id} fee still unavailable "
                f"after capture")
            failed += 1
    print(
        f"stripe fee backfill: checked={checked} backfilled={backfilled} "
        f"failed={failed} dry_run={args.dry_run}")
    await db.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
