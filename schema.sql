-- Bangla Basket -- Postgres schema (Phase 1 data-layer port).
--
-- Design: one table per former Mongo collection.  Each table stores the
-- full document in a JSONB ``doc`` column (exact keys, nesting, explicit
-- nulls, and absent-vs-null distinctions preserved) plus extracted
-- primary-key columns for the business IDs the API exposes.  The provider
-- (backend/pgdb.py) reads and writes ``doc``; the key columns exist so
-- Postgres enforces uniqueness.  ``seq`` reproduces Mongo's insertion
-- order for find_one / update_one / delete_one ("first match" semantics).
--
-- This file is idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF
-- NOT EXISTS) and is applied by the Docker entrypoint before the backend
-- starts, and by scripts/migrate_mongo_to_postgres.py (which assumes the
-- schema already exists).
--
-- TTL policy (deliberate, matches the old code's intent):
--   * user_sessions / otp_challenges / password_resets had Mongo TTL
--     indexes.  Postgres has no TTL indexes, so expiry is enforced by the
--     sweeper job (scripts/sweep_expired.py) AND by the existing
--     application checks (session expiry is checked on every request).
--   * export_files deliberately has NO expiry deletion: the old code
--     removed its TTL index on purpose and expires downloads LAZILY on
--     read.  Do not add a sweeper rule for it.

-- ---------------------------------------------------------------- admins
CREATE TABLE IF NOT EXISTS admins (
    email TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS admins_doc_gin ON admins USING GIN (doc);

-- ------------------------------------------------------- analytics_events
CREATE TABLE IF NOT EXISTS analytics_events (
    ledger_id TEXT PRIMARY KEY,  -- surrogate; docs carry no business ID
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS analytics_events_doc_gin
    ON analytics_events USING GIN (doc);
CREATE INDEX IF NOT EXISTS analytics_events_type_ts
    ON analytics_events ((doc ->> 'type'), (doc ->> 'ts'));

-- ------------------------------------------------------ business_settings
CREATE TABLE IF NOT EXISTS business_settings (
    key TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS business_settings_doc_gin
    ON business_settings USING GIN (doc);

-- ------------------------------------------------------- catering_packages
CREATE TABLE IF NOT EXISTS catering_packages (
    package_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS catering_packages_doc_gin
    ON catering_packages USING GIN (doc);

-- ------------------------------------------------- catering_quote_requests
CREATE TABLE IF NOT EXISTS catering_quote_requests (
    request_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS catering_quote_requests_doc_gin
    ON catering_quote_requests USING GIN (doc);

-- ----------------------------------------------------------------- coupons
CREATE TABLE IF NOT EXISTS coupons (
    code TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS coupons_doc_gin ON coupons USING GIN (doc);
CREATE INDEX IF NOT EXISTS coupons_owner_user_id
    ON coupons ((doc ->> 'owner_user_id'));

-- ------------------------------------------------------ coupon_redemptions
CREATE TABLE IF NOT EXISTS coupon_redemptions (
    code TEXT NOT NULL,
    user_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    seq BIGSERIAL,
    doc JSONB NOT NULL,
    PRIMARY KEY (code, user_id, order_id)
);
CREATE INDEX IF NOT EXISTS coupon_redemptions_doc_gin
    ON coupon_redemptions USING GIN (doc);
CREATE INDEX IF NOT EXISTS coupon_redemptions_order_id
    ON coupon_redemptions ((doc ->> 'order_id'));

-- ----------------------------------------------------- delivery_applications
CREATE TABLE IF NOT EXISTS delivery_applications (
    app_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS delivery_applications_doc_gin
    ON delivery_applications USING GIN (doc);

-- --------------------------------------------------------- delivery_partners
CREATE TABLE IF NOT EXISTS delivery_partners (
    partner_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS delivery_partners_doc_gin
    ON delivery_partners USING GIN (doc);

-- ------------------------------------------------------------- export_files
CREATE TABLE IF NOT EXISTS export_files (
    token TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS export_files_doc_gin ON export_files USING GIN (doc);
-- Plain index only (no TTL): expiry stays lazy on download.
CREATE INDEX IF NOT EXISTS export_files_expires_at
    ON export_files ((doc ->> 'expires_at'));

-- ------------------------------------------------------------------ grocery
CREATE TABLE IF NOT EXISTS grocery (
    item_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS grocery_doc_gin ON grocery USING GIN (doc);

-- --------------------------------------------------------------- master_menu
CREATE TABLE IF NOT EXISTS master_menu (
    item_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS master_menu_doc_gin ON master_menu USING GIN (doc);
CREATE INDEX IF NOT EXISTS master_menu_category_cuisine
    ON master_menu ((doc ->> 'category'), (doc ->> 'cuisine'));

-- -------------------------------------------------------------------- orders
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_doc_gin ON orders USING GIN (doc);
CREATE INDEX IF NOT EXISTS orders_user_id ON orders ((doc ->> 'user_id'));

-- ------------------------------------------------------------ otp_challenges
CREATE TABLE IF NOT EXISTS otp_challenges (
    email TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS otp_challenges_doc_gin
    ON otp_challenges USING GIN (doc);
-- Unique on email (mirrors the old unique index).  No TTL index: the
-- sweeper handles expiry.
CREATE UNIQUE INDEX IF NOT EXISTS otp_challenges_email_unique
    ON otp_challenges ((doc ->> 'email'));

-- ------------------------------------------------------------ password_resets
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS password_resets_doc_gin
    ON password_resets USING GIN (doc);

-- ------------------------------------------------------- payment_transactions
CREATE TABLE IF NOT EXISTS payment_transactions (
    session_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS payment_transactions_doc_gin
    ON payment_transactions USING GIN (doc);

-- -------------------------------------------------------------- points_ledger
CREATE TABLE IF NOT EXISTS points_ledger (
    ledger_id TEXT PRIMARY KEY,  -- surrogate; docs carry no business ID
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS points_ledger_doc_gin
    ON points_ledger USING GIN (doc);
CREATE INDEX IF NOT EXISTS points_ledger_user_ts
    ON points_ledger ((doc ->> 'user_id'), (doc ->> 'ts'));

-- --------------------------------------------------------------- pricing_zones
CREATE TABLE IF NOT EXISTS pricing_zones (
    zone_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS pricing_zones_doc_gin
    ON pricing_zones USING GIN (doc);

-- ---------------------------------------------------------------- push_tokens
CREATE TABLE IF NOT EXISTS push_tokens (
    user_id TEXT NOT NULL,
    token TEXT NOT NULL,
    seq BIGSERIAL,
    doc JSONB NOT NULL,
    PRIMARY KEY (user_id, token)
);
CREATE INDEX IF NOT EXISTS push_tokens_doc_gin ON push_tokens USING GIN (doc);

-- -------------------------------------------------------------- thali_packages
CREATE TABLE IF NOT EXISTS thali_packages (
    package_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS thali_packages_doc_gin
    ON thali_packages USING GIN (doc);

-- -------------------------------------------------------------- user_sessions
CREATE TABLE IF NOT EXISTS user_sessions (
    session_token TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS user_sessions_doc_gin
    ON user_sessions USING GIN (doc);
CREATE INDEX IF NOT EXISTS user_sessions_user_id
    ON user_sessions ((doc ->> 'user_id'));
-- No TTL index on expires_at: the sweeper handles expiry.

-- ---------------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS users_doc_gin ON users USING GIN (doc);
-- Partial-unique email: uniqueness enforced ONLY when email is a real
-- string, so phone-only (admin-created) customers never collide.  This
-- mirrors the old partial index the startup code recreates.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_partial_unique
    ON users ((doc ->> 'email')) WHERE (doc ->> 'email') IS NOT NULL;

-- --------------------------------------------------------------- weekly_menus
CREATE TABLE IF NOT EXISTS weekly_menus (
    week_start TEXT PRIMARY KEY,
    seq BIGSERIAL,
    doc JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS weekly_menus_doc_gin ON weekly_menus USING GIN (doc);
