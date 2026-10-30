# Bangla Basket — Refactored Backend (LOCAL ONLY)

A local-only refactor of the Bong Connect / Bangla Basket backend
(`surathdey/bongconnekt`, branch `main`, head `3f519b4` 2026-10-18)
from MongoDB + Emergent managed services to **Postgres + MinIO + direct
Resend / Expo / Google Auth**, packaged with Docker.

**Status: local build for review. NOT deployed, NOT pushed anywhere.**
The live deployment (systemd `bongconnekt` on AWS, MongoDB on-instance,
`banglabasket.ca`) is untouched and stays live until a separately
approved cutover. The new GitHub repo does not exist yet; when the user
creates it and grants access, this tree is what gets checked in.

## What changed (and what did not)

| Area | Before | After |
|---|---|---|
| Database | MongoDB via Motor | Postgres 16 via asyncpg (`backend/pgdb.py`) |
| Object storage | Emergent Managed Object Storage | MinIO, S3-compatible (`backend/storage_client.py`) |
| Email | Emergent email relay | Direct Resend (`backend/email_client.py`) |
| Push | Emergent Push relay | Direct Expo Push API (`server.py`: `send_push`, `/register-push`) |
| Google auth | Emergent Auth relay only | Relay kept + direct Google ID-token path (`/api/auth/session` accepts `id_token`, `backend/google_auth.py`) |
| LLM key | `EMERGENT_LLM_KEY` (Emergent SDK) | Unchanged (admin-time menu enrichment only; see "Decisions") |
| Twilio / Drive / exports / Fernet crypto | As-is | Unchanged |
| Platform hub poller / billing proxy | As-is | Unchanged (currently unconfigured: `brand.json` has an empty `platform.api_key`, so the poller is a no-op) |
| **API contract** | — | **UNCHANGED: same routes minus the deleted `/dev/seed` (upstream: 139 `@api` router routes + 3 app-level `/api` routes = 142 total; this tree: 141), same request/response JSON shapes, same field names, no `_id` leakage** |

Route handlers, serializers, and response shapes are byte-identical by
design: only the data-access layer and the external-service clients were
rewritten. The mobile apps need no update.

## Layout

```
brand.json                  Brand config (copied verbatim; platform.api_key is empty)
schema.sql                  Postgres DDL (one table per former collection)
Dockerfile                  Backend image (schema applied at container start)
docker-compose.yml          Parallel-test stack (backend + Postgres + MinIO + nginx)
nginx.conf                  Reverse proxy (port 8080 in the parallel phase)
.env.example                Placeholders ONLY -- never real values
backend/
  server.py                 Ported app (init/imports, push, auth, /dev/seed removed)
  pgdb.py                   Motor-compatible Postgres provider (the data layer)
  storage_client.py         MinIO client (same init/put/get interface)
  email_client.py           Direct Resend client (same send/is_configured interface)
  google_auth.py            Direct Google ID-token verification (new, additive)
  requirements.txt          motor/pymongo removed, asyncpg added
  web_dist/                 Expo web bundle (served by the backend at /)
  ...                       All other modules unchanged
scripts/
  migrate_mongo_to_postgres.py   Mongo -> Postgres data migration (gated)
  migrate_objects_to_minio.py    Object-store copy + byte-verify (gated)
  sweep_expired.py               TTL sweeper (replaces Mongo TTL indexes)
tests/
  test_pgdb.py              Provider tests (real Postgres)
  test_routes.py            Route-parity + boot/shape tests (real Postgres)
  route_inventory_upstream.json  The 139-route inventory these tests check against
```

## Design decisions (and deviations from the plan)

1. **Documents stay documents.** Each Postgres table is
   `(business-ID PK columns, seq, doc JSONB)`, where `doc` holds the
   full document exactly as Mongo stored it. This is a deliberate
   deviation from the plan's fully-normalized column layout, because the
   API freeze requires byte-identical shapes -- including absent-vs-null
   distinctions (`$unset` really removes a key), nested structures
   (`items_snapshot`, `lines`, `variants`, `address`), and mixed
   string/datetime fields. A columnar split would have risked silent
   shape changes in dozens of places. Normalization can be layered later
   without any API change. GIN indexes on `doc` + PK + the old index
   inventory (as `(doc->>'field')` btrees) cover the query patterns.
2. **Datetimes round-trip.** JSON has no datetime type, so datetimes are
   stored as ISO strings and converted back to aware `datetime` objects
   on read for the per-table datetime fields in `pgdb.TABLES`
   (models + direct `datetime.now(timezone.utc)` assignments, audited
   field by field). Fields the code stores as strings stay strings
   (weekly-menu `created_at`, tracking-event `ts`, integration
   `last_test_at`).
3. **Exact update counts.** `modified_count` counts only rows whose
   document actually changed (`IS DISTINCT FROM`). The Stripe webhook
   relies on this (`modified_count == 0` means "already paid").
   `matched_count` is counted separately. `update_one`/`delete_one`/
   `find_one` use `ORDER BY seq LIMIT 1` to reproduce Mongo's
   first-in-insertion-order semantics.
4. **No per-request transactions in this pass.** Each Motor call maps to
   one statement (or a locate-then-act pair), preserving old observable
   behaviour. The plan's aspirational transaction wrapping is deferred.
5. **`/dev/seed` deleted** (plan recommendation). It was an open,
   unauthenticated seeder. The upstream route inventory therefore has
   142 routes total (139 router + 3 app-level); this tree has 141, and the parity check asserts exactly
   that difference.
6. **Push tokens now live locally.** The old relay kept tokens; the new
   `/register-push` upserts `{user_id, token, platform}` into
   `push_tokens`, and `send_push` resolves user_ids through it before
   posting to Expo (100 messages per call, non-blocking with warning
   logs, same as before). The app already calls `/register-push`, so no
   app change is needed. `idempotency_key` is accepted but unused --
   Expo has no idempotency.
7. **Port fixes found by the test suite (2026-10-30).** (a) Shutdown called
   the removed Motor client's `close()`; now `await db.close()`. (b) All
   `httpx.AsyncClient` constructions pass `trust_env=False`: the sandbox
   `no_proxy` contains bracketed IPv6 entries httpx 0.28 cannot parse
   (raises `InvalidURL` at import); the live box has no proxy variables,
   so this changes nothing there. (c) `pgdb` update paths build update
   expressions with a fresh placeholder builder (the single-statement
   UPDATE has no filter clause, so reusing the filter builder left `$1`
   unreferenced and Postgres rejected it). (d) Datetime filter values are
   bound as `datetime` objects, not ISO strings, because asyncpg encodes
   by the prepared statement's `timestamptz` type.
8. **Upstream test suite and deploy scripts removed.** `backend/tests/`
   (47 live-preview integration tests importing pymongo/Motor and
   hitting a preview backend) and `backend/scripts/deploy_ec2.sh` (which
   rsyncs to the live box -- the frozen deploy path) are NOT in this
   tree; they are preserved in the pristine upstream copy only. The new
   suite is `tests/` (16 tests, all passing 2026-10-30).
7. **`/auth/session` gained an additive `id_token` field** (old
   `session_token` path untouched). `session_token` became optional so
   direct-login clients can send only `id_token`. Wiring the app to use
   it is future gated work (needs the Google OAuth client + app update).
8. **Stale branding fixed where it leaked:** email `from_name` default
   was `"Curry & Co."` -- now the brand name (`Bangla Basket`); the
   server module docstring likewise. Outbound email display changes
   from the stale name to the real one; nothing else about email changed.
9. **Kept as-is on purpose:** the mocked `send_email` in `server.py`
   (logs only; used for order-cancel + delivery-application notices --
   real mail for those was never sent), `menu_ai.py` (Emergent LLM SDK
   import is already optional with a fallback-text path; admin-time
   bulk-upload enrichment only), `platform_client.py` /
   `billing_client.py` (hub currently unconfigured), the legacy
   one-off helper scripts (`build_*.py`, `fix_*.py`, `import_*.py`,
   `migrate_*.py`, `seed_*.py` -- still Motor-based; they are NOT part
   of the server runtime and are ported only if reused).
10. **Grocery variants stay JSONB** (plan suggested a separate table).
    No code path queries variants at the DB level (`$elemMatch` count
    is zero; variant access is in-memory), so JSONB preserves order and
    shape exactly.
11. **requirements.txt:** `motor` + `pymongo` removed, `asyncpg==0.32.0`
    added, everything else identical -- including the `litellm` wheel
    served from an Emergent CDN URL. Switching that wheel to PyPI
    `litellm` is a follow-up (it is only a transitive dep of the
    commented-out `emergentintegrations` package; nothing imports it
    directly today).

## Running locally (Docker)

```sh
cp .env.example .env   # fill in real values; never commit .env
docker compose up -d --build
curl localhost:8080/health
curl localhost:8080/api/grocery/categories
docker compose logs -f backend
```

The stack publishes only port 8080. Postgres, MinIO, and the backend are
reachable only inside the Docker network, so this can run alongside the
live deployment on the same box without port conflicts.

## Running locally (no Docker, for development)

```sh
# Start Postgres 16 somehow (local install, or the Compose postgres service)
psql "$DATABASE_URL" -f schema.sql
cd backend
pip install -r requirements.txt
JWT_SECRET=dev-only-secret ADMIN_PASSWORD=dev-only-password \
  uvicorn server:app --port 8001
```

## Verification (what was actually run)

All checks below were run against this tree on the build VM. Commands
and outcomes are recorded here; re-run them before any cutover.

```sh
# 1. Syntax: every backend module compiles.
python3 -m py_compile backend/*.py

# 2. Route parity: ported routes == upstream routes minus /dev/seed.
#    (141 routes; method + path, exact set equality -- router inventory +
#     3 app-level /api routes; see tests/test_routes.py.)
python3 - <<'EOF'
import ast, json
# ... (asserts set equality; full script in the verification log)
EOF

# 3. Provider + route tests against a real local Postgres 16 cluster:
#    initdb a throwaway cluster, apply schema.sql, then:
BB_TEST_DSN=postgresql://bangla:bangla@127.0.0.1:54399/banglabasket_test \
  python -m pytest tests/ -q
```

Test coverage: filters (`$eq/$ne/$in/$nin/$gt/$lt/$regex/$or/$and`,
null-vs-missing, dotted array filters), projections (incl. positional
`items.$`), sort/limit/skip, `$set` (incl. dotted + positional `$inc`),
`$push`/`$each`/`$pull`/`$unset`, exact `modified_count`, upserts,
`replace_one` `_id` preservation, `find_one_and_update` pre-update
return, first-match-only deletes, all four aggregate pipelines, datetime
round-trips, partial-unique email, index shims, booted-app route
inventory via OpenAPI, guest-session + `/auth/me` flows, grocery list
shape with no `_id` leakage.

**Not container-tested here:** this VM had no Docker, so the Compose
stack could not be booted here. Validated statically instead: Compose
YAML structure, Dockerfile instruction order (schema copy present,
uploads dirs, CMD applies schema then serves), nginx proxy config, and
`.env.example` completeness against every `os.environ.get` in the code.
Docker boot + end-to-end parity testing is required on the target box
before cutover (Phase 5).

## Migration rehearsal (gated -- NOT run yet)

```sh
# 1. Data (reads Mongo, writes ONLY the target Postgres):
pip install pymongo asyncpg
python scripts/migrate_mongo_to_postgres.py \
  --mongo-uri mongodb://127.0.0.1:27017 --mongo-db bongconnekt_db \
  --pg-dsn postgresql://bangla:bangla@postgres:5432/banglabasket \
  --verify 20
# 2. Objects (reads the old store, writes MinIO, byte-verifies):
EMERGENT_LLM_KEY='<from the old deploy env, transient>' \
python scripts/migrate_objects_to_minio.py \
  --pg-dsn postgresql://bangla:bangla@postgres:5432/banglabasket
# 3. Local uploads (NOT object store): rsync /app/backend/uploads (274MB
#    on the live box) into the Compose `uploads` volume at cutover.
# 4. TTL sweeper (hourly cron on the host after cutover):
python scripts/sweep_expired.py --pg-dsn <dsn>
```

## Gated items (need the user's explicit go-ahead / inputs)

1. **Docker install on the live box** (absent today; sudo available).
2. **Instance RAM:** 913Mi total / 472Mi free vs. a parallel stack
   (Postgres + MinIO + backend + nginx) -- measure before cutover; the
   live box may need a resize or a Postgres memory cap.
3. **Secrets/credentials for migration (values never stored here):**
   `INTEGRATIONS_FERNET_KEY` (byte-for-byte, or stored Twilio/Drive
   credentials become undecryptable), Stripe keys, Resend key, Google
   OAuth client ID (for the `id_token` path), Expo access token
   (optional), MinIO credentials, platform `api_key` (only if the hub
   is to be used).
4. **GitHub Actions workflow freeze:** the old repo's
   `deploy-backend.yml` deploys `backend/` to the instance on main
   merges. This refactor must never touch `main` of `surathdey/bongconnekt`;
   the NEW repo's workflow is future work.
5. **Cutover go-ahead + window** (Phase 6): stop the systemd service,
   repoint nginx to the Compose stack (80/443 + TLS via the existing
   certbot/ACME webroot layout), run migrations, verify, then
   decommission Emergent hosting (Phase 7).
6. **Open questions:** Stripe live vs. test keys; store-app vs. repo
   drift (do the store apps bundle any Emergent-hosted URLs?);
   object-bucket size on the old store (live box `uploads/` is 274MB of
   LOCAL files, not the bucket); `menu_ai` direct-LLM replacement vs.
   keeping the Emergent key; the app update to use `id_token` login.
