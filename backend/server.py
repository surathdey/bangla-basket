"""
Bangla Basket — Backend API
FastAPI + Postgres + Google Auth + Stripe Checkout + Expo Push
"""
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request, Depends, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from pgdb import PgDatabase
import stripe
import os
import asyncio
import logging
import uuid
import re
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone, timedelta, date

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# --- Brand config (name/emails/region — one file to swap on rebrand)
from brand import (
    BRAND_NAME, BRAND_LEGAL_NAME, BRAND_EMAIL_FROM,
    BRAND_ADMIN_EMAIL, BRAND_SUPPORT_EMAIL, BRAND_GUEST_DOMAIN,
    BRAND_DELIVERY_EMAIL, BRAND_REGION,
    as_dict as brand_as_dict,
)

# --- Env
# --- Postgres (replaces MongoDB/Motor; see backend/pgdb.py)
# DATABASE_URL is the only database setting. A localhost default keeps
# local runs working without a .env file; Docker Compose and
# production always set it explicitly.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://bangla:bangla@localhost:5432/banglabasket")
# Stripe secret — required in every environment that processes card payments.
# Do NOT provide a source default here (deployment policy: no secrets in source).
# In preview/dev, `backend/.env` is expected to set STRIPE_API_KEY (Stripe test
# key is fine). In production, the deployment environment provides the
# live/test key. If completely unset, the checkout endpoint will refuse to charge.
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
# Optional Expo access token (raises push rate limits when set).
EXPO_ACCESS_TOKEN = os.environ.get("EXPO_ACCESS_TOKEN", "")
# Brand-driven defaults with env overrides (environment variables can still
# override for production without touching brand.json).
EMAIL_FROM = os.environ.get("EMAIL_FROM", BRAND_EMAIL_FROM)

# Emergent Auth session-exchange endpoint. Overridable via env for future
# self-hosted auth backends; the default is the managed Emergent Auth relay.
EMERGENT_AUTH_URL = os.environ.get(
    "EMERGENT_AUTH_URL",
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
)

# ---- Auth secrets — MUST come from env in production. -----------------
# Both local dev (backend/.env) and the deployment environment are expected
# to provide these. We fail fast on prod-only deploys where env vars are missing.
JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_ALG = "HS256"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", BRAND_ADMIN_EMAIL)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

if not JWT_SECRET:
    raise RuntimeError(
        "SECURITY: JWT_SECRET env var is required. Set it in backend/.env "
        "for local dev or in the deployment environment for production."
    )
if not ADMIN_PASSWORD:
    raise RuntimeError(
        "SECURITY: ADMIN_PASSWORD env var is required. Set it in backend/.env "
        "for local dev or in the deployment environment for production."
    )

# --- Admin auth deps
from passlib.context import CryptContext
from jose import jwt, JWTError

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Postgres
db = PgDatabase(DATABASE_URL)  # pool created lazily on first use

# --- App
app = FastAPI(title=f"{BRAND_NAME} API")
api = APIRouter(prefix="/api")

# ----------------------------------------------------------------------
# Kubernetes health / readiness probes.
# Deployment ingress hits `GET /health` (root, not /api/health) — MUST return
# 200 OK, otherwise K8s marks the pod NotReady and stops routing traffic to it.
# Keep these responses cheap (no DB calls, no external I/O).
# ----------------------------------------------------------------------
@app.get("/health", include_in_schema=False)
async def _health():
    return {"status": "ok", "service": "bongconnekt-api"}


@app.get("/healthz", include_in_schema=False)
async def _healthz():
    # Alternate probe path used by some K8s configurations.
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def _root():
    # If the Expo web bundle exists (production deploy), serve the SPA entry
    # so admins hitting the root see the app; otherwise return JSON status
    # (K8s probes rely on this being fast).
    if WEB_DIST.exists() and (WEB_DIST / "index.html").exists():
        return FileResponse(str(WEB_DIST / "index.html"), headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        })
    return {"service": "bongconnekt-api", "status": "ok", "docs": "/docs", "web_bundle": "missing"}


# --- Uploaded images (AI-generated menu photos, etc.) served under /api/uploads/*
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", "/app/backend/uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
(UPLOADS_DIR / "menu").mkdir(parents=True, exist_ok=True)
(UPLOADS_DIR / "delivery").mkdir(parents=True, exist_ok=True)
(UPLOADS_DIR / "grocery").mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# --- Persistent object storage (MinIO) for catalog/menu images ------------
# Objects live in a bucket shared across the user's environments, so images
# uploaded from preview are readable from production. Reads are streamed back
# here (no public storage URLs). These are PUBLIC catalog images (no auth).
import storage_client as _obj

_STORAGE_CT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}


@app.on_event("startup")
async def _init_object_storage():
    try:
        await run_in_threadpool(_obj.init_storage)
        log.info("[storage] object storage initialised")
    except Exception as e:
        log.warning(f"[storage] init skipped: {e}")


@api.get("/files/{path:path}", include_in_schema=False)
async def serve_object(path: str):
    """Stream a public catalog image from object storage."""
    from fastapi.responses import Response
    try:
        data, ct = await run_in_threadpool(_obj.get_object, path)
    except Exception:
        raise HTTPException(404, "File not found")
    if ct in (None, "application/octet-stream"):
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        ct = _STORAGE_CT.get(ext, "application/octet-stream")
    return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------
# SPA static serving — production + preview.
# The Expo web bundle can live in one of two locations:
#   1. /app/backend/web_dist/       (production — bundled inside backend so it
#                                    ships with the K8s image regardless of
#                                    whether the frontend directory is copied)
#   2. /app/frontend/dist/          (preview — created by `expo export` during
#                                    local dev / `yarn install` postinstall)
# We prefer (1) so production always has a working admin webapp. Any refresh
# in preview automatically re-syncs (1) via the sync helper below.
# ---------------------------------------------------------------
_WEB_DIST_PROD = Path("/app/backend/web_dist")
_WEB_DIST_PREVIEW = Path("/app/frontend/dist")

def _resolve_web_dist() -> Optional[Path]:
    for p in (_WEB_DIST_PROD, _WEB_DIST_PREVIEW):
        if p.exists() and (p / "index.html").exists():
            return p
    return None

WEB_DIST = _resolve_web_dist() or _WEB_DIST_PROD  # used by handlers below

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("curryco")

# --- Direct Expo Push (replaces the Emergent Push relay)
# Tokens are stored locally by /register-push (push_tokens collection);
# send_push resolves user_ids -> tokens here, then posts to Expo directly.
_push_client = httpx.AsyncClient(
    base_url="https://exp.host",
    timeout=10.0,
    trust_env=False,
)


async def _expo_tokens_for(recipients: List[str]) -> List[str]:
    tokens: List[str] = []
    user_ids = []
    for r in recipients:
        if r.startswith("ExponentPushToken[") or r.startswith("ExpoPushToken["):
            tokens.append(r)
        else:
            user_ids.append(r)
    if user_ids:
        cur = db.push_tokens.find({"user_id": {"$in": user_ids}},
                                  {"_id": 0, "token": 1})
        async for row in cur:
            if row.get("token"):
                tokens.append(row["token"])
    return list(dict.fromkeys(tokens))  # de-duplicate, preserving order


async def send_push(recipients: List[str], data: dict, idempotency_key: Optional[str] = None):
    if not recipients:
        return
    if "title" not in data or "message" not in data:
        raise ValueError("push data must include title and message")
    try:
        tokens = await _expo_tokens_for(recipients)
    except Exception as e:
        log.warning(f"push token lookup error (non-blocking): {e}")
        return
    if not tokens:
        return
    messages = [{"to": t, "title": data["title"], "body": data["message"],
                 "data": {k: v for k, v in data.items()
                          if k not in ("title", "message")}}
                for t in tokens]
    headers = {}
    if EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {EXPO_ACCESS_TOKEN}"
    try:
        for i in range(0, len(messages), 100):  # Expo accepts max 100/call
            resp = await _push_client.post("/--/api/v2/push/send",
                                           json=messages[i:i + 100],
                                           headers=headers)
            if resp.status_code >= 400:
                log.warning(f"expo push non-2xx {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"expo push error (non-blocking): {e}")


# --- Email (MOCKED — logs only)
async def send_email(to: str, subject: str, body: str):
    log.info(f"[EMAIL MOCK] to={to} subject={subject!r} body={body[:120]}...")


# --- Stripe hosted Checkout for card payments.
# Stripe Checkout handles cards and wallet payments; COD + Interac remain
# available. Enable/disable per deployment via business_settings.payment_methods.
def _stripe():
    """Configure and return the Stripe SDK, or 503 if no key is configured."""
    if not STRIPE_API_KEY:
        raise HTTPException(
            503,
            "Card payments are not configured on this deployment. Please use Cash on Delivery or Interac e-Transfer.",
        )
    stripe.api_key = STRIPE_API_KEY
    return stripe


# ==========================================================
# MODELS
# ==========================================================
class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    phone: Optional[str] = None
    default_address: Optional[dict] = None
    loyalty_points: int = 0
    referral_code: str = ""          # e.g. "BB4F2K9A" — auto-assigned on login
    weekly_meal_streak: int = 0      # completed weekly-meal orders since last reward
    email_verified: bool = False
    has_logged_in: bool = False          # flips true on first successful login (first-time coupon trigger)
    first_login_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "customer"  # customer | admin | delivery_partner | guest


class MenuItem(BaseModel):
    item_id: str = Field(default_factory=lambda: f"item_{uuid.uuid4().hex[:10]}")
    name: str
    description: str
    price_cents: int
    image_url: str
    category: str  # "veg", "non-veg", "rice", "dessert", "starter", "curry"
    tags: List[str] = []
    is_featured: bool = False


class MasterMenuItem(BaseModel):
    """Permanent menu item repository. Reused across weekly menus."""
    item_id: str = Field(default_factory=lambda: f"mi_{uuid.uuid4().hex[:10]}")
    name: str
    short_description: str = ""
    full_description: str = ""
    category: str  # starter | main-veg | main-non-veg | dessert | beverage | rice | curry | side | bread
    cuisine: str = "bengali"  # bengali | north-indian | south-indian | indo-chinese | fusion
    default_price_cents: int
    cost_price_cents: int = 0  # visible to super admin only (client should mask for others)
    image_url: str = ""  # public URL OR data URI (base64)
    extra_images: List[str] = []
    veg_type: str = "vegetarian"  # vegetarian | non-vegetarian | eggitarian
    spice_level: str = "medium"  # mild | medium | hot
    allergens: List[str] = []  # dairy | nuts | seafood | gluten
    is_active: bool = True
    always_available: bool = False  # orderable any time, independent of weekly menu
    prep_notes: str = ""
    kitchen_notes: str = ""
    display_order: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WeeklyMenuLine(BaseModel):
    """Line in a weekly menu — references a MasterMenuItem with optional overrides."""
    line_id: str = Field(default_factory=lambda: f"wl_{uuid.uuid4().hex[:10]}")
    master_item_id: str
    price_override_cents: Optional[int] = None
    availability: str = "available"  # available | low_inventory | sold_out
    stock_limit: Optional[int] = None
    stock_used: int = 0
    is_featured: bool = False
    display_order: int = 0
    # Per-week à-la-carte visibility. When a new week copies ALL master items,
    # they are added hidden (is_visible=False) and the admin turns on the ones
    # they want customers to see this week. Manually-added lines default visible.
    is_visible: bool = True


class WeeklyMenuPackage(BaseModel):
    """Weekly-menu combo: customer picks X items from an eligible pool for a flat price."""
    package_id: str = Field(default_factory=lambda: f"wpkg_{uuid.uuid4().hex[:10]}")
    name: str = "This Week's Combo"
    description: str = ""
    price_cents: int = 0
    pick_count: int = 3  # X — number of items customer must pick
    eligible_master_ids: List[str] = []  # subset of master items in this week's lines; empty = all
    # Per-item surcharge (in cents) added on TOP of the flat package price for every portion
    # the customer picks of that specific item. e.g. {"mi_mutton": 500, "mi_ilish": 1000}.
    item_surcharges_cents: Dict[str, int] = {}
    image_url: str = ""
    # ---- Composition-based pricing (Mustard Garden weekly plan) ----
    # When pricing_mode == "composition", the flat `price_cents` is ignored and
    # the total is chosen by the veg/non-veg makeup of the customer's picks:
    #   all picks vegetarian            -> veg_price_cents
    #   all picks non-veg (incl. egg)   -> nonveg_price_cents
    #   any mix of veg + non-veg        -> mixed_price_cents
    # Egg dishes (veg_type == "eggitarian") count as NON-VEG here.
    pricing_mode: str = "flat"          # "flat" | "composition"
    veg_price_cents: int = 0
    mixed_price_cents: int = 0
    nonveg_price_cents: int = 0
    # Display-only freebies shown with the plan; customer CANNOT select these.
    complimentary_master_ids: List[str] = []
    # ---- Fixed-composition plan config (used when pricing_mode == "composition") ----
    # A selection is valid only when its veg/non-veg makeup matches ONE of:
    #   all-veg      -> veg_pick_count veg dishes
    #   all-non-veg  -> nonveg_pick_count non-veg dishes
    #   mixed        -> mixed_veg_count veg + mixed_nonveg_count non-veg
    # When mixed_* are 0 the legacy "any mix at pick_count" behaviour is kept.
    max_per_dish: int = 0          # cap on how many of the same dish (0 = unlimited)
    veg_pick_count: int = 0        # dishes required for the all-veg plan (0 → pick_count)
    nonveg_pick_count: int = 0     # dishes required for the all-non-veg plan (0 → pick_count)
    mixed_veg_count: int = 0       # veg dishes in the mixed plan
    mixed_nonveg_count: int = 0    # non-veg dishes in the mixed plan


class WeeklyMenu(BaseModel):
    menu_id: str = Field(default_factory=lambda: f"menu_{uuid.uuid4().hex[:10]}")
    week_start: str  # ISO date string of Sunday (YYYY-MM-DD)
    week_end: Optional[str] = None
    title: str
    description: str = ""
    banner_image_url: str = ""
    items: List[MenuItem] = []  # legacy embedded — deprecated but kept for back-compat
    lines: List[WeeklyMenuLine] = []  # new: references to Master Menu with overrides
    # Week-level complimentary dishes (display-only freebies). Shown to customers
    # ONLY when the Weekly Package is enabled. Selected from the Master Menu.
    complimentary_master_ids: List[str] = []
    published: bool = True
    status: str = "published"  # draft | scheduled | published
    # Weekly-menu mode toggles (v3)
    alacarte_enabled: bool = True
    package_enabled: bool = False
    package: Optional[WeeklyMenuPackage] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaymentMethodConfig(BaseModel):
    """Per-payment-method config. Each method has its own enable/HST toggle plus method-specific settings."""
    enabled: bool = True
    tax_enabled: bool = True   # apply HST to orders using this method?
    # method-specific (all optional):
    publishable_key: Optional[str] = None   # Stripe
    secret_key: Optional[str] = None        # Stripe (SENSITIVE — never returned to public /settings)
    client_id: Optional[str] = None         # PayPal
    client_secret: Optional[str] = None     # PayPal (SENSITIVE)
    email: Optional[str] = None             # Interac e-Transfer email address
    instructions: Optional[str] = None      # Free-text shown to customer (e.g. Interac note pattern)


class BusinessSettings(BaseModel):
    key: str = "default"
    business_name: str = BRAND_NAME
    kitchen_address: str = "6941 Derry Rd West, Milton, ON, Canada"
    phone: str = ""
    email: str = BRAND_EMAIL_FROM
    operating_hours: str = "Sun–Thu ordering · Fri/Sat delivery"
    # Structured schedule (0=Sun, 1=Mon, ..., 6=Sat). Drives the customer-app
    # "orders open/closed" banner and next-delivery-slot logic.
    ordering_days: List[int] = [0, 1, 2, 3, 4]   # Sun–Thu
    delivery_days: List[int] = [5, 6]            # Fri–Sat
    delivery_areas: List[str] = ["Toronto", "Mississauga", "Brampton", "Markham"]
    default_delivery_fee_cents: int = 599
    minimum_order_cents: int = 0
    # Distance-based delivery fee tiers, measured (driving) from `kitchen_address`.
    # Each tier: {max_km, fee_cents}. A destination is charged the first tier whose
    # max_km it falls within (ascending). Beyond the largest tier, `delivery_fee_over_max_cents`.
    delivery_fee_tiers: List[dict] = [
        {"max_km": 20, "fee_cents": 0},
        {"max_km": 40, "fee_cents": 500},
        {"max_km": 75, "fee_cents": 1000},
    ]
    delivery_fee_over_max_cents: int = 1500
    # ---- Zone-based delivery (Bangla Basket delivery plan, Oct 2026) ----
    # When delivery_cycles is set, delivery slots come from these cycles
    # (delivery_day / cutoff_day use 0=Sun..6=Sat JS convention; cutoff_hour
    # is Toronto local time). Empty = legacy delivery_days fallback.
    delivery_cycles: List[dict] = []
    # Free delivery: subtotal at/above threshold → delivery fee waived.
    # Remote cities (Barrie, London) use the higher threshold.
    free_delivery_threshold_cents: int = 15000
    free_delivery_remote_threshold_cents: int = 25000
    free_delivery_remote_cities: List[str] = ["Barrie", "London"]
    # Restaurant owner notification targets. Every new order + every delivery
    # sends a copy here (email always; SMS if a phone + Twilio are set).
    notify_email: str = ""
    notify_phone: str = ""
    # Customer-app home-hero tagline. Explains the ordering model in one line,
    # e.g. "We take orders all week and deliver on Monday." Configurable per
    # tenant because different restaurants operate on different schedules.
    home_hero_tagline: str = "Order anytime this week — we deliver every weekend."
    # Customer-app home-hero headline + subtitle (editable in Admin → Settings).
    home_hero_title: str = "Your neighbourhood halal grocery — delivered."
    home_hero_subtitle: str = "Fresh meat, fish, sweets & everyday groceries, delivered to your door."
    # Free-delivery ribbon shown at the top of the customer app + website.
    delivery_ribbon_enabled: bool = True
    delivery_ribbon_text: str = "Free delivery on orders over $150"
    # Home-page product sections (customer app). Toggle from Admin → Settings.
    # Best Sellers = featured groceries; New Items = most recently added groceries.
    home_best_sellers_enabled: bool = True
    home_new_items_enabled: bool = True
    # When True, groceries are browseable but not purchasable — every Add button
    # shows a disabled "Coming soon" label (app + website portal).
    grocery_coming_soon: bool = False
    # When True, the customer app + website show a small "Your location detected —
    # <City>" banner at the top (driven by expo-location / browser geolocation).
    # Primarily a QA/testing aid to confirm location detection is working.
    location_banner_enabled: bool = False
    # When True, grocery prices are hidden until the customer's location is
    # resolved ("price gating"). Default OFF → prices always visible.
    price_gating_enabled: bool = False
    # Optional add-on service offered in cart for cut / by-weight fish.
    fish_service_enabled: bool = True
    fish_service_name: str = "Fish Scaling & Cleaning"
    fish_service_desc: str = "We'll scale and clean your fish before delivery."
    fish_service_price_cents: int = 299
    # Global "Always Available" menu — master item ids orderable any time,
    # independent of the weekly plan. Admin picks these from the Master Menu on
    # a dedicated screen; changes reflect on the customer app immediately.
    always_available_master_ids: List[str] = []
    # Legacy global tax toggle — kept as a fallback for methods that don't specify their own.
    tax_enabled: bool = True
    tax_rate_bps: int = 1300  # basis points; 1300 = 13% HST
    tax_label: str = "HST"
    currency: str = BRAND_REGION.get("currency", "CAD")
    company_info: str = ""
    # ---- Loyalty program (Admin → Settings → Loyalty) ----
    # Earn rate: loyalty points awarded per $1 of order subtotal (before tax/fees/discount).
    loyalty_earn_points_per_dollar: float = 1.0
    # Redemption rate: how many points equal $1 of discount (e.g. 25 → 25 pts = $1).
    loyalty_redeem_points_per_dollar: int = 25
    # ---- First-time coupon (Admin → Settings → Coupons) ----
    # When enabled, a unique percentage coupon is auto-issued on a customer's first login.
    first_time_coupon_enabled: bool = True
    first_time_coupon_percent: int = 20
    # Per-payment-method configuration
    # Per-payment-method configuration. Stripe (card + Apple/Google Pay via
    # hosted Checkout) is enabled alongside COD + Interac.
    payment_methods: Dict[str, PaymentMethodConfig] = Field(default_factory=lambda: {
        "stripe":  PaymentMethodConfig(enabled=True,  tax_enabled=True),
        "paypal":  PaymentMethodConfig(enabled=False, tax_enabled=True),
        "cod":     PaymentMethodConfig(enabled=True,  tax_enabled=True),
        "interac": PaymentMethodConfig(enabled=True,  tax_enabled=True,
                                        email=BRAND_EMAIL_FROM,
                                        instructions="Please note your order ID in the message field."),
    })


class CateringChoiceGroup(BaseModel):
    """A group of dishes where customer must pick N (min–max) options."""
    group_id: str = Field(default_factory=lambda: f"grp_{uuid.uuid4().hex[:8]}")
    title: str  # e.g. "Snack", "3 Veg Items", "Dessert"
    subtitle: str = ""  # e.g. "Choose Any 3"
    min_select: int = 1
    max_select: int = 1
    option_master_ids: List[str] = []  # references to MasterMenuItem.item_id
    display_order: int = 0


class CateringUpgradeTier(BaseModel):
    """Alternate per-person price tier that may override choice-group counts."""
    tier_id: str = Field(default_factory=lambda: f"tier_{uuid.uuid4().hex[:8]}")
    title: str  # "Base tier" | "Snack + Tea upgrade"
    subtitle: str = ""
    per_person_cents: int
    # Overrides group min/max in this tier: {group_id: {"min_select": N, "max_select": N}}
    group_overrides: Dict[str, Dict[str, int]] = {}
    is_default: bool = True


class CateringPremiumItem(BaseModel):
    """Marks a master item as premium — customer pays extra per-person if selected."""
    master_item_id: str
    upcharge_per_person_cents: int


class CateringPackage(BaseModel):
    package_id: str = Field(default_factory=lambda: f"cat_{uuid.uuid4().hex[:10]}")
    name: str
    tagline: str = ""
    description: str = ""
    emoji: str = "🍽️"
    perfect_for: str = ""  # e.g. "Weddings · Puja Celebrations"
    price_cents: int = 0  # per-person price (fallback if no tiers)
    min_guests: int = 10
    image_url: str = ""
    includes: List[str] = []  # legacy free-text (back-compat + always-included display)
    included_master_ids: List[str] = []  # always-served master items
    choice_groups: List[CateringChoiceGroup] = []
    upgrade_tiers: List[CateringUpgradeTier] = []
    premium_items: List[CateringPremiumItem] = []
    is_custom_quote: bool = False  # if True, show contact form instead of Add-to-Bag
    contact_email: str = ""
    contact_phone: str = ""
    is_featured: bool = False
    is_active: bool = True
    sort_order: int = 0


class ThaliProteinOption(BaseModel):
    option_id: str = Field(default_factory=lambda: f"tp_{uuid.uuid4().hex[:8]}")
    name: str                      # e.g. "Mutton", "Chicken", "Fish"
    price_cents: int = 0           # per-person price when this protein is chosen


class ThaliPackage(BaseModel):
    """Party / event thali — a bulk per-person meal. Separate from catering_packages."""
    package_id: str = Field(default_factory=lambda: f"th_{uuid.uuid4().hex[:10]}")
    name: str
    thali_type: str = "veg"        # "veg" | "non_veg"
    description: str = ""
    per_person_price_cents: int = 0  # used for veg (flat); for non_veg the chosen protein price applies
    protein_options: List[ThaliProteinOption] = []  # non_veg only
    includes: List[str] = []       # contents list, one per line
    min_guests: int = 25
    image_url: str = ""
    is_active: bool = True
    sort_order: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GroceryVariant(BaseModel):
    variant_id: str
    title: str = "Standard"
    price_cents: int = 0
    compare_at_cents: int = 0
    available: bool = True
    sku: str = ""
    weight_g: int = 0
    image_url: str = ""              # cut sample photo shown in the option selector


class GroceryItem(BaseModel):
    item_id: str = Field(default_factory=lambda: f"gr_{uuid.uuid4().hex[:12]}")
    title: str
    handle: str = ""
    description: str = ""
    category: str = "Grocery & Pantry"
    subcategory: str = ""  # e.g. Fish → "Block" | "Cut" | "By Weight"
    all_categories: str = ""
    price_cents: int = 0
    compare_at_cents: int = 0
    unit: str = ""
    image_url: str = ""
    images: List[str] = []
    vendor: str = ""
    tags: List[str] = []
    variants: List[GroceryVariant] = []
    has_variants: bool = False
    on_sale: bool = False
    in_stock: bool = True
    is_active: bool = True
    is_featured: bool = False
    sort_order: int = 0
    source_id: str = ""
    product_url: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Coupon(BaseModel):
    code: str
    discount_type: str = "percent"  # "percent" | "fixed"
    value: int  # percent (0-100) OR cents (for fixed)
    active: bool = True
    min_order_cents: int = 0
    description: str = ""
    expiry: Optional[str] = None            # ISO date "YYYY-MM-DD"; None = never expires
    usage_limit: int = 0                    # total redemptions allowed across all customers; 0 = unlimited
    per_customer_limit: int = 0             # redemptions allowed per customer; 0 = unlimited
    first_time_only: bool = False           # only redeemable by customers who've never ordered
    applies_to: str = "all"                 # all | grocery_only | weekly_meal_only | all_except_weekly_meal
    used_count: int = 0                     # total redemptions so far
    owner_user_id: Optional[str] = None     # set for auto-issued personal (first-time) coupons
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CateringSelection(BaseModel):
    """Customer's picks when adding a catering package to bag."""
    tier_id: Optional[str] = None
    # {group_id: [master_item_id, ...]}
    group_selections: Dict[str, List[str]] = {}
    # Master item IDs from the premium list — each adds its upcharge per person.
    premium_selections: List[str] = []


class OrderItemIn(BaseModel):
    kind: str  # "menu" | "catering" | "weekly_package" | "grocery"
    ref_id: str  # item_id | package_id | weekly_menu_id
    quantity: int
    variant_id: Optional[str] = None  # for grocery variants
    catering_guest_count: Optional[int] = None  # for catering only
    catering_selections: Optional[CateringSelection] = None
    package_selections: Optional[List[str]] = None  # weekly_package master_ids picked
    thali_guest_count: Optional[int] = None  # for thali only
    thali_protein_option_id: Optional[str] = None  # non-veg thali protein pick
    thali_delivery_date: Optional[str] = None  # requested party date (ISO yyyy-mm-dd)


class Address(BaseModel):
    # Optional recipient name attached to this address. When present, the
    # admin Orders list uses it as `customer_name` (see the resolver in
    # /admin/orders + admin_orders/list). Lets guests type their real name
    # at checkout so orders don't show up as "Guest 1", "Guest 2".
    name: Optional[str] = ""
    email: Optional[str] = ""   # customer email captured at checkout (order confirmation + invoice)
    line1: str
    line2: Optional[str] = ""
    city: str = "Toronto"
    province: str = "ON"
    postal_code: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    instructions: Optional[str] = ""


class DeliverySlot(BaseModel):
    date: str  # YYYY-MM-DD
    window: str  # "friday_evening" | "saturday_morning"


class QuoteOrderReq(BaseModel):
    """Pre-checkout quote. Phone optional (customer may not have filled it yet)."""
    items: List[OrderItemIn]
    address: Address
    slot: DeliverySlot
    phone: Optional[str] = ""
    coupon_code: Optional[str] = None
    referral_code: Optional[str] = None
    redeem_points: int = 0
    special_instructions: Optional[str] = ""
    payment_method: str = "card"


class CreateOrderReq(BaseModel):
    items: List[OrderItemIn]
    address: Address
    slot: DeliverySlot
    phone: str  # REQUIRED — contact phone captured at checkout
    coupon_code: Optional[str] = None
    referral_code: Optional[str] = None
    redeem_points: int = 0  # points to redeem (1 pt = 1 cent)
    special_instructions: Optional[str] = ""
    payment_method: str = "card"  # "card" (Stripe) | "cod" (Cash on Delivery)
    # The public origin the customer is on (e.g. https://xyz.preview...). Used as a
    # fallback to build absolute invoice/tracking links in SMS/email.
    client_base_url: Optional[str] = None


class Order(BaseModel):
    order_id: str = Field(default_factory=lambda: f"ord_{uuid.uuid4().hex[:10]}")
    user_id: str
    items_snapshot: List[dict]
    address: dict
    slot: dict
    phone: str = ""
    subtotal_cents: int
    delivery_fee_cents: int
    tax_cents: int = 0
    tax_label: str = "HST"
    discount_cents: int
    referral_discount_cents: int = 0
    points_redeemed_cents: int
    points_redeemed: int = 0   # actual loyalty points consumed (balance deducted by this)
    total_cents: int
    coupon_code: Optional[str] = None
    referral_code: Optional[str] = None
    referrer_user_id: Optional[str] = None
    special_instructions: Optional[str] = ""
    payment_method: str = "card"  # "card" | "cod"
    status: str = "pending_payment"
    payment_status: str = "pending"
    stripe_session_id: Optional[str] = None
    points_awarded: int = 0
    refund_status: Optional[str] = None  # None | "requested" | "refunded"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tracking_events: List[dict] = []
    # Public origin captured at checkout for building absolute invoice/tracking links.
    public_base_url: Optional[str] = None
    # ---- Delivery assignment (v3) ----
    delivery_partner_id: Optional[str] = None  # DeliveryPartner.partner_id
    delivery_status: Optional[str] = None      # unassigned | assigned | picked_up | on_the_way | arrived | delivered
    delivery_partner_name: Optional[str] = None
    delivery_partner_phone: Optional[str] = None
    delivery_partner_lat: Optional[float] = None
    delivery_partner_lng: Optional[float] = None
    delivery_partner_updated_at: Optional[datetime] = None
    delivery_eta_seconds: Optional[int] = None
    delivery_eta_updated_at: Optional[datetime] = None
    delivery_route_order: Optional[int] = None  # index in optimized route
    delivery_proof_photo_url: Optional[str] = None  # proof-of-delivery photo

class DeliveryPartner(BaseModel):
    partner_id: str = Field(default_factory=lambda: f"dp_{uuid.uuid4().hex[:10]}")
    name: str
    email: str
    phone: str = ""
    vehicle: str = "car"           # "car" | "bike" | "scooter"
    password_hash: str = ""
    is_active: bool = True
    # Live location
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    current_location_updated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeliveryPartnerApplication(BaseModel):
    app_id: str = Field(default_factory=lambda: f"dp_{uuid.uuid4().hex[:10]}")
    user_id: Optional[str] = None
    full_name: str
    email: str
    phone: str
    city: str
    vehicle: str  # "car" | "bike" | "scooter"
    availability: str  # "part_time" | "full_time" | "weekends"
    experience: Optional[str] = ""
    status: str = "submitted"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PushRegisterReq(BaseModel):
    user_id: str
    platform: str
    device_token: str


# ==========================================================
# AUTH
# ==========================================================
async def _current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    exp = session.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Session expired")
    user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user_doc)


class SessionInReq(BaseModel):
    session_token: Optional[str] = None
    id_token: Optional[str] = None


@api.post("/auth/guest")
async def create_guest_session():
    """Create a lightweight guest user + 7-day session token. No email verification."""
    guest_id = f"guest_{uuid.uuid4().hex[:12]}"
    user = User(
        user_id=guest_id,
        email=f"{guest_id}@{BRAND_GUEST_DOMAIN}",
        name="Guest",
        role="guest",
    )
    await db.users.insert_one(user.model_dump())
    token = f"guest-{uuid.uuid4().hex}"
    session_doc = {
        "session_token": token,
        "user_id": user.user_id,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    await db.user_sessions.insert_one(session_doc)
    return {"session_token": token, "user": user.model_dump()}


from google_auth import verify_google_id_token as _verify_google_id_token


@api.post("/auth/session")
async def create_session(req: SessionInReq):
    """Exchange a token for our session (validates + upserts user).

    Two paths, same response shape:
    - ``session_token``: the legacy Emergent Auth relay exchange (unchanged).
    - ``id_token``: a direct Google ID token, verified locally against
      GOOGLE_CLIENT_ID (the self-hosted path; no relay involved).
    """
    if req.session_token:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as hc:
            r = await hc.get(
                EMERGENT_AUTH_URL,
                headers={"X-Session-ID": req.session_token},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session token")
        data = r.json()
    elif req.id_token:
        try:
            data = _verify_google_id_token(req.id_token)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid Google ID token")
        data["session_token"] = f"sess_{uuid.uuid4().hex}"
    else:
        raise HTTPException(status_code=401, detail="session_token or id_token required")
    email = data["email"]
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user = User(**existing)
    else:
        user = User(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            email=email,
            name=name,
            picture=picture,
        )
        await db.users.insert_one(user.model_dump())

    session_doc = {
        "session_token": data["session_token"],
        "user_id": user.user_id,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    await db.user_sessions.update_one(
        {"session_token": data["session_token"]},
        {"$set": session_doc},
        upsert=True,
    )
    await _handle_first_login(user.user_id)
    fresh = await db.users.find_one({"user_id": user.user_id}, {"_id": 0}) or user.model_dump()
    return {"session_token": data["session_token"], "user": fresh}


@api.get("/auth/me")
async def me(user: User = Depends(_current_user)):
    return user.model_dump()


@api.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# ==========================================================
# EMAIL OTP LOGIN (passwordless) + first-login / loyalty helpers
# ==========================================================
import hmac as _hmac, hashlib as _hashlib, secrets as _secrets

OTP_TTL_MIN = 10
OTP_RESEND_COOLDOWN_SEC = 60
OTP_MAX_RESENDS = 3
OTP_MAX_FAILED = 5


def _norm_email(v: str) -> str:
    return (v or "").strip().casefold()


def _otp_digest(email: str, code: str) -> str:
    pepper = os.environ.get("OTP_PEPPER", "")
    return _hmac.new(pepper.encode(), f"{email}:{code}".encode(), _hashlib.sha256).hexdigest()


def _new_otp() -> str:
    return f"{_secrets.randbelow(1_000_000):06d}"


async def _new_session_token(user_id: str, prefix: str = "sess", days: int = 30) -> str:
    token = f"{prefix}-{uuid.uuid4().hex}"
    await db.user_sessions.insert_one({
        "session_token": token, "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=days),
    })
    return token


async def _ensure_referral_code(user_id: str) -> Optional[str]:
    """Assign a referral code on first sight (idempotent). Format BB + 6 hex."""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "referral_code": 1})
    if not u:
        return None
    if (u.get("referral_code") or "").strip():
        return u["referral_code"]
    for _ in range(20):
        code = "BB" + _secrets.token_hex(3).upper()
        if not await db.users.find_one({"referral_code": code}, {"_id": 0}):
            await db.users.update_one({"user_id": user_id}, {"$set": {"referral_code": code}})
            return code
    return None


async def _resolve_referral(code: Optional[str], user, snapshots):
    """Referral programme: 10% off GROCERY lines when a valid referrer code is
    entered. Returns (discount_cents, referrer_user_id_or_None, error_or_None).
    The referrer reward coupon is issued separately at order confirmation."""
    if not code:
        return 0, None, None
    ref = await db.users.find_one({"referral_code": code.strip().upper()},
                                  {"_id": 0, "user_id": 1, "role": 1})
    if not ref or ref.get("role") == "guest":
        return 0, None, "Invalid referral code."
    if ref["user_id"] == getattr(user, "user_id", None):
        return 0, None, "You can't use your own referral code."
    base = sum(int(l.get("line_total_cents", 0) or 0) for l in (snapshots or []) if l.get("kind") == "grocery")
    return base * 10 // 100, ref["user_id"], None


async def _issue_first_time_coupon(user: dict) -> Optional[dict]:
    settings = await _get_settings()
    if not settings.get("first_time_coupon_enabled", True):
        return None
    existing = await db.coupons.find_one({"owner_user_id": user["user_id"]}, {"_id": 0})
    if existing:
        return existing
    pct = int(settings.get("first_time_coupon_percent", 20))
    code = f"WELCOME{_secrets.randbelow(9000) + 1000}"
    while await db.coupons.find_one({"code": code}):
        code = f"WELCOME{_secrets.randbelow(9000) + 1000}"
    doc = Coupon(code=code, discount_type="percent", value=pct, active=True,
                 description=f"{pct}% off your first order — welcome to {BRAND_NAME}!",
                 per_customer_limit=1, usage_limit=1, first_time_only=False,
                 applies_to="all_except_weekly_meal",
                 owner_user_id=user["user_id"]).model_dump()
    await db.coupons.insert_one(doc)
    return doc


async def _handle_first_login(user_id: str):
    """On a customer's first successful login: flag it + issue the first-time coupon."""
    try:
        await _ensure_referral_code(user_id)
    except Exception as e:
        log.warning(f"[referral] ensure code failed: {e}")
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u or u.get("role") == "guest" or u.get("has_logged_in"):
        return
    await db.users.update_one({"user_id": user_id},
        {"$set": {"has_logged_in": True, "first_login_at": datetime.now(timezone.utc)}})
    try:
        await _issue_first_time_coupon(u)
    except Exception as e:
        log.warning(f"[first_login] coupon issue failed: {e}")


import base64 as _b64

def _bcrypt_input(password: str) -> bytes:
    # SHA-256 pre-hash avoids bcrypt's 72-byte limit; base64 keeps it printable.
    return _b64.b64encode(_hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    try:
        import bcrypt
        return bcrypt.checkpw(_bcrypt_input(password), stored_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("timing-dummy-password-not-used")
PASSWORD_RESET_TTL_MIN = 30


def _public_user(u: dict) -> dict:
    return {k: v for k, v in u.items() if k not in ("_id", "password_hash")}


def _web_base(request: Request) -> str:
    env = os.environ.get("PUBLIC_WEB_URL")
    if env:
        return env.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{proto}://{host}" if host else ""


class EmailSignupReq(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class EmailLoginReq(BaseModel):
    email: str
    password: str


class ForgotReq(BaseModel):
    email: str


class ResetReq(BaseModel):
    token: str
    password: str


def _valid_email(e: str) -> bool:
    return "@" in e and "." in e.split("@")[-1] and len(e) <= 254


@api.post("/auth/email/signup", status_code=201)
async def email_signup(req: EmailSignupReq):
    """Create (or upgrade a Google/guest) account with email + password."""
    email = _norm_email(req.email)
    if not _valid_email(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(req.password or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing and existing.get("password_hash"):
        raise HTTPException(409, "An account already exists for this email. Please log in.")
    pw = hash_password(req.password)
    if existing:
        await db.users.update_one({"user_id": existing["user_id"]},
            {"$set": {"password_hash": pw, "email_verified": True,
                      **({"name": req.name.strip()} if req.name and not existing.get("name") else {})}})
        uid = existing["user_id"]
    else:
        user = User(user_id=f"user_{uuid.uuid4().hex[:12]}", email=email,
                    name=(req.name or email.split("@")[0]).strip(), email_verified=True)
        doc = user.model_dump()
        doc["password_hash"] = pw
        await db.users.insert_one(doc)
        uid = user.user_id
    token = await _new_session_token(uid, prefix="pw")
    await _handle_first_login(uid)
    fresh = await db.users.find_one({"user_id": uid}, {"_id": 0})
    return {"session_token": token, "user": _public_user(fresh)}


@api.post("/auth/email/login")
async def email_login(req: EmailLoginReq):
    email = _norm_email(req.email)
    user = await db.users.find_one({"email": email})
    if not user:
        verify_password(req.password, _DUMMY_HASH)  # constant-time-ish
        raise HTTPException(401, "Incorrect email or password.")
    if not verify_password(req.password, user.get("password_hash")):
        raise HTTPException(401, "Incorrect email or password.")
    token = await _new_session_token(user["user_id"], prefix="pw")
    await _handle_first_login(user["user_id"])
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"session_token": token, "user": _public_user(fresh)}


@api.post("/auth/password/forgot")
async def password_forgot(req: ForgotReq, request: Request):
    """Email a time-limited reset link. Always returns the same response (no enumeration)."""
    email = _norm_email(req.email)
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user:
        raw = _secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        await db.password_resets.insert_one({
            "user_id": user["user_id"],
            "token_hash": _hashlib.sha256(raw.encode()).hexdigest(),
            "created_at": now,
            "expires_at": now + timedelta(minutes=PASSWORD_RESET_TTL_MIN),
            "used_at": None,
        })
        link = f"{_web_base(request)}/shop/reset-password?token={raw}"
        try:
            if _email.is_configured():
                html = (f"<p>We received a request to reset your {BRAND_NAME} password.</p>"
                        f"<p><a href=\"{link}\">Set a new password</a> (valid for {PASSWORD_RESET_TTL_MIN} minutes).</p>"
                        f"<p>If you didn't request this, you can safely ignore this email.</p>")
                await _email.send_email(to=email, subject=f"Reset your {BRAND_NAME} password", html=html)
            else:
                log.info(f"[reset:dev] {email} -> {link}")
        except Exception as e:
            log.error(f"[reset] email send failed: {e}")
    return {"ok": True, "message": "If an account exists, a reset link has been sent."}


@api.post("/auth/password/reset")
async def password_reset(req: ResetReq):
    if len(req.password or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    now = datetime.now(timezone.utc)
    th = _hashlib.sha256((req.token or "").encode()).hexdigest()
    rec = await db.password_resets.find_one_and_update(
        {"token_hash": th, "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}},
    )
    if not rec:
        raise HTTPException(400, "This reset link is invalid or has expired.")
    await db.users.update_one({"user_id": rec["user_id"]},
                              {"$set": {"password_hash": hash_password(req.password)}})
    # Invalidate all existing sessions so the old password/sessions stop working.
    await db.user_sessions.delete_many({"user_id": rec["user_id"]})
    return {"ok": True, "message": "Password reset. Please sign in with your new password."}


# --------------------------------------------------------------
# Account deletion — required for App Store & Play Store review.
# Hard-deletes profile + sessions; anonymises past orders (kept for
# tax/legal recordkeeping but with PII stripped).
# --------------------------------------------------------------
@api.delete("/user/me")
async def delete_my_account(user: User = Depends(_current_user)):
    uid = user.user_id
    # Anonymise historical orders so financial records survive audit,
    # but no personal data (name / email / phone / address) remains.
    await db.orders.update_many(
        {"user_id": uid},
        {"$set": {
            "user_id": f"deleted_{uid[:8]}",
            "customer_name": "Deleted user",
            "customer_email": "",
            "customer_phone": "",
            "delivery_address": {"line1": "REDACTED", "line2": "", "city": "", "postal_code": ""},
            "instructions": "",
        }}
    )
    # Delete auth sessions, push tokens, saved addresses.
    await db.user_sessions.delete_many({"user_id": uid})
    await db.push_tokens.delete_many({"user_id": uid})
    # Finally, delete the user record itself.
    await db.users.delete_one({"user_id": uid})
    return {"ok": True, "deleted": True}


# ==========================================================
# USER PROFILE — saved address
# ==========================================================
class SavedAddressReq(BaseModel):
    line1: str
    line2: Optional[str] = ""
    city: Optional[str] = "Toronto"
    province: Optional[str] = "ON"
    postal_code: str


@api.post("/me/address")
async def save_default_address(req: SavedAddressReq, user: User = Depends(_current_user)):
    """Store this customer's default delivery address so the Bag screen can pre-fill it next time."""
    await db.users.update_one(
        {"user_id": user.user_id},
        {"$set": {"default_address": req.model_dump()}},
    )
    return {"ok": True}


@api.delete("/me/address")
async def clear_default_address(user: User = Depends(_current_user)):
    await db.users.update_one({"user_id": user.user_id}, {"$unset": {"default_address": ""}})
    return {"ok": True}


# ==========================================================
# GOOGLE PLACES AUTOCOMPLETE (proxied so the API key stays on the server)
# ==========================================================
@api.get("/places/autocomplete")
async def places_autocomplete(q: str, session_token: Optional[str] = None):
    """Return address suggestions for the given partial query. Restricted to Canada."""
    q = (q or "").strip()
    if len(q) < 3:
        return {"predictions": []}
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("AIzaSy_PLACEHOLDER"):
        return {"predictions": []}
    params = {
        "input": q,
        "key": GOOGLE_MAPS_API_KEY,
        "types": "address",
        "components": "country:ca",   # keep the deliverable zone tight
        "language": "en",
    }
    if session_token:
        params["sessiontoken"] = session_token
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            r = await client.get("https://maps.googleapis.com/maps/api/place/autocomplete/json", params=params)
            data = r.json()
            if data.get("status") not in ("OK", "ZERO_RESULTS"):
                logging.warning(f"[places.autocomplete] status={data.get('status')} error={data.get('error_message')}")
                return {"predictions": [], "warning": data.get("status")}
            return {
                "predictions": [
                    {
                        "place_id": p["place_id"],
                        "description": p["description"],
                        "main_text": p.get("structured_formatting", {}).get("main_text", ""),
                        "secondary_text": p.get("structured_formatting", {}).get("secondary_text", ""),
                    }
                    for p in data.get("predictions", [])[:6]
                ],
            }
    except Exception as e:
        logging.exception(f"[places.autocomplete] {e}")
        return {"predictions": []}


@api.get("/places/details")
async def places_details(place_id: str, session_token: Optional[str] = None):
    """Fetch a Places details record and return a structured address (line1/city/postal)."""
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("AIzaSy_PLACEHOLDER"):
        return {"ok": False, "error": "Google Maps API key not configured"}
    params = {
        "place_id": place_id,
        "key": GOOGLE_MAPS_API_KEY,
        "fields": "formatted_address,address_components,geometry",
        "language": "en",
    }
    if session_token:
        params["sessiontoken"] = session_token
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            r = await client.get("https://maps.googleapis.com/maps/api/place/details/json", params=params)
            data = r.json()
            if data.get("status") != "OK":
                return {"ok": False, "error": data.get("status")}
            result = data["result"]
            comps = result.get("address_components", [])

            def find(*types) -> str:
                for c in comps:
                    if any(t in c["types"] for t in types):
                        return c.get("short_name") or c.get("long_name") or ""
                return ""

            street_number = find("street_number")
            route = find("route")
            line1 = " ".join([x for x in [street_number, route] if x]).strip()
            city = find("locality", "sublocality", "sublocality_level_1", "administrative_area_level_2")
            province = find("administrative_area_level_1")
            postal = find("postal_code")
            country = find("country")
            geom = result.get("geometry", {}).get("location", {})
            return {
                "ok": True,
                "address": {
                    "line1": line1,
                    "city": city or "",
                    "province": province or "ON",
                    "postal_code": postal or "",
                    "country": country or "CA",
                    "lat": geom.get("lat"),
                    "lng": geom.get("lng"),
                    "formatted": result.get("formatted_address"),
                },
            }
    except Exception as e:
        logging.exception(f"[places.details] {e}")
        return {"ok": False, "error": str(e)}


# ==========================================================
# MENU
# ==========================================================
def _sunday_of(d: date) -> date:
    """Sunday of the week containing d (weekday: Mon=0..Sun=6). We want Sunday."""
    # weekday: Sun == 6 in python
    days_since_sun = (d.weekday() + 1) % 7  # Sun->0, Mon->1, ..., Sat->6
    return d - timedelta(days=days_since_sun)


async def _hydrate_menu(doc: dict) -> dict:
    """If the weekly menu uses `lines` (master-refs), inflate them to a `items` array
    the frontend already understands, applying price overrides & availability."""
    if not doc:
        return doc
    lines = doc.get("lines") or []
    if not lines:
        return doc
    inflated = []
    for line in lines:
        if line.get("is_visible", True) is False:
            continue  # hidden this week — admin hasn't turned it on for customers
        mi = await db.master_menu.find_one({"item_id": line["master_item_id"]}, {"_id": 0})
        if not mi or not mi.get("is_active", True):
            continue
        price = line.get("price_override_cents") or mi["default_price_cents"]
        avail = line.get("availability", "available")
        stock_limit = line.get("stock_limit")
        stock_used = line.get("stock_used", 0)
        if stock_limit is not None and stock_used >= stock_limit:
            avail = "sold_out"
        inflated.append({
            "item_id": line["master_item_id"],
            "line_id": line["line_id"],
            "name": mi["name"],
            "description": mi.get("short_description") or mi.get("full_description", ""),
            "price_cents": price,
            "image_url": mi.get("image_url", ""),
            "category": mi.get("category", "curry"),
            "tags": [mi.get("veg_type", ""), mi.get("spice_level", "")],
            "is_featured": line.get("is_featured", False),
            "availability": avail,
            "veg_type": mi.get("veg_type"),
            "spice_level": mi.get("spice_level"),
            "allergens": mi.get("allergens", []),
        })
    # If there are also legacy embedded items, keep them appended for back-compat.
    inflated.extend(doc.get("items", []) or [])
    out = dict(doc)
    out["items"] = inflated
    # Resolve complimentary items (display-only). Week-level list takes priority,
    # falling back to the legacy package-level list. Shown to customers ONLY when
    # the Weekly Package is enabled (per product spec).
    pkg = out.get("package") or {}
    comp_ids: List[str] = []
    if out.get("package_enabled"):
        comp_ids = out.get("complimentary_master_ids") or pkg.get("complimentary_master_ids") or []
    comps = []
    if comp_ids:
        by_id = {}
        async for m in db.master_menu.find({"item_id": {"$in": comp_ids}}, {"_id": 0}):
            by_id[m["item_id"]] = m
        for cid in comp_ids:  # preserve admin's chosen order
            m = by_id.get(cid)
            if not m or m.get("is_active") is False:
                continue
            comps.append({
                "item_id": m["item_id"],
                "name": m["name"],
                "description": m.get("short_description") or m.get("full_description", ""),
                "image_url": m.get("image_url", ""),
                "category": m.get("category", ""),
            })
    out["complimentary_items"] = comps
    return out


@api.get("/menu/current")
async def menu_current():
    today = datetime.now(timezone.utc).date()
    week_start = _sunday_of(today).isoformat()
    doc = await db.weekly_menus.find_one(
        {"week_start": week_start, "published": True, "status": {"$ne": "draft"}},
        {"_id": 0},
    )
    if not doc:
        cur = db.weekly_menus.find(
            {"published": True, "status": {"$ne": "draft"}}, {"_id": 0}
        ).sort("week_start", -1).limit(1)
        docs = await cur.to_list(1)
        doc = docs[0] if docs else None
    return await _hydrate_menu(doc) if doc else None


@api.get("/menu/upcoming")
async def menu_upcoming():
    today = datetime.now(timezone.utc).date()
    week_start = _sunday_of(today).isoformat()
    cur = db.weekly_menus.find(
        {"week_start": {"$gt": week_start}, "published": True, "status": {"$ne": "draft"}}, {"_id": 0}
    ).sort("week_start", 1)
    docs = await cur.to_list(20)
    return [await _hydrate_menu(d) for d in docs]


@api.get("/menu/history")
async def menu_history():
    cur = db.weekly_menus.find({}, {"_id": 0}).sort("week_start", -1).limit(20)
    return await cur.to_list(20)


@api.get("/menu/anytime")
async def menu_anytime():
    """Global "Always Available" menu — master items the admin picked on the
    Always Available screen (settings.always_available_master_ids). Orderable any
    time, independent of the weekly plan (e.g. Roti, Biryani, Rolls). Falls back
    to the legacy `always_available` master flag when no global list is set."""
    settings = await _get_settings()
    ids = settings.get("always_available_master_ids") or []
    out = []
    if ids:
        by_id = {}
        async for m in db.master_menu.find(
            {"item_id": {"$in": ids}, "is_active": {"$ne": False}}, {"_id": 0}
        ):
            by_id[m["item_id"]] = m
        ordered = [by_id[i] for i in ids if i in by_id]
        ordered.sort(key=lambda m: (m.get("name") or "").lower())
        cur_items = ordered
    else:
        cur = db.master_menu.find(
            {"always_available": True, "is_active": {"$ne": False}}, {"_id": 0}
        ).sort([("display_order", 1), ("name", 1)])
        cur_items = [m async for m in cur]
    for m in cur_items:
        out.append({
            "item_id": m["item_id"],
            "name": m["name"],
            "description": m.get("short_description") or m.get("full_description", ""),
            "price_cents": m.get("default_price_cents", 0),
            "image_url": m.get("image_url", ""),
            "category": m.get("category", ""),
            "tags": [m.get("veg_type", ""), m.get("spice_level", "")],
            "veg_type": m.get("veg_type", "vegetarian"),
            "spice_level": m.get("spice_level", "medium"),
            "allergens": m.get("allergens", []),
            "is_featured": False,
        })
    return out


@api.post("/menu/upsert")
async def menu_upsert(menu: WeeklyMenu):
    """Admin endpoint (RBAC deferred — protected by shared secret in production)."""
    doc = menu.model_dump()
    await db.weekly_menus.update_one(
        {"week_start": menu.week_start}, {"$set": doc}, upsert=True
    )
    return {"ok": True, "week_start": menu.week_start}


@api.get("/catering")
async def catering_list():
    cur = db.catering_packages.find({}, {"_id": 0}).sort([("sort_order", 1), ("price_cents", 1)])
    return await cur.to_list(50)


@api.get("/catering/{package_id}")
async def catering_detail(package_id: str):
    pkg = await db.catering_packages.find_one({"package_id": package_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(404, "Package not found")
    # Collect all master IDs referenced and return their public summary.
    ids: set = set()
    for g in pkg.get("choice_groups", []) or []:
        ids.update(g.get("option_master_ids", []) or [])
    ids.update(pkg.get("included_master_ids") or [])
    ids.update((p.get("master_item_id") for p in (pkg.get("premium_items") or [])))
    master_map: Dict[str, dict] = {}
    if ids:
        async for m in db.master_menu.find({"item_id": {"$in": list(ids)}}, {"_id": 0}):
            master_map[m["item_id"]] = {
                "item_id": m["item_id"],
                "name": m["name"],
                "short_description": m.get("short_description", ""),
                "image_url": m.get("image_url", ""),
                "veg_type": m.get("veg_type", "vegetarian"),
                "category": m.get("category", ""),
                "allergens": m.get("allergens", []),
            }
    return {"package": pkg, "master_items": master_map}


@api.get("/thali")
async def thali_list():
    cur = db.thali_packages.find({"is_active": {"$ne": False}}, {"_id": 0}).sort([("sort_order", 1), ("per_person_price_cents", 1)])
    return await cur.to_list(50)


@api.get("/thali/{package_id}")
async def thali_detail(package_id: str):
    pkg = await db.thali_packages.find_one({"package_id": package_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(404, "Thali not found")
    return pkg


@api.post("/catering/quote-request")
async def catering_quote_request(body: dict):
    """Store a custom-quote request from customer for the Grand Feast."""
    doc = {
        "request_id": f"cqr_{uuid.uuid4().hex[:10]}",
        "package_id": body.get("package_id"),
        "name": body.get("name", ""),
        "email": body.get("email", ""),
        "phone": body.get("phone", ""),
        "guest_count": int(body.get("guest_count") or 0),
        "event_date": body.get("event_date", ""),
        "notes": body.get("notes", ""),
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.catering_quote_requests.insert_one(doc)
    return {"ok": True, "request_id": doc["request_id"]}


# ==========================================================
# GROCERY (public storefront — App + Customer Portal)
# ==========================================================
def _grocery_public(doc: dict, surcharge_cents: int = 0) -> dict:
    sc = int(surcharge_cents or 0)
    base = int(doc.get("price_cents", 0) or 0)
    cmp = int(doc.get("compare_at_cents", 0) or 0)
    variants = []
    for v in (doc.get("variants") or []):
        vv = dict(v)
        if vv.get("price_cents"):
            vv["price_cents"] = int(vv["price_cents"]) + sc
        if vv.get("compare_at_cents"):
            vv["compare_at_cents"] = int(vv["compare_at_cents"]) + sc
        variants.append(vv)
    return {
        "item_id": doc.get("item_id"),
        "title": doc.get("title"),
        "handle": doc.get("handle", ""),
        "description": doc.get("description", ""),
        "category": doc.get("category", "Grocery & Pantry"),
        "subcategory": doc.get("subcategory", ""),
        "price_cents": (base + sc) if base else base,
        "compare_at_cents": (cmp + sc) if cmp else cmp,
        "unit": doc.get("unit", ""),
        "image_url": doc.get("image_url", ""),
        "images": doc.get("images", []),
        "vendor": doc.get("vendor", ""),
        "tags": doc.get("tags", []),
        "variants": variants,
        "has_variants": doc.get("has_variants", False),
        "on_sale": doc.get("on_sale", False),
        "in_stock": doc.get("in_stock", True),
        "is_featured": doc.get("is_featured", False),
        "zone_surcharge_cents": sc,
    }


# ==========================================================
# LOCATION-BASED PRICING (grocery only)
# ==========================================================
def _normalize_postal(s: Optional[str]) -> str:
    return re.sub(r"\s+", "", (s or "")).upper()


async def _zone_surcharge_for(postal: Optional[str]) -> dict:
    """Return the grocery surcharge for a postal code / FSA by longest-prefix match."""
    p = _normalize_postal(postal)
    if not p:
        return {"zone_id": None, "zone_name": None, "surcharge_cents": 0}
    best = None
    best_len = -1
    async for z in db.pricing_zones.find({"enabled": {"$ne": False}}):
        for pref in (z.get("postal_prefixes") or []):
            pn = _normalize_postal(pref)
            if pn and p.startswith(pn) and len(pn) > best_len:
                best, best_len = z, len(pn)
    if not best:
        return {"zone_id": None, "zone_name": None, "surcharge_cents": 0}
    return {"zone_id": best.get("zone_id"), "zone_name": best.get("name"),
            "surcharge_cents": int(best.get("surcharge_cents") or 0)}


@api.get("/grocery/categories")
async def grocery_categories():
    """List categories with counts (active, not deleted)."""
    pipeline = [
        {"$match": {"is_active": {"$ne": False}, "deleted_at": None}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.grocery.aggregate(pipeline).to_list(500)
    total = sum(r["count"] for r in rows)
    cats = [{"category": r["_id"] or "Grocery & Pantry", "count": r["count"]} for r in rows]
    return {"total": total, "categories": cats}


@api.get("/grocery/subcategories")
async def grocery_subcategories(category: str):
    """Distinct subcategories (with counts) for a category — powers the Fish
    sub-filter chips. Blank subcategories are ignored."""
    pipeline = [
        {"$match": {"is_active": {"$ne": False}, "deleted_at": None, "category": category,
                    "subcategory": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$subcategory", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.grocery.aggregate(pipeline).to_list(100)
    return {"subcategories": [{"subcategory": r["_id"], "count": r["count"]} for r in rows]}


@api.get("/grocery")
async def grocery_list(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    q: Optional[str] = None,
    featured: Optional[bool] = None,
    sort: Optional[str] = None,
    postal: Optional[str] = None,
    page: int = 1,
    limit: int = 24,
):
    """Paginated public catalog. Filter by category, text search, or featured.

    `sort=newest` orders by most-recently-added (used by the app's "New Items"
    strip); otherwise the manual sort_order + title ordering is used.
    """
    page = max(1, page)
    limit = max(1, min(60, limit))
    query: Dict[str, Any] = {"is_active": {"$ne": False}, "deleted_at": None}
    if category and category != "All":
        query["category"] = category
    if subcategory and subcategory != "All":
        query["subcategory"] = subcategory
    if featured:
        query["is_featured"] = True
    if q:
        query["title"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    sort_spec = [("created_at", -1)] if sort == "newest" else [("sort_order", 1), ("title", 1)]
    total = await db.grocery.count_documents(query)
    cur = (
        db.grocery.find(query, {"_id": 0})
        .sort(sort_spec)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    docs = await cur.to_list(limit)
    sc = (await _zone_surcharge_for(postal))["surcharge_cents"] if postal else 0
    return {
        "items": [_grocery_public(d, sc) for d in docs],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "limit": limit,
    }


@api.get("/grocery/{item_id}")
async def grocery_detail(item_id: str, postal: Optional[str] = None):
    doc = await db.grocery.find_one({"item_id": item_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Item not found")
    sc = (await _zone_surcharge_for(postal))["surcharge_cents"] if postal else 0
    return _grocery_public(doc, sc)


@api.get("/grocery/{item_id}/related")
async def grocery_related(item_id: str, postal: Optional[str] = None, limit: int = 12):
    """"You may also like" — other active items in the same category as this one.
    Falls back to featured items if the category is too thin."""
    limit = max(1, min(20, limit))
    doc = await db.grocery.find_one({"item_id": item_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Item not found")
    base = {"is_active": {"$ne": False}, "deleted_at": None, "item_id": {"$ne": item_id}}
    cat = doc.get("category")
    picks: List[dict] = []
    seen: set = set()
    if cat:
        cur = (
            db.grocery.find({**base, "category": cat}, {"_id": 0})
            .sort([("is_featured", -1), ("sort_order", 1), ("title", 1)])
            .limit(limit)
        )
        async for d in cur:
            if d["item_id"] not in seen:
                picks.append(d)
                seen.add(d["item_id"])
    # Top up with featured items from other categories if we don't have enough.
    if len(picks) < limit:
        need = limit - len(picks)
        cur = (
            db.grocery.find(
                {**base, "item_id": {"$nin": list(seen) + [item_id]}, "is_featured": True},
                {"_id": 0},
            )
            .sort([("sort_order", 1), ("title", 1)])
            .limit(need)
        )
        async for d in cur:
            if d["item_id"] not in seen:
                picks.append(d)
                seen.add(d["item_id"])
    sc = (await _zone_surcharge_for(postal))["surcharge_cents"] if postal else 0
    return {"items": [_grocery_public(d, sc) for d in picks]}


# ---- Location pricing resolve + admin zone management ----
class PricingResolveReq(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    postal: Optional[str] = None


@api.post("/pricing/resolve")
async def pricing_resolve(req: PricingResolveReq):
    """Auto-detect the customer's grocery surcharge from GPS coords or a postal code."""
    postal = req.postal
    city = None
    if req.lat is not None and req.lng is not None and GOOGLE_MAPS_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
                r = await c.get("https://maps.googleapis.com/maps/api/geocode/json",
                                params={"latlng": f"{req.lat},{req.lng}", "key": GOOGLE_MAPS_API_KEY})
                data = r.json()
            for res in data.get("results", []):
                for comp in res.get("address_components", []):
                    types = comp.get("types", [])
                    if not postal and "postal_code" in types:
                        postal = comp.get("long_name")
                    if not city and any(t in types for t in ("locality", "postal_town", "sublocality", "administrative_area_level_2")):
                        city = comp.get("long_name")
                if postal and city:
                    break
        except Exception as e:
            log.warning(f"[pricing] reverse geocode failed: {e}")
    z = await _zone_surcharge_for(postal or "")
    fsa = _normalize_postal(postal)[:3] if postal else None
    return {"postal_code": postal, "city": city, "fsa": fsa, **z}


# ==========================================================
# COUPONS
# ==========================================================
@api.get("/coupons/{code}")
async def coupon_lookup(code: str):
    c = await db.coupons.find_one({"code": code.upper(), "active": True}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Coupon not found")
    return c


# ==========================================================
# ORDERS
# ==========================================================
DELIVERY_FEE_CENTS = 599  # $5.99 default GTA delivery fee


# --- Distance-based delivery fee (measured from the Milton kitchen) ---
MILTON_ORIGIN = "6941 Derry Rd West, Milton, ON, Canada"
# Fallback tiers if none configured in settings: {max_km, fee_cents}
DEFAULT_DELIVERY_FEE_TIERS = [
    {"max_km": 20, "fee_cents": 0},
    {"max_km": 40, "fee_cents": 500},
    {"max_km": 75, "fee_cents": 1000},
]
DEFAULT_DELIVERY_FEE_OVER_MAX_CENTS = 1500
DELIVERY_TIME_WINDOW = "6:00 AM – 8:00 PM"
DELIVERY_CONDO_POLICY = (
    "Condo & apartment deliveries: please collect your food from the building gate — "
    "our drivers cannot deliver to individual unit doors."
)


def _num(v, default=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fee_for_km(km, tiers, over_max_cents):
    """Pick the first tier (ascending max_km) the distance falls within.
    Returns (fee_cents, human_label like "0–20 km")."""
    clean = sorted(
        [{"max_km": _num(t.get("max_km")), "fee_cents": int(_num(t.get("fee_cents")))}
         for t in (tiers or []) if t.get("max_km") is not None],
        key=lambda t: t["max_km"],
    )
    if not clean:
        clean = DEFAULT_DELIVERY_FEE_TIERS
    lower = 0
    for t in clean:
        upper = t["max_km"]
        if km <= upper:
            lo = int(lower) if float(lower).is_integer() else lower
            up = int(upper) if float(upper).is_integer() else upper
            return t["fee_cents"], f"{lo}–{up} km"
        lower = upper
    top = int(lower) if float(lower).is_integer() else lower
    return int(over_max_cents), f"{top}+ km"


async def _driving_distance_km(address, origin):
    """Driving distance (km) from the kitchen (`origin`) to the customer address.
    Returns None if Google Maps is unavailable so callers can fall back."""
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("AIzaSy_PLACEHOLDER"):
        return None
    if getattr(address, "lat", None) is not None and getattr(address, "lng", None) is not None:
        dest = f"{address.lat},{address.lng}"
    else:
        parts = [address.line1, address.city, address.province, address.postal_code, "Canada"]
        dest = ", ".join([p for p in parts if p])
    params = {"origins": origin or MILTON_ORIGIN, "destinations": dest,
              "key": GOOGLE_MAPS_API_KEY, "units": "metric", "mode": "driving"}
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            r = await client.get("https://maps.googleapis.com/maps/api/distancematrix/json", params=params)
            data = r.json()
            el = (data.get("rows") or [{}])[0].get("elements", [{}])[0]
            if el.get("status") == "OK":
                return el["distance"]["value"] / 1000.0
            logging.warning(f"[delivery.distance] element status={el.get('status')} top={data.get('status')}")
    except Exception as e:
        logging.exception(f"[delivery.distance] {e}")
    return None


def _norm_city(s) -> str:
    return " ".join((s or "").split()).lower()


async def _zone_fee_for_city(city: Optional[str]) -> dict:
    """Flat delivery fee for a city from enabled pricing zones with fee_cents set.
    City match is exact on the normalized city name. Returns fee_cents None
    when no fee zone matches (caller falls back to km tiers)."""
    c = _norm_city(city)
    if not c:
        return {"zone_id": None, "zone_name": None, "fee_cents": None}
    async for z in db.pricing_zones.find({"enabled": {"$ne": False}}):
        cities = [_norm_city(x) for x in (z.get("cities") or [])]
        if c in cities and z.get("fee_cents") is not None:
            return {"zone_id": z.get("zone_id"), "zone_name": z.get("name"),
                    "fee_cents": int(z["fee_cents"])}
    return {"zone_id": None, "zone_name": None, "fee_cents": None}


async def compute_delivery_fee(address, settings):
    """Returns (fee_cents, distance_km_or_None, tier_label). A fee zone matching
    the delivery city wins over km tiers; otherwise the km-tier table from
    BusinessSettings applies. Origin + tiers are read from BusinessSettings
    so the admin can configure them in Settings."""
    origin = (settings.get("kitchen_address") or "").strip() or MILTON_ORIGIN
    zone = await _zone_fee_for_city(getattr(address, "city", None))
    if zone["fee_cents"] is not None:
        return zone["fee_cents"], None, f"zone:{zone['zone_name']}"
    km = await _driving_distance_km(address, origin)
    if km is None:
        return settings.get("default_delivery_fee_cents", DELIVERY_FEE_CENTS), None, "standard"
    tiers = settings.get("delivery_fee_tiers") or DEFAULT_DELIVERY_FEE_TIERS
    over = settings.get("delivery_fee_over_max_cents", DEFAULT_DELIVERY_FEE_OVER_MAX_CENTS)
    fee, tier = _fee_for_km(km, tiers, over)
    return fee, round(km, 1), tier


def _free_delivery_applies(subtotal_cents: int, city: Optional[str], settings: dict) -> bool:
    """Free-delivery threshold: standard threshold, or the higher remote
    threshold for Barrie / London (and any cities the admin lists)."""
    c = _norm_city(city)
    remote = {_norm_city(x) for x in (settings.get("free_delivery_remote_cities") or ["Barrie", "London"])}
    threshold = int(settings.get("free_delivery_remote_threshold_cents", 25000) if c in remote
                    else settings.get("free_delivery_threshold_cents", 15000))
    return subtotal_cents >= threshold



async def _resolve_items(items: List[OrderItemIn], grocery_surcharge_cents: int = 0):
    """Fetch authoritative prices from DB and return (snapshots, subtotal_cents).
    For catering, price is per-person; line_total = per_person * catering_guest_count * quantity.
    Menu items are looked up in weekly menus (v1 embedded or v2 lines) or master_menu.
    """
    snapshots = []
    subtotal = 0
    for it in items:
        if it.kind == "service":
            s = await _get_settings()
            if it.ref_id == "fish_cleaning":
                if not bool(s.get("fish_service_enabled", True)):
                    raise HTTPException(400, "This service is not available right now.")
                price = int(s.get("fish_service_price_cents", 299) or 0)
                name = s.get("fish_service_name", "Fish Scaling & Cleaning")
            else:
                raise HTTPException(400, f"Unknown service {it.ref_id}")
            line_total = price * it.quantity
            line = {
                "kind": "service",
                "ref_id": it.ref_id,
                "name": name,
                "unit_price_cents": price,
                "quantity": it.quantity,
                "image_url": "",
                "line_total_cents": line_total,
            }
        elif it.kind == "menu":
            src = None
            avail = "available"
            # 1) legacy embedded weekly item
            m = await db.weekly_menus.find_one(
                {"items.item_id": it.ref_id}, {"_id": 0, "items.$": 1}
            )
            if m and m.get("items"):
                src = m["items"][0]
            else:
                # 2) v2 line: try master_menu direct, applying any current-week override
                mi = await db.master_menu.find_one({"item_id": it.ref_id}, {"_id": 0})
                if mi:
                    src = {
                        "name": mi["name"],
                        "price_cents": mi["default_price_cents"],
                        "image_url": mi.get("image_url", ""),
                    }
                    # Try to find a matching line in a published weekly menu for override.
                    wm = await db.weekly_menus.find_one(
                        {"lines.master_item_id": it.ref_id, "published": True,
                         "status": {"$ne": "draft"}},
                        {"_id": 0, "lines.$": 1},
                    )
                    if wm and wm.get("lines"):
                        ln = wm["lines"][0]
                        if ln.get("price_override_cents"):
                            src["price_cents"] = ln["price_override_cents"]
                        avail = ln.get("availability", "available")
                        stock_limit = ln.get("stock_limit")
                        if stock_limit is not None and ln.get("stock_used", 0) >= stock_limit:
                            avail = "sold_out"
            if not src:
                raise HTTPException(400, f"Menu item {it.ref_id} not found")
            if avail == "sold_out":
                raise HTTPException(400, f"'{src.get('name')}' is sold out this week")
            line_total = src["price_cents"] * it.quantity
            line = {
                "kind": "menu",
                "ref_id": it.ref_id,
                "name": src.get("name"),
                "unit_price_cents": src.get("price_cents"),
                "quantity": it.quantity,
                "image_url": src.get("image_url"),
                "line_total_cents": line_total,
            }
        elif it.kind == "catering":
            pkg = await db.catering_packages.find_one({"package_id": it.ref_id}, {"_id": 0})
            if not pkg:
                raise HTTPException(400, f"Catering package {it.ref_id} not found")
            if pkg.get("is_custom_quote"):
                raise HTTPException(400, "This catering package is quote-only; contact us to book.")
            guests = it.catering_guest_count or pkg.get("min_guests", 10)
            min_g = pkg.get("min_guests", 10)
            if guests < min_g:
                raise HTTPException(400, f"Catering package requires at least {min_g} guests")

            # ---- Resolve per-person price from tier (or fallback price_cents) ----
            per_person = pkg.get("price_cents", 0)
            selection = it.catering_selections or CateringSelection()
            tiers = pkg.get("upgrade_tiers", []) or []
            active_tier = None
            if selection.tier_id and tiers:
                active_tier = next((t for t in tiers if t.get("tier_id") == selection.tier_id), None)
                if not active_tier:
                    raise HTTPException(400, "Invalid catering tier")
                per_person = active_tier["per_person_cents"]
            elif tiers:
                active_tier = next((t for t in tiers if t.get("is_default")), tiers[0])
                per_person = active_tier["per_person_cents"]

            # ---- Validate choice-group selections (with tier overrides) ----
            groups = pkg.get("choice_groups", []) or []
            group_by_id = {g["group_id"]: g for g in groups}
            picks_by_group = selection.group_selections or {}
            for g in groups:
                gid = g["group_id"]
                override = (active_tier or {}).get("group_overrides", {}).get(gid) if active_tier else None
                min_sel = override.get("min_select") if override else g.get("min_select", 1)
                max_sel = override.get("max_select") if override else g.get("max_select", 1)
                picks = picks_by_group.get(gid, [])
                # dedupe & keep only valid options
                picks = [p for p in dict.fromkeys(picks) if p in g.get("option_master_ids", [])]
                if len(picks) < min_sel or len(picks) > max_sel:
                    raise HTTPException(400, f"Group '{g['title']}' requires {min_sel}–{max_sel} selections (got {len(picks)})")

            # ---- Premium upcharges (only allowed items from pkg.premium_items) ----
            premium_list = {p["master_item_id"]: p["upcharge_per_person_cents"] for p in (pkg.get("premium_items") or [])}
            premium_picks = [pid for pid in dict.fromkeys(selection.premium_selections or []) if pid in premium_list]
            premium_upcharge_per_person = sum(premium_list[pid] for pid in premium_picks)

            unit_per_person = per_person + premium_upcharge_per_person
            line_total = unit_per_person * guests * it.quantity

            # Build human-readable selection summary for the order snapshot.
            id_to_name: Dict[str, str] = {}
            all_master_ids = set()
            for g in groups:
                all_master_ids.update(g.get("option_master_ids", []))
            all_master_ids.update(pkg.get("included_master_ids") or [])
            all_master_ids.update(premium_list.keys())
            if all_master_ids:
                async for m in db.master_menu.find({"item_id": {"$in": list(all_master_ids)}}, {"_id": 0, "item_id": 1, "name": 1}):
                    id_to_name[m["item_id"]] = m["name"]

            selection_summary = []
            for g in groups:
                names = [id_to_name.get(pid, pid) for pid in picks_by_group.get(g["group_id"], [])]
                if names:
                    selection_summary.append({"title": g["title"], "items": names})
            included_names = [id_to_name.get(mid, mid) for mid in (pkg.get("included_master_ids") or [])]
            premium_names = [id_to_name.get(pid, pid) for pid in premium_picks]

            line = {
                "kind": "catering",
                "ref_id": it.ref_id,
                "name": pkg.get("name"),
                "unit_price_cents": unit_per_person,
                "per_person_price_cents": unit_per_person,
                "base_per_person_cents": per_person,
                "premium_upcharge_per_person_cents": premium_upcharge_per_person,
                "tier_id": (active_tier or {}).get("tier_id"),
                "tier_title": (active_tier or {}).get("title"),
                "catering_guest_count": guests,
                "quantity": it.quantity,
                "image_url": pkg.get("image_url"),
                "line_total_cents": line_total,
                "selection_summary": selection_summary,
                "included_names": included_names,
                "premium_names": premium_names,
            }
        elif it.kind == "weekly_package":
            wm = await db.weekly_menus.find_one({"menu_id": it.ref_id}, {"_id": 0})
            if not wm:
                raise HTTPException(400, f"Weekly menu {it.ref_id} not found")
            if not wm.get("package_enabled") or not wm.get("package"):
                raise HTTPException(400, "Weekly package is not enabled for this menu")
            pkg = wm["package"]
            pick_count = int(pkg.get("pick_count") or 0)
            price_cents = int(pkg.get("price_cents") or 0)
            picks = list(it.package_selections or [])  # KEEP ORDER + DUPLICATES (quantities)

            # Eligible pool: explicit list, else all master items in the week's lines
            line_master_ids = [ln.get("master_item_id") for ln in (wm.get("lines") or []) if ln.get("master_item_id")]
            eligible = pkg.get("eligible_master_ids") or line_master_ids
            eligible_set = set(eligible)

            # Validate all picks are in eligible pool
            invalid = [p for p in picks if p not in eligible_set]
            if invalid:
                raise HTTPException(400, "Some items are not eligible for this week's package")

            # Resolve names + veg types for snapshot / composition (dedupe for the lookup)
            unique_picks = list(dict.fromkeys(picks))
            names_map: Dict[str, str] = {}
            vt_map: Dict[str, str] = {}
            async for m in db.master_menu.find({"item_id": {"$in": unique_picks}}, {"_id": 0, "item_id": 1, "name": 1, "veg_type": 1}):
                names_map[m["item_id"]] = m["name"]
                vt_map[m["item_id"]] = m.get("veg_type", "vegetarian")

            # ---- Composition-based pricing (veg / mixed / non-veg) ----
            # Egg (eggitarian) counts as NON-VEG, per the poster grouping. A plan is
            # valid only when the veg/non-veg makeup matches one fixed shape.
            pricing_mode = pkg.get("pricing_mode") or "flat"
            if pricing_mode == "composition":
                from collections import Counter as _C0
                # Cap how many of the same dish the customer may pick.
                max_per = int(pkg.get("max_per_dish") or 0)
                if max_per > 0:
                    over = [names_map.get(mid, mid) for mid, c in _C0(picks).items() if c > max_per]
                    if over:
                        raise HTTPException(400, f"You can pick at most {max_per} of the same dish (too many: {', '.join(over)}).")
                nonveg_count = sum(1 for p in picks if vt_map.get(p, "vegetarian") != "vegetarian")
                veg_count = len(picks) - nonveg_count
                veg_n = int(pkg.get("veg_pick_count") or pkg.get("pick_count") or 0)
                nonveg_n = int(pkg.get("nonveg_pick_count") or pkg.get("pick_count") or 0)
                mixed_v = int(pkg.get("mixed_veg_count") or 0)
                mixed_nv = int(pkg.get("mixed_nonveg_count") or 0)
                if nonveg_count == 0 and veg_n > 0 and veg_count == veg_n:
                    price_cents = int(pkg.get("veg_price_cents") or 0)
                    composition = "all-veg"
                elif veg_count == 0 and nonveg_n > 0 and nonveg_count == nonveg_n:
                    price_cents = int(pkg.get("nonveg_price_cents") or 0)
                    composition = "all-non-veg"
                elif mixed_v > 0 and mixed_nv > 0 and veg_count == mixed_v and nonveg_count == mixed_nv:
                    price_cents = int(pkg.get("mixed_price_cents") or 0)
                    composition = "mixed"
                elif mixed_v == 0 and mixed_nv == 0 and veg_count > 0 and nonveg_count > 0 and pick_count > 0 and len(picks) == pick_count:
                    # Legacy config (no explicit mixed counts): any mix at pick_count.
                    price_cents = int(pkg.get("mixed_price_cents") or 0)
                    composition = "mixed"
                else:
                    opts = []
                    if veg_n > 0:
                        opts.append(f"{veg_n} veg")
                    if mixed_v > 0 and mixed_nv > 0:
                        opts.append(f"{mixed_v} veg + {mixed_nv} non-veg")
                    if nonveg_n > 0:
                        opts.append(f"{nonveg_n} non-veg")
                    raise HTTPException(400, "Please pick exactly " + ", or ".join(opts) + ".")
                if price_cents <= 0:
                    raise HTTPException(400, "Weekly plan price is not configured for this selection")
                pick_count = len(picks)
            else:
                if len(picks) != pick_count:
                    raise HTTPException(400, f"Weekly package requires exactly {pick_count} portions (got {len(picks)})")
                # Flat mode also honours max_per_dish (e.g. "all 6 items" = 1 of each).
                from collections import Counter as _C0f
                max_per_f = int(pkg.get("max_per_dish") or 0)
                if max_per_f > 0:
                    over_f = [names_map.get(mid, mid) for mid, c in _C0f(picks).items() if c > max_per_f]
                    if over_f:
                        raise HTTPException(400, f"You can pick at most {max_per_f} of the same dish (too many: {', '.join(over_f)}).")
                composition = None

            # Human-readable display list — aggregate repeats as "Biryani × 3"
            from collections import Counter as _Counter
            counts = _Counter(picks)

            # Per-item surcharges add on top of the flat package price for each portion.
            surcharge_map = pkg.get("item_surcharges_cents") or {}
            surcharge_total = sum(int(surcharge_map.get(mid, 0) or 0) for mid in picks)
            effective_unit_cents = price_cents + surcharge_total

            display_names = []
            for mid, q in counts.items():
                base = names_map.get(mid, mid)
                extra = int(surcharge_map.get(mid, 0) or 0)
                # Show " (+$X)" per-portion so kitchen/receipt lists surcharge context.
                suffix = f" (+CA${extra/100:.2f} ea)" if extra > 0 else ""
                display_names.append(f"{base} × {q}{suffix}" if q > 1 else f"{base}{suffix}")

            line = {
                "kind": "weekly_package",
                "ref_id": it.ref_id,
                "name": pkg.get("name") or "Weekly Combo",
                "unit_price_cents": effective_unit_cents,        # base + surcharges
                "quantity": it.quantity,
                "image_url": pkg.get("image_url") or wm.get("banner_image_url", ""),
                "line_total_cents": effective_unit_cents * it.quantity,
                "package_selection_ids": picks,                  # expanded (preserves qty)
                "package_selection_names": display_names,        # aggregated for display
                "package_pick_count": pick_count,
                "package_base_cents": price_cents,               # transparency for receipts
                "package_composition": composition,              # all-veg | mixed | all-non-veg | None
                "package_pricing_mode": pkg.get("pricing_mode") or "flat",
                "package_surcharge_cents": surcharge_total,      # transparency for receipts
                "weekly_menu_id": it.ref_id,
                "weekly_menu_week_start": wm.get("week_start"),
            }
        elif it.kind == "thali":
            pkg = await db.thali_packages.find_one({"package_id": it.ref_id}, {"_id": 0})
            if not pkg:
                raise HTTPException(400, f"Thali package {it.ref_id} not found")
            if not pkg.get("is_active", True):
                raise HTTPException(400, "This thali is not available right now.")
            guests = int(it.thali_guest_count or 0)
            min_g = int(pkg.get("min_guests", 25) or 0)
            if guests < min_g:
                raise HTTPException(400, f"Minimum order for {pkg.get('name','this thali')} is {min_g} guests.")
            protein_name = ""
            if (pkg.get("thali_type") == "non_veg") and (pkg.get("protein_options") or []):
                opt = None
                if it.thali_protein_option_id:
                    opt = next((o for o in pkg["protein_options"] if o.get("option_id") == it.thali_protein_option_id), None)
                if not opt:
                    raise HTTPException(400, f"Please choose a protein for {pkg.get('name','the thali')}.")
                per_person = int(opt.get("price_cents") or 0)
                protein_name = opt.get("name", "")
            else:
                per_person = int(pkg.get("per_person_price_cents") or 0)
            line_total = per_person * guests * it.quantity
            name = pkg.get("name", "Thali") + (f" — {protein_name}" if protein_name else "")
            line = {
                "kind": "thali",
                "ref_id": it.ref_id,
                "name": name,
                "unit_price_cents": per_person,
                "quantity": it.quantity,
                "image_url": pkg.get("image_url", ""),
                "line_total_cents": line_total,
                "thali_type": pkg.get("thali_type", "veg"),
                "thali_guest_count": guests,
                "thali_protein_name": protein_name,
                "thali_delivery_date": it.thali_delivery_date or "",
                "thali_includes": pkg.get("includes", []),
            }
        elif it.kind == "grocery":
            g = await db.grocery.find_one(
                {"item_id": it.ref_id, "is_active": {"$ne": False}, "deleted_at": None},
                {"_id": 0},
            )
            if not g:
                raise HTTPException(400, f"Grocery item {it.ref_id} not found")
            variants = g.get("variants") or []
            chosen = None
            if it.variant_id and variants:
                chosen = next((v for v in variants if str(v.get("variant_id")) == str(it.variant_id)), None)
            if chosen is None and variants:
                chosen = next((v for v in variants if v.get("available")), variants[0])
            if chosen is not None:
                unit_price = int(chosen.get("price_cents") or 0) + int(grocery_surcharge_cents or 0)
                vtitle = chosen.get("title") or ""
                available = chosen.get("available", True)
                name = g.get("title") + (f" — {vtitle}" if vtitle and vtitle != "Standard" else "")
            else:
                unit_price = int(g.get("price_cents") or 0) + int(grocery_surcharge_cents or 0)
                available = g.get("in_stock", True)
                name = g.get("title")
            if not available:
                raise HTTPException(400, f"'{name}' is out of stock")
            line = {
                "kind": "grocery",
                "ref_id": it.ref_id,
                "variant_id": it.variant_id or (chosen.get("variant_id") if chosen else ""),
                "name": name,
                "unit_price_cents": unit_price,
                "quantity": it.quantity,
                "image_url": g.get("image_url", ""),
                "line_total_cents": unit_price * it.quantity,
                "grocery_unit": g.get("unit", ""),
            }
        else:
            raise HTTPException(400, f"Unknown item kind {it.kind}")
        subtotal += line["line_total_cents"]
        snapshots.append(line)
    return snapshots, subtotal


async def _get_settings() -> dict:
    doc = await db.business_settings.find_one({"key": "default"}, {"_id": 0})
    if not doc:
        return BusinessSettings().model_dump()
    # Merge over defaults so a partially-written doc never misses fields
    # (e.g. an upsert that only touched always_available_master_ids).
    return {**BusinessSettings().model_dump(), **doc}


def _tax_enabled_for_method(settings: dict, payment_method: str) -> bool:
    """Return whether HST should be applied for the given payment_method.

    Priority:
      1. `payment_methods[<method>].tax_enabled` if configured
      2. Legacy global `settings.tax_enabled` as fallback
    Note: `payment_method == "card"` is used for Stripe by the client.
    """
    key_map = {"card": "stripe", "stripe": "stripe", "cod": "cod",
               "paypal": "paypal", "interac": "interac"}
    key = key_map.get((payment_method or "").lower(), "stripe")
    pm = (settings.get("payment_methods") or {}).get(key)
    if pm is not None and "tax_enabled" in pm:
        return bool(pm["tax_enabled"])
    return bool(settings.get("tax_enabled", True))


def _loyalty_cfg(settings: dict):
    """Return (earn_points_per_dollar, redeem_points_per_dollar) with safe defaults."""
    earn = float(settings.get("loyalty_earn_points_per_dollar", 1.0) or 0)
    redeem = int(settings.get("loyalty_redeem_points_per_dollar", 25) or 25)
    return earn, max(1, redeem)


async def _resolve_coupon(code: Optional[str], subtotal: int, user: User, snapshots=None):
    """Validate a coupon against all rules. Returns (discount_cents, coupon_code, error_or_None).
    The discount base depends on applies_to: grocery_only / weekly_meal_only /
    all_except_weekly_meal restrict the base to the matching snapshot lines."""
    if not code:
        return 0, None, None
    c = await db.coupons.find_one({"code": code.strip().upper()}, {"_id": 0})
    if not c or not c.get("active", True):
        return 0, None, "Invalid or inactive coupon code."
    exp = c.get("expiry")
    if exp:
        try:
            if datetime.strptime(exp, "%Y-%m-%d").date() < datetime.now(timezone.utc).date():
                return 0, None, "This coupon has expired."
        except Exception:
            pass
    if subtotal < c.get("min_order_cents", 0):
        return 0, None, f"This coupon needs a minimum order of CA${c['min_order_cents']/100:.2f}."
    owner = c.get("owner_user_id")
    if owner and owner != user.user_id:
        return 0, None, "This coupon isn't available on your account."
    if c.get("usage_limit", 0) and c.get("used_count", 0) >= c["usage_limit"]:
        return 0, None, "This coupon has reached its usage limit."
    pcl = c.get("per_customer_limit", 0)
    if pcl:
        used_by_me = await db.coupon_redemptions.count_documents({"code": c["code"], "user_id": user.user_id})
        if used_by_me >= pcl:
            return 0, None, "You've already used this coupon."
    if c.get("first_time_only"):
        prior = await db.orders.count_documents(
            {"user_id": user.user_id, "payment_status": {"$in": ["paid", "cod_pending", "interac_pending"]}})
        if prior > 0:
            return 0, None, "This coupon is for first-time customers only."
    applies = c.get("applies_to") or "all"
    snaps = snapshots or []
    if applies == "grocery_only":
        base = sum(int(l.get("line_total_cents", 0) or 0) for l in snaps if l.get("kind") == "grocery")
    elif applies == "weekly_meal_only":
        base = sum(int(l.get("line_total_cents", 0) or 0) for l in snaps if l.get("kind") in ("menu", "weekly_package"))
    elif applies == "all_except_weekly_meal":
        base = subtotal - sum(int(l.get("line_total_cents", 0) or 0) for l in snaps if l.get("kind") in ("menu", "weekly_package"))
    else:
        base = subtotal
    if c.get("discount_type") == "percent":
        discount = base * int(c["value"]) // 100
    else:
        discount = min(int(c["value"]), base)
    return discount, c["code"], None


async def _record_loyalty_and_coupon(order: dict, user_id: str):
    """After an order is confirmed/paid: write points ledger, coupon redemption + usage."""
    now = datetime.now(timezone.utc)
    oid = order.get("order_id")
    awarded = int(order.get("points_awarded", 0) or 0)
    redeemed_pts = int(order.get("points_redeemed", 0) or 0)
    if awarded:
        await db.points_ledger.insert_one({"user_id": user_id, "order_id": oid, "delta": awarded,
                                           "type": "earn", "ts": now, "note": f"Earned on order {oid[-6:].upper()}"})
    if redeemed_pts:
        await db.points_ledger.insert_one({"user_id": user_id, "order_id": oid, "delta": -redeemed_pts,
                                           "type": "redeem", "ts": now, "note": f"Redeemed on order {oid[-6:].upper()}"})
    code = order.get("coupon_code")
    if code:
        already = await db.coupon_redemptions.find_one({"code": code, "order_id": oid})
        if not already:
            await db.coupon_redemptions.insert_one({ "code": code, "user_id": user_id, "order_id": oid, "ts": now})
            await db.coupons.update_one({"code": code}, {"$inc": {"used_count": 1}})
    # Referral reward: on the referred customer's confirmed/paid order, the
    # referrer earns a 10% grocery-only coupon — once per (referrer, referred) pair.
    referrer_id = order.get("referrer_user_id")
    if referrer_id and user_id != referrer_id:
        already_ref = await db.referrals.find_one({"referrer_user_id": referrer_id, "referred_user_id": user_id})
        if not already_ref:
            await db.referrals.insert_one({"referrer_user_id": referrer_id, "referred_user_id": user_id,
                                           "order_id": oid, "ts": now})
            rcode = f"REF{_secrets.randbelow(9000) + 1000}"
            while await db.coupons.find_one({"code": rcode}):
                rcode = f"REF{_secrets.randbelow(9000) + 1000}"
            await db.coupons.insert_one(Coupon(code=rcode, discount_type="percent", value=10, active=True,
                description="10% off groceries — thanks for referring a friend!",
                per_customer_limit=1, usage_limit=1, applies_to="grocery_only",
                owner_user_id=referrer_id).model_dump())
    # Weekly-meal streak: 4 completed weekly-meal orders → 50% off the 5th.
    snaps = order.get("items_snapshot") or []
    if any(l.get("kind") in ("menu", "weekly_package") for l in snaps):
        u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "weekly_meal_streak": 1})
        if u is not None:
            streak = int(u.get("weekly_meal_streak") or 0) + 1
            if streak >= 4:
                mcode = f"MEAL50{_secrets.randbelow(9000) + 1000}"
                while await db.coupons.find_one({"code": mcode}):
                    mcode = f"MEAL50{_secrets.randbelow(9000) + 1000}"
                await db.coupons.insert_one(Coupon(code=mcode, discount_type="percent", value=50, active=True,
                    description="50% off your 5th weekly meal — thanks for 4 in a row!",
                    per_customer_limit=1, usage_limit=1, applies_to="weekly_meal_only",
                    owner_user_id=user_id).model_dump())
                streak = 0
            await db.users.update_one({"user_id": user_id}, {"$set": {"weekly_meal_streak": streak}})


async def _clawback_points_if_cancelled(order: dict, new_status: str):
    """When an order is cancelled/refunded, reverse the loyalty points it earned.

    Inserts a compensating 'clawback' ledger entry and decrements the user's
    balance (floored at 0 so it can never go negative). Idempotent — guarded by
    the order's `points_clawed_back` flag so repeated status writes don't
    double-deduct. Only the points THIS order earned are reversed.
    """
    if new_status not in ("cancelled", "refunded"):
        return
    if order.get("points_clawed_back"):
        return
    oid = order.get("order_id")
    uid = order.get("user_id")
    awarded = int(order.get("points_awarded", 0) or 0)
    if uid and awarded > 0:
        u = await db.users.find_one({"user_id": uid}, {"_id": 0, "loyalty_points": 1}) or {}
        bal = int(u.get("loyalty_points", 0) or 0)
        dec = min(bal, awarded)  # floor the balance at 0
        if dec > 0:
            await db.users.update_one({"user_id": uid}, {"$inc": {"loyalty_points": -dec}})
        await db.points_ledger.insert_one({
            "user_id": uid, "order_id": oid, "delta": -dec, "type": "clawback",
            "ts": datetime.now(timezone.utc),
            "note": f"Reversed — order {str(oid)[-6:].upper()} {new_status}",
        })
    await db.orders.update_one({"order_id": oid}, {"$set": {"points_clawed_back": True}})


@api.post("/orders/quote")
async def order_quote(req: QuoteOrderReq, user: User = Depends(_current_user)):
    # When a zone flat fee applies, the zone surcharge is skipped (else the
    # customer would pay zone fee + zone surcharge on the same order).
    zone_fee = await _zone_fee_for_city(getattr(req.address, "city", None)) if req.address else {"fee_cents": None}
    g_sc = 0 if zone_fee["fee_cents"] is not None else (await _zone_surcharge_for(getattr(req.address, "postal_code", None)))["surcharge_cents"] if req.address else 0
    snaps, subtotal = await _resolve_items(req.items, g_sc)
    settings = await _get_settings()
    earn_rate, redeem_rate = _loyalty_cfg(settings)
    discount, coupon, coupon_err = await _resolve_coupon(req.coupon_code, subtotal, user, snaps)
    ref_discount, _, ref_err = await _resolve_referral(req.referral_code, user, snaps)
    is_customer = user.role != "guest"
    pts_balance = user.loyalty_points if is_customer else 0
    # redeem_points are POINTS; discount value in cents = points*100 // redeem_rate
    max_redeem_cents = pts_balance * 100 // redeem_rate
    want_cents = max(0, req.redeem_points) * 100 // redeem_rate
    points_redeem_cents = min(want_cents, max_redeem_cents, max(0, subtotal - discount - ref_discount))
    points_consumed = round(points_redeem_cents * redeem_rate / 100) if points_redeem_cents else 0
    # Tell the customer when their requested redemption was reduced (over-balance
    # or capped at the order value) instead of silently clamping it.
    requested_pts = max(0, req.redeem_points)
    points_notice = None
    if requested_pts > points_consumed:
        if requested_pts > pts_balance:
            points_notice = f"Only {pts_balance} points available — {points_consumed} applied."
        else:
            points_notice = f"Points capped at order value — {points_consumed} applied."
    delivery_fee, dist_km, fee_tier = await compute_delivery_fee(req.address, settings)
    if _free_delivery_applies(subtotal, getattr(req.address, "city", None), settings):
        delivery_fee, fee_tier = 0, "free_delivery"
    taxable = max(0, subtotal + delivery_fee - discount - ref_discount - points_redeem_cents)
    tax_on = _tax_enabled_for_method(settings, req.payment_method)
    tax_cents = (taxable * settings.get("tax_rate_bps", 1300)) // 10000 if tax_on else 0
    total = taxable + tax_cents
    earn_preview = int((subtotal / 100.0) * earn_rate) if is_customer else 0
    return {
        "subtotal_cents": subtotal,
        "delivery_fee_cents": delivery_fee,
        "delivery_distance_km": dist_km,
        "delivery_fee_tier": fee_tier,
        "delivery_time_window": DELIVERY_TIME_WINDOW,
        "delivery_condo_policy": DELIVERY_CONDO_POLICY,
        "tax_cents": tax_cents,
        "tax_label": settings.get("tax_label", "HST"),
        "tax_enabled": tax_on,
        "discount_cents": discount,
        "referral_discount_cents": ref_discount,
        "referral_error": ref_err,
        "points_redeemed_cents": points_redeem_cents,
        "points_consumed": points_consumed,
        "points_notice": points_notice,
        "total_cents": total,
        "coupon_code": coupon,
        "coupon_error": coupon_err,
        "items_snapshot": snaps,
        "points_available": pts_balance,
        "points_redeem_rate": redeem_rate,
        "points_earn_rate": earn_rate,
        "points_earn_preview": earn_preview,
        "is_guest": not is_customer,
    }


def _validate_delivery_slot(slot, settings):
    """Enforce configured delivery cycles: the slot date must fall on a cycle
    delivery day and be booked before that cycle's cutoff (Toronto time).
    No cycles configured → legacy behaviour (no validation)."""
    cycles = settings.get("delivery_cycles") or []
    if not cycles:
        return
    try:
        d = date.fromisoformat(slot.date)
    except Exception:
        raise HTTPException(400, "Invalid delivery date.")
    js_dow = (d.weekday() + 1) % 7  # Mon=1 .. Sun=0
    cycle = next((c for c in cycles if int(c.get("delivery_day", -1)) == js_dow), None)
    if not cycle:
        names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        days = sorted({int(c.get("delivery_day", 0)) for c in cycles})
        raise HTTPException(400, "Please choose a " + " or ".join(names[x] for x in days) + " delivery slot.")
    from zoneinfo import ZoneInfo as _ZoneInfo
    cutoff_day = int(cycle.get("cutoff_day", 0))
    cutoff_hour = int(cycle.get("cutoff_hour", 12))
    days_back = (js_dow - cutoff_day) % 7
    cutoff_date = d - timedelta(days=days_back)
    cutoff = datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day,
                      cutoff_hour, tzinfo=_ZoneInfo("America/Toronto"))
    now_toronto = datetime.now(timezone.utc).astimezone(_ZoneInfo("America/Toronto"))
    if now_toronto > cutoff:
        raise HTTPException(400, f"Cutoff passed for this delivery slot ({cycle.get('label') or 'delivery'}). Please choose the next available slot.")


@api.post("/orders")
async def create_order(req: CreateOrderReq, request: Request, user: User = Depends(_current_user)):
    # Platform gate — if the Suparna Dey Platform flags this tenant as
    # non-operational or hide_checkout, block new orders with a 402 (Payment
    # Required) so the frontend can surface a "subscription lapsed" screen.
    from platform_client import is_operational, should_hide_checkout, snapshot
    if not is_operational() or should_hide_checkout():
        snap = snapshot()
        raise HTTPException(
            402,
            snap.get("banner_text") or (
                f"{BRAND_NAME} is temporarily paused because the restaurant owner "
                "has not completed their platform subscription payment. Please try again shortly."
            )
        )
    zone_fee = await _zone_fee_for_city(getattr(req.address, "city", None)) if getattr(req, "address", None) else {"fee_cents": None}
    g_sc = 0 if zone_fee["fee_cents"] is not None else (await _zone_surcharge_for(getattr(req.address, "postal_code", None)))["surcharge_cents"] if getattr(req, "address", None) else 0
    snaps, subtotal = await _resolve_items(req.items, g_sc)
    settings = await _get_settings()
    _validate_delivery_slot(req.slot, settings)
    earn_rate, redeem_rate = _loyalty_cfg(settings)
    discount, coupon_code, coupon_err = await _resolve_coupon(req.coupon_code, subtotal, user, snaps)
    if req.coupon_code and coupon_err:
        raise HTTPException(400, coupon_err)
    ref_discount, referrer_id, ref_err = await _resolve_referral(req.referral_code, user, snaps)
    if req.referral_code and ref_err:
        raise HTTPException(400, ref_err)
    is_customer = user.role != "guest"
    pts_balance = user.loyalty_points if is_customer else 0
    max_redeem_cents = pts_balance * 100 // redeem_rate
    want_cents = max(0, req.redeem_points) * 100 // redeem_rate
    points_redeem_cents = min(want_cents, max_redeem_cents, max(0, subtotal - discount - ref_discount))
    points_consumed = round(points_redeem_cents * redeem_rate / 100) if points_redeem_cents else 0
    delivery_fee, dist_km, fee_tier = await compute_delivery_fee(req.address, settings)
    if _free_delivery_applies(subtotal, getattr(req.address, "city", None), settings):
        delivery_fee, fee_tier = 0, "free_delivery"
    taxable = max(0, subtotal + delivery_fee - discount - ref_discount - points_redeem_cents)
    tax_cents = (taxable * settings.get("tax_rate_bps", 1300)) // 10000 if _tax_enabled_for_method(settings, req.payment_method) else 0
    total = taxable + tax_cents

    # "card"|"stripe" → Stripe, "cod" → Cash on Delivery, "interac" → Interac e-Transfer (manual), "paypal" → PayPal (config-ready)
    payment_method = req.payment_method if req.payment_method in ("card", "cod", "interac", "paypal") else "card"
    now = datetime.now(timezone.utc)

    earn_on_subtotal = int((subtotal / 100.0) * earn_rate) if is_customer else 0
    if payment_method in ("cod", "interac"):
        status = "confirmed"
        payment_status = "cod_pending" if payment_method == "cod" else "interac_pending"
        label = "Cash on Delivery" if payment_method == "cod" else "Interac e-Transfer"
        tracking = [
            {"status": "new", "ts": now.isoformat(), "note": "Order created"},
            {"status": "confirmed", "ts": now.isoformat(), "note": f"Order confirmed ({label})"},
        ]
        points_awarded = earn_on_subtotal
    else:
        status = "pending_payment"
        payment_status = "pending"
        tracking = [{"status": "new", "ts": now.isoformat(), "note": "Order created, awaiting payment"}]
        points_awarded = 0

    order = Order(
        user_id=user.user_id,
        items_snapshot=snaps,
        address=req.address.model_dump(),
        slot=req.slot.model_dump(),
        phone=req.phone,
        subtotal_cents=subtotal,
        delivery_fee_cents=delivery_fee,
        tax_cents=tax_cents,
        tax_label=settings.get("tax_label", "HST"),
        discount_cents=discount,
        referral_discount_cents=ref_discount,
        points_redeemed_cents=points_redeem_cents,
        points_redeemed=points_consumed,
        total_cents=total,
        coupon_code=coupon_code,
        referral_code=req.referral_code if referrer_id else None,
        referrer_user_id=referrer_id,
        special_instructions=req.special_instructions or "",
        payment_method=payment_method,
        status=status,
        payment_status=payment_status,
        points_awarded=points_awarded,
        tracking_events=tracking,
    )
    order_doc = order.model_dump()
    # Stamp the public base URL (from the request / env) so invoice + tracking
    # links in SMS/email are absolute & clickable, and so later delivery
    # notifications reuse the same origin.
    order_doc["public_base_url"] = _public_base_from_request(request, req.client_base_url)
    order.public_base_url = order_doc["public_base_url"]
    await db.orders.insert_one(order_doc)

    # Save phone on user if not already saved.
    if req.phone and not user.phone:
        await db.users.update_one({"user_id": user.user_id}, {"$set": {"phone": req.phone}})

    # Save name on user record when the customer typed a real name on the
    # address. This is what turns a "Guest" into "Priya Roy" on future
    # orders. We only overwrite when the user's current name is empty
    # OR is an auto-generated placeholder like "Guest" / "Guest 12".
    addr_name = (req.address.name or "").strip() if hasattr(req.address, "name") else ""
    if addr_name:
        current_name = (user.name or "").strip()
        looks_placeholder = (
            not current_name
            or current_name.lower() == "guest"
            or current_name.lower().startswith("guest ")
            or current_name.lower().startswith("guest_")
        )
        if looks_placeholder:
            await db.users.update_one(
                {"user_id": user.user_id},
                {"$set": {"name": addr_name}},
            )

    # Auto-save this order's address as the user's default (so next time it's pre-filled).
    # Skip if the line1 was a placeholder ("TBD") — only real addresses get saved.
    if req.address.line1 and req.address.line1.strip().lower() != "tbd":
        await db.users.update_one(
            {"user_id": user.user_id},
            {"$set": {"default_address": req.address.model_dump()}},
        )

    if payment_method in ("cod", "interac"):
        # Decrement stock immediately (COD + Interac are both confirmed on placement).
        await _decrement_stock_for_order(order.model_dump())
        await db.users.update_one(
            {"user_id": user.user_id},
            {"$inc": {"loyalty_points": points_awarded - points_consumed}},
        )
        try:
            await _record_loyalty_and_coupon(order.model_dump(), user.user_id)
        except Exception as e:
            log.warning(f"[loyalty/coupon record] {e}")
        try:
            pay_line = (
                f"Pay CA${total/100:.2f} at delivery." if payment_method == "cod"
                else f"Send CA${total/100:.2f} via Interac e-Transfer to {(settings.get('payment_methods') or {}).get('interac', {}).get('email', '')}."
            )
            await send_push(
                recipients=[user.user_id],
                data={"title": "Order confirmed 🎉",
                      "message": f"Your {BRAND_NAME} order is being prepared. {pay_line}",
                      "action_url": f"/order/{order.order_id}"},
            )
        except Exception as e:
            log.warning(f"push fail: {e}")

        # Order confirmation → customer (email + SMS) and owner (email + SMS).
        try:
            fresh = await db.orders.find_one({"order_id": order.order_id}, {"_id": 0})
            u = await db.users.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
            await _notify_order_created(fresh or order.model_dump(), settings, u)
        except Exception as e:
            log.warning(f"order notify fail: {e}")

    return order.model_dump()


async def _decrement_stock_for_order(order: dict):
    """For each menu line in the order, decrement stock_used on the matching weekly line
    (if the current-week weekly menu references this master item)."""
    today = datetime.now(timezone.utc).date()
    week_start = _sunday_of(today).isoformat()
    for it in order.get("items_snapshot", []):
        if it.get("kind") != "menu":
            continue
        ref = it["ref_id"]
        qty = it["quantity"]
        # Try v2 line first.
        await db.weekly_menus.update_one(
            {"week_start": week_start, "lines.master_item_id": ref},
            {"$inc": {"lines.$.stock_used": qty}},
        )


@api.get("/orders")
async def list_my_orders(user: User = Depends(_current_user)):
    # Hide unpaid card orders — they only exist during Stripe handoff and are
    # cleaned up on failure. Users should not see "awaiting payment" lines.
    query = {
        "user_id": user.user_id,
        "status": {"$ne": "pending_payment"},
    }
    cur = db.orders.find(query, {"_id": 0}).sort("created_at", -1).limit(50)
    return await cur.to_list(50)


@api.get("/orders/{order_id}")
async def get_order(order_id: str, user: User = Depends(_current_user)):
    o = await db.orders.find_one({"order_id": order_id, "user_id": user.user_id}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Order not found")
    return o


@api.post("/orders/{order_id}/cancel-unpaid")
async def cancel_unpaid_order(order_id: str, user: User = Depends(_current_user)):
    """Called by frontend after Stripe checkout is cancelled or fails.
    Deletes the pending-payment order so the user never sees an 'awaiting payment' row,
    and sends a courtesy email letting them know."""
    order = await db.orders.find_one(
        {"order_id": order_id, "user_id": user.user_id}, {"_id": 0}
    )
    if not order:
        raise HTTPException(404, "Order not found")
    if order.get("payment_status") == "paid" or order.get("status") != "pending_payment":
        # Already paid or already moved past pending — refuse to delete.
        raise HTTPException(400, "Order is not pending payment and cannot be cancelled here")
    await db.orders.delete_one({"order_id": order_id, "user_id": user.user_id})
    # Cleanup Stripe tx row too.
    if order.get("stripe_session_id"):
        await db.payment_transactions.delete_many({"session_id": order["stripe_session_id"]})
    try:
        await send_email(
            to=user.email,
            subject=f"{BRAND_NAME} — Your order was not completed",
            body=(
                f"Hi {user.name}, we noticed the payment for your order was cancelled. "
                f"Nothing was charged. Come back anytime — this week's menu is still open. "
                f"Total attempted: CA${order['total_cents']/100:.2f}."
            ),
        )
    except Exception as e:
        log.warning(f"email fail: {e}")
    return {"ok": True, "deleted": True}


# ==========================================================
# CHECKOUT (Stripe hosted Checkout)
# ==========================================================
class CheckoutReq(BaseModel):
    order_id: str
    origin_url: str  # frontend origin to build success/cancel URLs
    return_base: Optional[str] = None  # optional same-origin base for Stripe return URLs (web shop)


@api.post("/checkout/session")
async def create_checkout_session(req: CheckoutReq, user: User = Depends(_current_user)):
    """Create a Stripe hosted Checkout session for an existing unpaid order."""
    order = await db.orders.find_one({"order_id": req.order_id, "user_id": user.user_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    if order.get("payment_method") in ("cod", "interac"):
        raise HTTPException(400, "This order does not require card checkout.")
    if order.get("payment_status") == "paid":
        raise HTTPException(400, "Order already paid")

    amount = int(order.get("total_cents", 0))
    if amount <= 0:
        raise HTTPException(400, "Invalid order total")
    stripe_sdk = _stripe()
    # Stripe replaces {CHECKOUT_SESSION_ID} with the real id on redirect.
    # Web shop checkout passes return_base = origin + "/shop" so Stripe
    # returns to /shop/order/{id}. Only accept same-origin bases (never an
    # arbitrary redirect target); otherwise fall back to origin_url.
    base = req.origin_url
    if req.return_base and req.return_base.startswith(req.origin_url):
        base = req.return_base
    success_url = f"{base}/order/{req.order_id}?paid=1&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/order/{req.order_id}?paid=0"
    try:
        session = await run_in_threadpool(
            stripe_sdk.checkout.Session.create,
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "cad",
                    "product_data": {"name": f"{BRAND_NAME} — Order #{req.order_id[-6:].upper()}"},
                    "unit_amount": amount,
                },
                "quantity": 1,
            }],
            client_reference_id=req.order_id,
            metadata={"order_id": req.order_id, "user_id": user.user_id},
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except stripe.StripeError as e:
        log.error(f"stripe checkout session create failed: {e}")
        raise HTTPException(502, "Unable to create Stripe checkout session") from e
    await db.payment_transactions.update_one(
        {"session_id": session.id},
        {"$set": {
            "session_id": session.id, "order_id": req.order_id,
            "user_id": user.user_id, "amount_cents": order["total_cents"],
            "currency": "cad", "status": "initiated", "payment_status": "pending",
            "created_at": datetime.now(timezone.utc),
        }}, upsert=True,
    )
    await db.orders.update_one(
        {"order_id": req.order_id},
        {"$set": {"stripe_session_id": session.id, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"url": session.url, "session_id": session.id}


@api.get("/checkout/status/{session_id}")
async def checkout_status(session_id: str, user: User = Depends(_current_user)):
    """Poll Stripe for a session's status and finalize the order on first paid."""
    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx or tx.get("user_id") != user.user_id:
        raise HTTPException(404, "Unknown checkout session")
    stripe_sdk = _stripe()
    try:
        remote = await run_in_threadpool(stripe_sdk.checkout.Session.retrieve, session_id)
    except stripe.StripeError as e:
        log.error(f"stripe checkout session retrieve failed: {e}")
        raise HTTPException(502, "Unable to retrieve Stripe checkout session") from e
    if remote.payment_status == "paid":
        await checkout_status_finalize(session_id)
    order = await db.orders.find_one({"order_id": tx["order_id"]}, {"_id": 0}) or {}
    return {
        "order_id": tx["order_id"],
        "status": remote.status,
        "payment_status": order.get("payment_status", tx.get("payment_status", "pending")),
    }


@api.post("/checkout/webhook")
async def checkout_webhook(request: Request):
    """Stripe webhook — authoritative confirmation. Idempotent via finalize()."""
    stripe_sdk = _stripe()
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        raise HTTPException(503, "Stripe webhook is not configured")
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe_sdk.Webhook.construct_event(body, sig, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as e:
        log.warning(f"stripe webhook verify fail: {e}")
        raise HTTPException(400, "Invalid webhook")
    if event.type == "checkout.session.completed":
        session_id = event.data.object.id
        try:
            session = await run_in_threadpool(
                stripe_sdk.checkout.Session.retrieve, session_id
            )
        except stripe.StripeError as e:
            log.error(f"stripe webhook session retrieve failed: {e}")
            raise HTTPException(502, "Unable to retrieve Stripe checkout session") from e
        if session.payment_status == "paid":
            await checkout_status_finalize(session.id)
    return {"received": True}


async def checkout_status_finalize(session_id: str):
    """Mark a card order paid exactly once (guards against double-crediting).

    Awards loyalty points, decrements stock and fires confirmation
    notifications the same way COD/Interac orders do on placement.
    """
    # Atomic compare-and-set: only the first caller flips the tx to paid.
    res = await db.payment_transactions.update_one(
        {"session_id": session_id, "status": {"$ne": "paid"}},
        {"$set": {"status": "paid", "payment_status": "paid", "paid_at": datetime.now(timezone.utc)}},
    )
    if res.modified_count == 0:
        return  # already finalized (or unknown) — no double credit
    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx:
        return
    order = await db.orders.find_one({"order_id": tx["order_id"]}, {"_id": 0})
    if not order or order.get("payment_status") == "paid":
        return

    now = datetime.now(timezone.utc)
    settings = await _get_settings()
    earn_rate, _ = _loyalty_cfg(settings)
    buyer = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0}) or {}
    is_customer = buyer.get("role") != "guest"
    points_awarded = int((order["subtotal_cents"] / 100.0) * earn_rate) if is_customer else 0
    tracking = order.get("tracking_events", []) + [
        {"status": "confirmed", "ts": now.isoformat(), "note": "Payment received (card)"},
    ]
    await db.orders.update_one(
        {"order_id": order["order_id"]},
        {"$set": {"payment_status": "paid", "status": "confirmed",
                  "points_awarded": points_awarded, "tracking_events": tracking, "updated_at": now}},
    )
    fresh = await db.orders.find_one({"order_id": order["order_id"]}, {"_id": 0}) or order
    try:
        await _decrement_stock_for_order(fresh)
    except Exception as e:
        log.warning(f"stock decrement fail: {e}")
    redeem_pts = int(order.get("points_redeemed", 0) or 0)
    await db.users.update_one(
        {"user_id": order["user_id"]},
        {"$inc": {"loyalty_points": points_awarded - redeem_pts}},
    )
    try:
        await _record_loyalty_and_coupon(fresh, order["user_id"])
    except Exception as e:
        log.warning(f"[loyalty/coupon record] {e}")
    try:
        settings = await _get_settings()
        u = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0}) or {}
        await _notify_order_created(fresh, settings, u)
    except Exception as e:
        log.warning(f"card order notify fail: {e}")
    try:
        await send_push(
            recipients=[order["user_id"]],
            data={"title": "Payment received 🎉",
                  "message": f"Your {BRAND_NAME} order is confirmed and being prepared.",
                  "action_url": f"/order/{order['order_id']}"},
        )
    except Exception as e:
        log.warning(f"push fail: {e}")


# ==========================================================
# ADMIN ORDER STATUS SIMULATION (public in MVP — protect later)
# ==========================================================
class OrderStatusUpdate(BaseModel):
    status: str  # "preparing" | "out_for_delivery" | "delivered"
    note: Optional[str] = ""


@api.post("/orders/{order_id}/status")
async def update_order_status(order_id: str, upd: OrderStatusUpdate):
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    events = order.get("tracking_events", []) + [{
        "status": upd.status,
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": upd.note or "",
    }]
    await db.orders.update_one(
        {"order_id": order_id},
        {"$set": {"status": upd.status, "tracking_events": events,
                  "updated_at": datetime.now(timezone.utc)}},
    )
    try:
        await _clawback_points_if_cancelled(order, upd.status)
    except Exception as e:
        log.warning(f"[points clawback] {e}")
    try:
        await send_push(
            recipients=[order["user_id"]],
            data={"title": f"Order update: {upd.status.replace('_',' ').title()}",
                  "message": upd.note or "Your order status changed.",
                  "action_url": f"/order/{order_id}"},
        )
    except Exception:
        pass
    return {"ok": True}


# ==========================================================
# DELIVERY PARTNER
# ==========================================================
@api.post("/delivery-partner/apply")
async def apply_delivery(app_in: DeliveryPartnerApplication):
    doc = app_in.model_dump()
    await db.delivery_applications.insert_one(doc)
    try:
        await send_email(app_in.email, f"{BRAND_NAME} — Application received",
                         f"Hi {app_in.full_name}, we received your delivery partner application.")
    except Exception:
        pass
    return {"ok": True, "app_id": app_in.app_id}


# ==========================================================
# PUSH REGISTRATION
# ==========================================================
@api.post("/register-push", status_code=201)
async def register_push(body: PushRegisterReq):
    # Store the Expo token locally (replaces the Emergent relay registry);
    # send_push resolves user_ids through this collection.
    try:
        await db.push_tokens.update_one(
            {"user_id": body.user_id, "token": body.device_token},
            {"$set": {"user_id": body.user_id, "token": body.device_token,
                      "platform": body.platform,
                      "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception as e:
        log.warning(f"register-push error (non-blocking): {e}")
    return {"status": "registered"}


# ==========================================================
# SEED / HEALTH
# ==========================================================
@api.get("/")
async def root():
    return {"service": "bongconnekt-api", "ok": True}


BENGALI_MENU_TEMPLATES = [
    {
        "name": "Kolkata Chicken Biryani",
        "description": "Slow-cooked long-grain basmati with tender chicken, potatoes, boiled egg and Kolkata masala.",
        "price_cents": 1899,
        "image_url": "https://images.pexels.com/photos/31537385/pexels-photo-31537385.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "rice",
        "tags": ["signature", "spicy"],
        "is_featured": True,
    },
    {
        "name": "Shorshe Ilish",
        "description": "Hilsa fish steamed in traditional mustard-poppy paste. Bengali monsoon classic.",
        "price_cents": 2299,
        "image_url": "https://images.pexels.com/photos/9345647/pexels-photo-9345647.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "curry",
        "tags": ["seafood", "signature"],
        "is_featured": True,
    },
    {
        "name": "Kosha Mangsho",
        "description": "Rich slow-cooked Bengali mutton in caramelized onion & warm spices.",
        "price_cents": 2099,
        "image_url": "https://images.pexels.com/photos/35267281/pexels-photo-35267281.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "curry",
        "tags": ["mutton", "signature"],
        "is_featured": False,
    },
    {
        "name": "Cholar Dal",
        "description": "Bengal gram dal tempered with coconut, ghee, raisins and warm spices.",
        "price_cents": 999,
        "image_url": "https://images.pexels.com/photos/35539325/pexels-photo-35539325.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "veg",
        "tags": ["vegetarian"],
        "is_featured": False,
    },
    {
        "name": "Aloo Posto",
        "description": "Baby potatoes in creamy poppy-seed paste, a Bengali comfort classic.",
        "price_cents": 1099,
        "image_url": "https://images.pexels.com/photos/9345647/pexels-photo-9345647.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "veg",
        "tags": ["vegetarian"],
        "is_featured": False,
    },
    {
        "name": "Luchi & Aloor Dom",
        "description": "Fluffy fried flatbread with spicy potato curry — the ultimate Bengali brunch.",
        "price_cents": 1299,
        "image_url": "https://images.pexels.com/photos/35267281/pexels-photo-35267281.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "starter",
        "tags": ["breakfast"],
        "is_featured": False,
    },
    {
        "name": "Mishti Doi",
        "description": "Traditional Bengali sweet yogurt with caramelized jaggery, served chilled.",
        "price_cents": 599,
        "image_url": "https://images.pexels.com/photos/35539325/pexels-photo-35539325.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "dessert",
        "tags": ["sweet"],
        "is_featured": False,
    },
    {
        "name": "Rosogolla (6 pcs)",
        "description": "Soft cottage cheese dumplings soaked in fragrant sugar syrup.",
        "price_cents": 799,
        "image_url": "https://images.pexels.com/photos/31537385/pexels-photo-31537385.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "category": "dessert",
        "tags": ["sweet", "signature"],
        "is_featured": True,
    },
]

CATERING_PACKAGES = []  # deprecated — packages are now built dynamically in seed() below.

# Additional master menu items required by catering packages.
# category values match the existing MasterMenuItem set: starter | veg | curry | rice | dessert | beverage | side | bread
CATERING_MASTER_EXTRAS = [
    # ---- Snacks / starters ----
    {"name": "Kolkata Egg Roll", "description": "Flaky paratha wrapped around spiced egg, onions and green chutney.",
     "price_cents": 649, "category": "starter", "veg_type": "eggitarian",
     "image_url": "https://images.unsplash.com/photo-1631515243349-e0cb75fb8d3a?auto=format&fit=crop&w=800&q=80"},
    {"name": "Chicken Kathi Roll", "description": "Grilled chicken tikka in a soft paratha with mint chutney.",
     "price_cents": 799, "category": "starter", "veg_type": "non-vegetarian",
     "image_url": "https://images.unsplash.com/photo-1633945274309-2c16c96d020a?auto=format&fit=crop&w=800&q=80"},
    {"name": "Fish Fry", "description": "Bengali-style crumb-fried bhetki with lemon and kasundi.",
     "price_cents": 849, "category": "starter", "veg_type": "non-vegetarian", "allergens": ["seafood"],
     "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=800&q=80"},
    {"name": "Veg Chop", "description": "Beetroot-and-peanut croquettes with muri and kasundi.",
     "price_cents": 499, "category": "starter", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=800&q=80"},
    {"name": "Mochar Chop", "description": "Banana-flower cutlets, a Kolkata tea-time favourite.",
     "price_cents": 499, "category": "starter", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1625944230945-1b7dd3b949ab?auto=format&fit=crop&w=800&q=80"},
    {"name": "Chicken Pakora", "description": "Crispy gram-flour fritters with spiced chicken.",
     "price_cents": 699, "category": "starter", "veg_type": "non-vegetarian",
     "image_url": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=800&q=80"},
    {"name": "Egg Devil", "description": "Boiled egg encased in spiced potato and fried golden.",
     "price_cents": 549, "category": "starter", "veg_type": "eggitarian",
     "image_url": "https://images.unsplash.com/photo-1541544741938-0af808871cc0?auto=format&fit=crop&w=800&q=80"},

    # ---- Beverages ----
    {"name": "Masala Tea Pitcher", "description": "Cardamom-clove chai brewed the Kolkata way (serves ~6).",
     "price_cents": 1499, "category": "beverage", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1571934811356-5cc061b6821f?auto=format&fit=crop&w=800&q=80"},
    {"name": "Bengali Doodh Cha Pitcher", "description": "Extra-milky, extra-sweet Bengali tea (serves ~6).",
     "price_cents": 1499, "category": "beverage", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1517701550927-30cf4ba1dba5?auto=format&fit=crop&w=800&q=80"},
    {"name": "Coffee Pitcher", "description": "South-Indian filter coffee — smooth and aromatic.",
     "price_cents": 1499, "category": "beverage", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?auto=format&fit=crop&w=800&q=80"},
    {"name": "Tea & Coffee Station", "description": "Full self-serve tea + coffee service for events.",
     "price_cents": 0, "category": "beverage", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1511920170033-f8396924c348?auto=format&fit=crop&w=800&q=80"},
    {"name": "Soft Drink Service", "description": "Assorted chilled soft drinks (Coke, Sprite, Thums Up).",
     "price_cents": 0, "category": "beverage", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?auto=format&fit=crop&w=800&q=80"},

    # ---- Veg mains ----
    {"name": "Aloor Dom", "description": "Baby potatoes slow-cooked in spiced tomato-onion gravy.",
     "price_cents": 999, "category": "veg", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1567337710282-00832b415979?auto=format&fit=crop&w=800&q=80"},
    {"name": "Mochar Ghonto", "description": "Banana-flower cooked with coconut, cumin and ghee.",
     "price_cents": 1099, "category": "veg", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1625944230945-1b7dd3b949ab?auto=format&fit=crop&w=800&q=80"},
    {"name": "Shukto", "description": "Bengali medley of bitter and sweet vegetables in a milky broth.",
     "price_cents": 999, "category": "veg", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1631515243349-e0cb75fb8d3a?auto=format&fit=crop&w=800&q=80"},
    {"name": "Mixed Vegetable Curry", "description": "Seasonal vegetables in a light Bengali panch-phoron gravy.",
     "price_cents": 999, "category": "veg", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1585032226651-759b368d7246?auto=format&fit=crop&w=800&q=80"},
    {"name": "Paneer Butter Masala", "description": "Cottage cheese in a rich tomato-butter gravy.",
     "price_cents": 1299, "category": "veg", "veg_type": "vegetarian", "allergens": ["dairy"],
     "image_url": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=800&q=80"},

    # ---- Non-veg mains ----
    {"name": "Chicken Kosha", "description": "Bengali-style caramelised chicken with warm mustard-cumin masala.",
     "price_cents": 1799, "category": "curry", "veg_type": "non-vegetarian",
     "image_url": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=800&q=80"},
    {"name": "Rui Kalia", "description": "Rohu fish curry in a rich onion-tomato gravy.",
     "price_cents": 1599, "category": "curry", "veg_type": "non-vegetarian", "allergens": ["seafood"],
     "image_url": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=800&q=80"},
    {"name": "Egg Curry", "description": "Boiled eggs simmered in Bengali onion-tomato curry.",
     "price_cents": 1199, "category": "curry", "veg_type": "eggitarian",
     "image_url": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=800&q=80"},
    {"name": "Chicken Rezala", "description": "White chicken curry cooked in yogurt, cashew and rosewater.",
     "price_cents": 1899, "category": "curry", "veg_type": "non-vegetarian",
     "image_url": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=800&q=80"},
    {"name": "Chingri Malaikari", "description": "Prawns in a creamy coconut-milk gravy — Bengali royalty.",
     "price_cents": 2299, "category": "curry", "veg_type": "non-vegetarian", "allergens": ["seafood"],
     "image_url": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=800&q=80"},
    {"name": "Chicken Chaap", "description": "Slow-braised chicken in yogurt-cashew Mughlai gravy.",
     "price_cents": 1999, "category": "curry", "veg_type": "non-vegetarian",
     "image_url": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=800&q=80"},

    # ---- Rice & bread ----
    {"name": "Basanti Pulao", "description": "Saffron-turmeric sweet pulao with cashews and raisins.",
     "price_cents": 1099, "category": "rice", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1585032226651-759b368d7246?auto=format&fit=crop&w=800&q=80"},
    {"name": "Steamed Rice", "description": "Long-grain white rice served hot.",
     "price_cents": 399, "category": "rice", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1516684732162-798a0062be99?auto=format&fit=crop&w=800&q=80"},

    # ---- Desserts ----
    {"name": "Payesh", "description": "Bengali rice pudding slow-cooked with jaggery and cardamom.",
     "price_cents": 549, "category": "dessert", "veg_type": "vegetarian", "allergens": ["dairy"],
     "image_url": "https://images.unsplash.com/photo-1571934811356-5cc061b6821f?auto=format&fit=crop&w=800&q=80"},
    {"name": "Pantua", "description": "Deep-fried khoya dumplings in cardamom sugar syrup.",
     "price_cents": 599, "category": "dessert", "veg_type": "vegetarian", "allergens": ["dairy"],
     "image_url": "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=800&q=80"},
    {"name": "Rajbhog", "description": "King-sized rosogolla stuffed with saffron and cardamom.",
     "price_cents": 699, "category": "dessert", "veg_type": "vegetarian", "allergens": ["dairy"],
     "image_url": "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=800&q=80"},

    # ---- Accompaniments (as starters/sides) ----
    {"name": "Bengali Salad", "description": "Fresh cucumber, radish, onion and lemon salad.",
     "price_cents": 299, "category": "starter", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?auto=format&fit=crop&w=800&q=80"},
    {"name": "Aam Kasundi Chutney", "description": "Sweet-tangy mango chutney with Bengali mustard.",
     "price_cents": 299, "category": "starter", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=800&q=80"},
    {"name": "Papad Platter", "description": "Assorted roasted and fried papads.",
     "price_cents": 299, "category": "starter", "veg_type": "vegetarian",
     "image_url": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=800&q=80"},
]

COUPONS_SEED = [
    {"code": "WELCOME10", "discount_type": "percent", "value": 10, "active": True,
     "min_order_cents": 2000, "description": "10% off first order over $20"},
    {"code": "BENGALI15", "discount_type": "percent", "value": 15, "active": True,
     "min_order_cents": 5000, "description": "15% off orders over $50"},
    {"code": "MISHTI5", "discount_type": "fixed", "value": 500, "active": True,
     "min_order_cents": 3000, "description": "$5 off orders over $30"},
]


class AdminLoginReq(BaseModel):
    email: str
    password: str


async def _current_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing admin bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        raise HTTPException(401, "Invalid admin token")
    if payload.get("role") != "admin":
        raise HTTPException(403, "Not an admin token")
    return {"email": payload.get("sub"), "role": "admin"}


@api.post("/admin/login")
async def admin_login(req: AdminLoginReq):
    admin = await db.admins.find_one({"email": req.email.lower()}, {"_id": 0})
    if not admin or not _pwd.verify(req.password, admin["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode(
        {"sub": admin["email"], "role": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=12)},
        JWT_SECRET, algorithm=JWT_ALG,
    )
    return {"access_token": token, "token_type": "bearer",
            "admin": {"email": admin["email"]}}


@api.get("/admin/me")
async def admin_me(admin=Depends(_current_admin)):
    return admin


# ----- Menu management -----
@api.get("/admin/menus")
async def admin_list_menus(admin=Depends(_current_admin)):
    cur = db.weekly_menus.find({}, {"_id": 0}).sort("week_start", -1).limit(52)
    return await cur.to_list(52)


@api.post("/admin/menus")
async def admin_upsert_menu(menu: WeeklyMenu, admin=Depends(_current_admin)):
    doc = menu.model_dump()
    await db.weekly_menus.update_one(
        {"week_start": menu.week_start}, {"$set": doc}, upsert=True
    )
    return {"ok": True, "menu": doc}


@api.delete("/admin/menus/{week_start}")
async def admin_delete_menu(week_start: str, admin=Depends(_current_admin)):
    r = await db.weekly_menus.delete_one({"week_start": week_start})
    return {"ok": True, "deleted": r.deleted_count}


class MenuItemUpsertReq(BaseModel):
    item: MenuItem


@api.post("/admin/menus/{week_start}/items")
async def admin_add_menu_item(week_start: str, req: MenuItemUpsertReq,
                              admin=Depends(_current_admin)):
    menu = await db.weekly_menus.find_one({"week_start": week_start}, {"_id": 0})
    if not menu:
        raise HTTPException(404, "Menu not found for that week")
    items = menu.get("items", [])
    # If item_id already exists → update; else append.
    replaced = False
    for i, it in enumerate(items):
        if it.get("item_id") == req.item.item_id:
            items[i] = req.item.model_dump()
            replaced = True
            break
    if not replaced:
        items.append(req.item.model_dump())
    await db.weekly_menus.update_one(
        {"week_start": week_start}, {"$set": {"items": items}}
    )
    return {"ok": True, "item": req.item.model_dump(), "replaced": replaced}


@api.delete("/admin/menus/{week_start}/items/{item_id}")
async def admin_delete_menu_item(week_start: str, item_id: str,
                                 admin=Depends(_current_admin)):
    r = await db.weekly_menus.update_one(
        {"week_start": week_start}, {"$pull": {"items": {"item_id": item_id}}}
    )
    return {"ok": True, "modified": r.modified_count}


# ----- Catering management -----
@api.get("/admin/catering")
async def admin_list_catering(admin=Depends(_current_admin)):
    cur = db.catering_packages.find({}, {"_id": 0}).sort([("sort_order", 1), ("price_cents", 1)])
    return await cur.to_list(100)


@api.post("/admin/catering")
async def admin_upsert_catering(pkg: CateringPackage, admin=Depends(_current_admin)):
    doc = pkg.model_dump()
    await db.catering_packages.update_one(
        {"package_id": pkg.package_id}, {"$set": doc}, upsert=True
    )
    return {"ok": True, "package": doc}


@api.delete("/admin/catering/{package_id}")
async def admin_delete_catering(package_id: str, admin=Depends(_current_admin)):
    r = await db.catering_packages.delete_one({"package_id": package_id})
    return {"ok": True, "deleted": r.deleted_count}


# ----- Thali management -----
@api.get("/admin/thali")
async def admin_list_thali(admin=Depends(_current_admin)):
    cur = db.thali_packages.find({}, {"_id": 0}).sort([("sort_order", 1), ("per_person_price_cents", 1)])
    return await cur.to_list(100)


@api.post("/admin/thali")
async def admin_upsert_thali(pkg: ThaliPackage, admin=Depends(_current_admin)):
    doc = pkg.model_dump()
    await db.thali_packages.update_one({"package_id": pkg.package_id}, {"$set": doc}, upsert=True)
    return {"ok": True, "package": doc}


@api.delete("/admin/thali/{package_id}")
async def admin_delete_thali(package_id: str, admin=Depends(_current_admin)):
    r = await db.thali_packages.delete_one({"package_id": package_id})
    return {"ok": True, "deleted": r.deleted_count}


# ----- Grocery management -----
@api.get("/admin/grocery")
async def admin_list_grocery(
    q: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    limit: int = 30,
    admin=Depends(_current_admin),
):
    page = max(1, page)
    limit = max(1, min(100, limit))
    query: Dict[str, Any] = {"deleted_at": None}
    if category and category != "All":
        query["category"] = category
    if q:
        query["title"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    total = await db.grocery.count_documents(query)
    cur = (
        db.grocery.find(query, {"_id": 0})
        .sort([("sort_order", 1), ("title", 1)])
        .skip((page - 1) * limit)
        .limit(limit)
    )
    docs = await cur.to_list(limit)
    return {"items": docs, "total": total, "page": page,
            "pages": (total + limit - 1) // limit, "limit": limit}


@api.post("/admin/grocery")
async def admin_upsert_grocery(item: GroceryItem, admin=Depends(_current_admin)):
    doc = item.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc)
    existing = await db.grocery.find_one({"item_id": item.item_id}, {"_id": 0})
    if existing:
        doc["created_at"] = existing.get("created_at", doc["created_at"])
        doc["deleted_at"] = existing.get("deleted_at")
    else:
        doc.setdefault("deleted_at", None)
    await db.grocery.update_one({"item_id": item.item_id}, {"$set": doc}, upsert=True)
    return {"ok": True, "item_id": item.item_id}


@api.delete("/admin/grocery/{item_id}")
async def admin_delete_grocery(item_id: str, admin=Depends(_current_admin)):
    # Soft delete — keep the row for history/restore.
    r = await db.grocery.update_one(
        {"item_id": item_id},
        {"$set": {"deleted_at": datetime.now(timezone.utc), "is_active": False}},
    )
    return {"ok": True, "modified": r.modified_count}


def _clean_doc(d: dict) -> dict:
    d = dict(d)
    d.pop("_id", None)
    return d


@api.get("/admin/export/meal-plan")
async def admin_export_meal_plan(admin=Depends(_current_admin)):
    """Snapshot all meal-plan data (weekly menus + master menu) as JSON so it
    can be pushed into another environment's DB via /admin/import/meal-plan."""
    menus = [_clean_doc(d) async for d in db.weekly_menus.find({})]
    master = [_clean_doc(d) async for d in db.master_menu.find({})]
    return {"weekly_menus": menus, "master_menu": master,
            "counts": {"weekly_menus": len(menus), "master_menu": len(master)}}


class MealPlanImportReq(BaseModel):
    weekly_menus: List[dict] = []
    master_menu: List[dict] = []


@api.post("/admin/import/meal-plan")
async def admin_import_meal_plan(req: MealPlanImportReq, admin=Depends(_current_admin)):
    """Upsert meal-plan data into THIS environment's DB (idempotent).
    weekly_menus keyed by menu_id (fallback week_start); master_menu by item_id."""
    wm_n = mm_n = 0
    for m in req.master_menu:
        iid = m.get("item_id")
        if not iid:
            continue
        await db.master_menu.replace_one({"item_id": iid}, _clean_doc(m), upsert=True)
        mm_n += 1
    for wm in req.weekly_menus:
        key = {"menu_id": wm["menu_id"]} if wm.get("menu_id") else {"week_start": wm.get("week_start")}
        if not (key.get("menu_id") or key.get("week_start")):
            continue
        await db.weekly_menus.replace_one(key, _clean_doc(wm), upsert=True)
        wm_n += 1
    return {"ok": True, "imported": {"weekly_menus": wm_n, "master_menu": mm_n}}


class PricingZoneReq(BaseModel):
    zone_id: Optional[str] = None
    name: str
    region: Optional[str] = None
    postal_prefixes: List[str] = []
    cities: List[str] = []           # city names served by this zone (match on address.city)
    fee_cents: Optional[int] = None  # flat delivery fee for this zone; None = surcharge-only zone
    surcharge_cents: int = 0
    enabled: bool = True


@api.get("/admin/pricing-zones")
async def admin_list_zones(admin=Depends(_current_admin)):
    zones = [_clean_doc(z) async for z in db.pricing_zones.find({}).sort("name", 1)]
    return {"zones": zones}


@api.post("/admin/pricing-zones")
async def admin_upsert_zone(req: PricingZoneReq, admin=Depends(_current_admin)):
    if not (req.name or "").strip():
        raise HTTPException(400, "Zone name is required")
    zid = req.zone_id or ("pz_" + uuid.uuid4().hex[:10])
    prefixes = sorted({_normalize_postal(p) for p in req.postal_prefixes if p and p.strip()})
    doc = {"zone_id": zid, "name": req.name.strip(), "region": (req.region or "").strip() or None,
           "postal_prefixes": prefixes,
           "cities": sorted({c.strip() for c in (req.cities or []) if c and c.strip()}),
           "fee_cents": (int(req.fee_cents) if req.fee_cents is not None else None),
           "surcharge_cents": int(req.surcharge_cents or 0), "enabled": bool(req.enabled),
           "updated_at": datetime.now(timezone.utc)}
    await db.pricing_zones.update_one({"zone_id": zid}, {"$set": doc}, upsert=True)
    return {"ok": True, "zone": _clean_doc(doc)}


@api.delete("/admin/pricing-zones/{zone_id}")
async def admin_delete_zone(zone_id: str, admin=Depends(_current_admin)):
    r = await db.pricing_zones.delete_one({"zone_id": zone_id})
    return {"ok": True, "deleted": r.deleted_count}


class BulkRecategorizeReq(BaseModel):
    target_category: str
    item_ids: Optional[List[str]] = None    # move these specific items, OR
    from_category: Optional[str] = None      # move every (non-deleted) item in this category


@api.post("/admin/grocery/bulk-recategorize")
async def admin_grocery_bulk_recategorize(req: BulkRecategorizeReq, admin=Depends(_current_admin)):
    """Reassign the category of many grocery items at once.

    Pass either an explicit list of `item_ids`, or a `from_category` to move the
    whole category. `target_category` is required in both cases.
    """
    target = (req.target_category or "").strip()
    if not target:
        raise HTTPException(400, "target_category is required")
    query: Dict[str, Any] = {"deleted_at": None}
    if req.item_ids:
        query["item_id"] = {"$in": req.item_ids}
    elif req.from_category:
        query["category"] = req.from_category
    else:
        raise HTTPException(400, "Provide either item_ids or from_category")
    r = await db.grocery.update_many(
        query,
        {"$set": {"category": target, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"ok": True, "modified": r.modified_count, "target_category": target}


@api.post("/admin/grocery/upload-image")
async def admin_grocery_upload_image(file: UploadFile = File(...), admin=Depends(_current_admin)):
    ext = (Path(file.filename or "").suffix or ".jpg").lower().lstrip(".")
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        ext = "jpg"
    name = f"gr_{uuid.uuid4().hex[:16]}.{ext}"
    content = await file.read()
    # Store in MinIO object storage (persistent + shared across instances and
    # environments) and serve via /api/files/* — NOT container-local disk, which
    # is ephemeral in production and causes intermittent 404s.
    path = f"{_obj.APP_NAME}/grocery/{name}"
    ct = _STORAGE_CT.get(ext, "image/jpeg")
    await run_in_threadpool(_obj.put_object, path, content, ct)
    return {"ok": True, "image_url": f"/api/files/{path}"}


class GroceryBulkReq(BaseModel):
    items: List[GroceryItem]


@api.post("/admin/grocery/bulk-import")
async def admin_grocery_bulk_import(req: GroceryBulkReq, admin=Depends(_current_admin)):
    """Upsert a batch of grocery items (matched by source_id when present, else item_id)."""
    upserted = 0
    for it in req.items:
        doc = it.model_dump()
        doc["updated_at"] = datetime.now(timezone.utc)
        doc.setdefault("deleted_at", None)
        key = {"source_id": it.source_id} if it.source_id else {"item_id": it.item_id}
        await db.grocery.update_one(key, {"$set": doc}, upsert=True)
        upserted += 1
    return {"ok": True, "upserted": upserted}


@api.get("/admin/grocery/template")
async def admin_grocery_download_template(admin=Depends(_current_admin)):
    """Download the .xlsx catalogue template (headers + sample rows)."""
    from grocery_template import build_template_xlsx
    from fastapi.responses import Response
    data = build_template_xlsx()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="BongConnekt_Product_Catalogue_Template.xlsx"',
            "Cache-Control": "no-store, private",
        },
    )


@api.post("/admin/grocery/upload-template")
async def admin_grocery_upload_template(file: UploadFile = File(...), admin=Depends(_current_admin)):
    """Parse a filled catalogue .xlsx and upsert products (matched by title).

    Rows sharing the same "Item" name collapse into one product with variants.
    Existing products keep their photos, featured flag and sort order; only the
    catalogue fields (prices, variants, category, description, stock) are refreshed.
    New products are created with no image — the admin adds photos later.
    """
    from grocery_template import parse_catalogue_xlsx

    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload the .xlsx template file.")
    content = await file.read()
    try:
        products, row_errors = await asyncio.to_thread(parse_catalogue_xlsx, content)
    except Exception as e:
        raise HTTPException(400, f"Could not read the spreadsheet: {e}")
    if not products and not row_errors:
        raise HTTPException(400, "No products found. Make sure the 'Item' column is filled in.")

    now = datetime.now(timezone.utc)
    inserted = 0
    updated = 0
    for p in products:
        existing = await db.grocery.find_one(
            {"title": p["title"], "deleted_at": None}, {"_id": 0}
        )
        # Build variants, reusing existing variant_ids where the title matches
        # so links/carts stay stable across re-uploads.
        prev_variants = (existing or {}).get("variants", []) if existing else []
        prev_by_title = {str(v.get("title", "")).strip().lower(): v.get("variant_id") for v in prev_variants}
        variants = []
        for v in p["variants"]:
            vid = prev_by_title.get(v["title"].strip().lower()) or f"v_{uuid.uuid4().hex[:12]}"
            variants.append({
                "variant_id": vid,
                "title": v["title"],
                "price_cents": v["price_cents"],
                "compare_at_cents": v["compare_at_cents"],
                "available": v["available"],
                "sku": "",
                "weight_g": v["weight_g"],
            })

        if existing:
            update = {
                "category": p["category"],
                "all_categories": p["all_categories"],
                "price_cents": p["price_cents"],
                "compare_at_cents": p["compare_at_cents"],
                "variants": variants,
                "has_variants": p["has_variants"],
                "on_sale": p["on_sale"],
                "in_stock": p["in_stock"],
                "is_active": True,
                "updated_at": now,
            }
            # Only overwrite description when the upload actually provided one.
            if p["description"]:
                update["description"] = p["description"]
            await db.grocery.update_one({"item_id": existing["item_id"]}, {"$set": update})
            updated += 1
        else:
            doc = {
                "item_id": f"gr_{uuid.uuid4().hex[:12]}",
                "title": p["title"],
                "handle": "",
                "description": p["description"],
                "category": p["category"],
                "all_categories": p["all_categories"],
                "price_cents": p["price_cents"],
                "compare_at_cents": p["compare_at_cents"],
                "unit": "",
                "image_url": "",
                "images": [],
                "vendor": "",
                "tags": [],
                "variants": variants,
                "has_variants": p["has_variants"],
                "on_sale": p["on_sale"],
                "in_stock": p["in_stock"],
                "is_active": True,
                "is_featured": False,
                "sort_order": 0,
                "source_id": "",
                "product_url": "",
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            }
            await db.grocery.insert_one(doc)
            inserted += 1

    return {"ok": True, "inserted": inserted, "updated": updated,
            "products": len(products), "errors": row_errors, "skipped": len(row_errors)}


@api.post("/admin/grocery/import-from-store")
async def admin_grocery_import_from_store(body: dict = None, admin=Depends(_current_admin)):
    """Bulk import the whole catalog from the tenant's Shopify products.json feed.
    Matches existing rows by source_id so re-running is idempotent (updates prices/images)."""
    from grocery_import import build_grocery_docs, STORE_PRODUCTS_URL
    url = (body or {}).get("url") or STORE_PRODUCTS_URL
    try:
        docs = await asyncio.to_thread(build_grocery_docs, url)
    except Exception as e:
        raise HTTPException(400, f"Could not fetch store feed: {e}")
    inserted = 0
    updated = 0
    for d in docs:
        d["updated_at"] = datetime.now(timezone.utc)
        d.setdefault("deleted_at", None)
        existing = await db.grocery.find_one({"source_id": d["source_id"]}, {"_id": 0, "item_id": 1, "created_at": 1, "is_featured": 1, "sort_order": 1})
        if existing:
            # preserve admin-managed fields
            d["item_id"] = existing["item_id"]
            d["created_at"] = existing.get("created_at", d["created_at"])
            d["is_featured"] = existing.get("is_featured", False)
            d["sort_order"] = existing.get("sort_order", 0)
            await db.grocery.update_one({"source_id": d["source_id"]}, {"$set": d})
            updated += 1
        else:
            await db.grocery.insert_one(d)
            inserted += 1
    return {"ok": True, "inserted": inserted, "updated": updated, "total": len(docs)}


# ----- Orders management -----
@api.get("/admin/orders")
async def admin_list_orders(status_filter: Optional[str] = None,
                            statuses: Optional[str] = None,
                            admin=Depends(_current_admin)):
    q: dict = {}
    if status_filter:
        q["status"] = status_filter
    elif statuses:
        vals = [s.strip() for s in statuses.split(",") if s.strip()]
        if vals:
            q["status"] = {"$in": vals}
    cur = db.orders.find(q, {"_id": 0}).sort("created_at", -1).limit(200)
    orders = await cur.to_list(200)
    # Batch-resolve linked users → attach a friendly customer_name + a user_summary blob.
    user_ids = list({o["user_id"] for o in orders if o.get("user_id")})
    users: dict = {}
    if user_ids:
        async for u in db.users.find({"user_id": {"$in": user_ids}},
                                     {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1}):
            users[u["user_id"]] = u
    for o in orders:
        u = users.get(o.get("user_id")) or {}
        addr_name = ((o.get("address") or {}).get("name") or "").strip()
        user_name = (u.get("name") or "").strip()
        o["customer_name"] = addr_name or user_name or "Guest"
        o["user_summary"] = u
    return orders


class AdminOrderStatusReq(BaseModel):
    status: str
    note: Optional[str] = ""


@api.post("/admin/orders/{order_id}/status")
async def admin_update_order_status(order_id: str, req: AdminOrderStatusReq,
                                    admin=Depends(_current_admin)):
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    events = order.get("tracking_events", []) + [{
        "status": req.status,
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": req.note or "",
    }]
    await db.orders.update_one(
        {"order_id": order_id},
        {"$set": {"status": req.status, "tracking_events": events,
                  "updated_at": datetime.now(timezone.utc)}},
    )
    try:
        await _clawback_points_if_cancelled(order, req.status)
    except Exception as e:
        log.warning(f"[points clawback] {e}")
    try:
        await send_push(
            recipients=[order["user_id"]],
            data={"title": f"Order update: {req.status.replace('_',' ').title()}",
                  "message": req.note or "Your order status changed.",
                  "action_url": f"/order/{order_id}"},
        )
    except Exception:
        pass
    return {"ok": True}


@api.get("/admin/stats")
async def admin_stats(admin=Depends(_current_admin)):
    total_orders = await db.orders.count_documents({"status": {"$ne": "pending_payment"}})
    delivered = await db.orders.count_documents({"status": "delivered"})
    active = await db.orders.count_documents({
        "status": {"$in": ["preparing", "out_for_delivery"]}
    })
    users = await db.users.count_documents({})
    # gross revenue (paid + cod combined)
    pipe = [
        {"$match": {"status": {"$ne": "pending_payment"}}},
        {"$group": {"_id": None, "sum": {"$sum": "$total_cents"}}},
    ]
    agg = await db.orders.aggregate(pipe).to_list(1)
    revenue_cents = (agg[0]["sum"] if agg else 0) or 0
    return {
        "total_orders": total_orders,
        "delivered": delivered,
        "active": active,
        "users": users,
        "revenue_cents": revenue_cents,
    }


# ==========================================================
# PUBLIC SETTINGS (customer app reads tax label etc.)
# ==========================================================
@api.get("/brand")
async def brand_info():
    """Public brand metadata — consumed by the web admin bundle so it can
    show the tenant's brand name/legal name/support email without needing
    a build-time recompile per tenant. Never returns secrets."""
    return brand_as_dict()


@api.get("/platform/status")
async def platform_status():
    """Public snapshot of what the Suparna Dey Platform last told us about
    this tenant. Consumed by the admin dashboard banner and the customer
    cart to decide whether to hide checkout.

    Returns `{known: false, operational: true}` when the tenant isn't wired
    to a platform (safe fail-open for dev/preview)."""
    from platform_client import snapshot
    return snapshot()


# ---------------------------------------------------------------------------
# Suparna Dey Platform · Billing (Phase 3)
# ---------------------------------------------------------------------------
# These endpoints are the tenant-side proxy in front of the central hub's
# Stripe integration. The hub owns Stripe entirely; we just pass through
# the tenant's own API key on every request so the hub can identify us.
#
# UI contract (see /app/frontend/app/admin/billing.tsx):
#   GET  /admin/billing/summary   → { status, plan, card, invoices, ... }
#   POST /admin/billing/subscribe → { url }   Stripe Checkout URL
#   POST /admin/billing/portal    → { url }   Stripe Customer Portal URL

class _BillingUrlsReq(BaseModel):
    success_url: Optional[str] = None
    cancel_url:  Optional[str] = None
    return_url:  Optional[str] = None


@api.get("/admin/billing/summary")
async def admin_billing_summary(force: bool = False, admin=Depends(_current_admin)):
    """Returns the current billing state as seen from the hub. Cached 60s
    server-side. Pass `?force=true` to bust the cache after a Stripe redirect."""
    from billing_client import get_summary
    return await get_summary(force=force)


@api.post("/admin/billing/subscribe")
async def admin_billing_subscribe(req: _BillingUrlsReq, admin=Depends(_current_admin)):
    """Kick off a Stripe Checkout session on the hub. The frontend opens
    the returned URL in a new tab; the hub webhook flips this tenant to
    `active` and our poller picks it up within 5 minutes (or force-refresh)."""
    from billing_client import create_checkout
    if not req.success_url or not req.cancel_url:
        raise HTTPException(400, "success_url and cancel_url are required")
    return await create_checkout(req.success_url, req.cancel_url)


@api.post("/admin/billing/portal")
async def admin_billing_portal(req: _BillingUrlsReq, admin=Depends(_current_admin)):
    """Get a Stripe Customer Portal URL for the restaurant owner to update
    card, download invoices, or cancel. Requires an existing subscription."""
    from billing_client import create_portal
    if not req.return_url:
        raise HTTPException(400, "return_url is required")
    return await create_portal(req.return_url)


@api.get("/settings")
async def public_settings():
    s = await _get_settings()
    # Only expose non-sensitive fields
    return {
        "business_name": s.get("business_name"),
        "phone": s.get("phone"),
        "email": s.get("email"),
        "delivery_areas": s.get("delivery_areas", []),
        "operating_hours": s.get("operating_hours", ""),
        "ordering_days": s.get("ordering_days", [0, 1, 2, 3, 4]),
        "delivery_days": s.get("delivery_days", [5, 6]),
        "default_delivery_fee_cents": s.get("default_delivery_fee_cents", 599),
        "minimum_order_cents": s.get("minimum_order_cents", 0),
        "tax_enabled": s.get("tax_enabled", True),
        "tax_rate_bps": s.get("tax_rate_bps", 1300),
        "tax_label": s.get("tax_label", "HST"),
        "currency": s.get("currency", "CAD"),
        "home_hero_tagline": s.get("home_hero_tagline", "Order anytime this week — we deliver every weekend."),
        "home_hero_title": s.get("home_hero_title", "Your neighbourhood halal grocery — delivered."),
        "home_hero_subtitle": s.get("home_hero_subtitle", "Fresh meat, fish, sweets & everyday groceries, delivered to your door."),
        "delivery_ribbon_enabled": bool(s.get("delivery_ribbon_enabled", True)),
        "delivery_ribbon_text": s.get("delivery_ribbon_text", "Free delivery on orders over $150"),
        "home_best_sellers_enabled": bool(s.get("home_best_sellers_enabled", True)),
        "home_new_items_enabled": bool(s.get("home_new_items_enabled", True)),
        "grocery_coming_soon": bool(s.get("grocery_coming_soon", False)),
        "location_banner_enabled": bool(s.get("location_banner_enabled", False)),
        "price_gating_enabled": bool(s.get("price_gating_enabled", False)),
        "fish_service_enabled": bool(s.get("fish_service_enabled", True)),
        "fish_service_name": s.get("fish_service_name", "Fish Scaling & Cleaning"),
        "fish_service_desc": s.get("fish_service_desc", "We'll scale and clean your fish before delivery."),
        "fish_service_price_cents": int(s.get("fish_service_price_cents", 299) or 0),
        "loyalty_earn_points_per_dollar": float(s.get("loyalty_earn_points_per_dollar", 1.0)),
        "loyalty_redeem_points_per_dollar": int(s.get("loyalty_redeem_points_per_dollar", 25)),
        # Expose ONLY safe payment-method fields (never secret keys) so the customer app
        # can render the right method list, apply per-method tax, and show Interac email.
        "payment_methods": {
            k: {
                "enabled":       bool(v.get("enabled", False)),
                "tax_enabled":   bool(v.get("tax_enabled", True)),
                # Interac needs its e-Transfer email in the customer flow
                **({"email": v.get("email", "")} if k == "interac" else {}),
                **({"instructions": v.get("instructions", "")} if k == "interac" else {}),
                # Stripe/PayPal publishable client-side identifiers ARE safe to return
                **({"publishable_key": v.get("publishable_key", "")} if k == "stripe" else {}),
                **({"client_id": v.get("client_id", "")} if k == "paypal" else {}),
            }
            for k, v in (s.get("payment_methods") or {}).items()
        },
    }


# ==========================================================
# ADMIN — Master Menu, Settings, Invoice
# ==========================================================
@api.get("/admin/settings")
async def admin_get_settings(admin=Depends(_current_admin)):
    return await _get_settings()


@api.put("/admin/settings")
async def admin_put_settings(payload: BusinessSettings, admin=Depends(_current_admin)):
    doc = payload.model_dump()
    doc["key"] = "default"
    await db.business_settings.update_one({"key": "default"}, {"$set": doc}, upsert=True)
    return {"ok": True, "settings": doc}


@api.get("/admin/master-menu")
async def admin_master_list(
    q: Optional[str] = None,
    category: Optional[str] = None,
    cuisine: Optional[str] = None,
    active: Optional[str] = None,
    admin=Depends(_current_admin),
):
    query: dict = {}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    if category:
        query["category"] = category
    if cuisine:
        query["cuisine"] = cuisine
    if active in ("true", "false"):
        query["is_active"] = (active == "true")
    cur = db.master_menu.find(query, {"_id": 0}).sort([("display_order", 1), ("name", 1)]).limit(500)
    return await cur.to_list(500)


@api.get("/admin/master-menu/{item_id}")
async def admin_master_get(item_id: str, admin=Depends(_current_admin)):
    it = await db.master_menu.find_one({"item_id": item_id}, {"_id": 0})
    if not it:
        raise HTTPException(404, "Not found")
    return it


@api.post("/admin/master-menu")
async def admin_master_upsert(item: MasterMenuItem, admin=Depends(_current_admin)):
    item.updated_at = datetime.now(timezone.utc)
    await db.master_menu.update_one(
        {"item_id": item.item_id}, {"$set": item.model_dump()}, upsert=True
    )
    return {"ok": True, "item": item.model_dump()}


# ----------------------------------------------------------
# BULK AI-ENRICHED IMPORT (name + price CSV → AI fills the rest)
# ----------------------------------------------------------
from menu_ai import enrich_item as _ai_enrich_item

class BulkPreviewRow(BaseModel):
    name: str
    default_price_cents: int = 0

class BulkPreviewReq(BaseModel):
    rows: List[BulkPreviewRow]
    generate_images: bool = True

@api.post("/admin/master-menu/bulk-preview")
async def admin_master_bulk_preview(req: BulkPreviewReq, admin=Depends(_current_admin)):
    """Take a list of {name, price} rows, ask the LLM to fill in all remaining fields
    (description / category / cuisine / veg-type / spice / allergens) AND generate a food
    image per row. Runs enrichment in parallel for speed.
    Nothing is written to the DB yet — the admin must call /bulk-save after review.
    Image URLs are returned as RELATIVE paths (`/api/uploads/menu/xxx.png`) — the
    frontend prepends its BACKEND_URL so images work in both web preview & native builds.
    """
    import asyncio as _asyncio

    if not req.rows:
        raise HTTPException(400, "No rows provided")
    if len(req.rows) > 25:
        raise HTTPException(400, "Max 25 rows per bulk upload")

    # Filter blanks & keep original order for the response.
    clean = [(r.name.strip(), max(0, int(r.default_price_cents or 0))) for r in req.rows if r.name and r.name.strip()]
    if not clean:
        raise HTTPException(400, "All rows are blank")

    # Enrich in parallel, but cap concurrency so we don't slam the LLM.
    sem = _asyncio.Semaphore(5)
    async def _one(name: str, price: int) -> dict:
        async with sem:
            try:
                ai = await _ai_enrich_item(name, price, want_image=req.generate_images)
            except Exception as e:
                log.warning(f"bulk-preview enrich failed for {name!r}: {e}")
                # graceful fallback
                from menu_ai import _fallback_text
                ai = {**_fallback_text(name), "image_url": ""}
            return {
                "item_id": f"mi_{uuid.uuid4().hex[:10]}",
                "name": name,
                "default_price_cents": price,
                "cost_price_cents": 0,
                "short_description": ai["short_description"],
                "full_description":  ai["full_description"],
                "category":     ai["category"],
                "cuisine":      ai["cuisine"],
                "veg_type":     ai["veg_type"],
                "spice_level":  ai["spice_level"],
                "allergens":    ai["allergens"],
                "image_url":    ai["image_url"],   # RELATIVE — frontend prepends host
                "extra_images": [],
                "is_active":    True,
                "prep_notes":   "",
                "kitchen_notes":"",
                "display_order": 0,
            }

    previews = await _asyncio.gather(*[_one(n, p) for (n, p) in clean])
    return {"ok": True, "previews": previews}


class BulkSaveReq(BaseModel):
    items: List[MasterMenuItem]

@api.post("/admin/master-menu/bulk-save")
async def admin_master_bulk_save(req: BulkSaveReq, admin=Depends(_current_admin)):
    """Persist the reviewed items in one batch. Returns count saved."""
    if not req.items:
        raise HTTPException(400, "No items to save")
    saved = 0
    for it in req.items:
        it.updated_at = datetime.now(timezone.utc)
        await db.master_menu.update_one(
            {"item_id": it.item_id}, {"$set": it.model_dump()}, upsert=True
        )
        saved += 1
    return {"ok": True, "saved": saved}


@api.post("/admin/master-menu/{item_id}/duplicate")
async def admin_master_duplicate(item_id: str, admin=Depends(_current_admin)):
    src = await db.master_menu.find_one({"item_id": item_id}, {"_id": 0})
    if not src:
        raise HTTPException(404, "Not found")
    src["item_id"] = f"mi_{uuid.uuid4().hex[:10]}"
    src["name"] = f"{src['name']} (Copy)"
    src["created_at"] = datetime.now(timezone.utc)
    src["updated_at"] = src["created_at"]
    await db.master_menu.insert_one(src)
    return {"ok": True, "item_id": src["item_id"]}


@api.delete("/admin/master-menu/{item_id}")
async def admin_master_delete(item_id: str, admin=Depends(_current_admin)):
    r = await db.master_menu.delete_one({"item_id": item_id})
    return {"ok": True, "deleted": r.deleted_count}


class BulkActionReq(BaseModel):
    item_ids: List[str]
    action: str  # "activate" | "deactivate" | "delete"


@api.post("/admin/master-menu/bulk")
async def admin_master_bulk(req: BulkActionReq, admin=Depends(_current_admin)):
    if req.action == "activate":
        r = await db.master_menu.update_many({"item_id": {"$in": req.item_ids}}, {"$set": {"is_active": True}})
        return {"ok": True, "modified": r.modified_count}
    if req.action == "deactivate":
        r = await db.master_menu.update_many({"item_id": {"$in": req.item_ids}}, {"$set": {"is_active": False}})
        return {"ok": True, "modified": r.modified_count}
    if req.action == "delete":
        r = await db.master_menu.delete_many({"item_id": {"$in": req.item_ids}})
        return {"ok": True, "deleted": r.deleted_count}
    raise HTTPException(400, "Unknown action")


# Weekly Menu v2 — line-level control
class WeeklyLineUpsertReq(BaseModel):
    line: WeeklyMenuLine


@api.post("/admin/menus/{week_start}/lines")
async def admin_add_weekly_line(week_start: str, req: WeeklyLineUpsertReq,
                                admin=Depends(_current_admin)):
    menu = await db.weekly_menus.find_one({"week_start": week_start}, {"_id": 0})
    if not menu:
        raise HTTPException(404, "Weekly menu not found")
    lines = menu.get("lines", [])
    replaced = False
    for i, ln in enumerate(lines):
        if ln.get("line_id") == req.line.line_id:
            lines[i] = req.line.model_dump()
            replaced = True
            break
    if not replaced:
        lines.append(req.line.model_dump())
    await db.weekly_menus.update_one(
        {"week_start": week_start}, {"$set": {"lines": lines}}
    )
    return {"ok": True, "line": req.line.model_dump(), "replaced": replaced}


@api.delete("/admin/menus/{week_start}/lines/{line_id}")
async def admin_delete_weekly_line(week_start: str, line_id: str,
                                   admin=Depends(_current_admin)):
    r = await db.weekly_menus.update_one(
        {"week_start": week_start}, {"$pull": {"lines": {"line_id": line_id}}}
    )
    return {"ok": True, "modified": r.modified_count}


class WeeklyMenuSettingsReq(BaseModel):
    alacarte_enabled: Optional[bool] = None
    package_enabled: Optional[bool] = None
    package: Optional[WeeklyMenuPackage] = None


@api.post("/admin/menus/{week_start}/settings")
async def admin_update_weekly_settings(week_start: str, req: WeeklyMenuSettingsReq,
                                       admin=Depends(_current_admin)):
    """Update per-week toggles + package config (alacarte/package mode)."""
    menu = await db.weekly_menus.find_one({"week_start": week_start}, {"_id": 0})
    if not menu:
        raise HTTPException(404, "Weekly menu not found")
    patch: Dict[str, Any] = {}
    if req.alacarte_enabled is not None:
        patch["alacarte_enabled"] = req.alacarte_enabled
    if req.package_enabled is not None:
        patch["package_enabled"] = req.package_enabled
    if req.package is not None:
        patch["package"] = req.package.model_dump()
    if not patch:
        return {"ok": True, "unchanged": True}
    # Safety: don't allow both toggles off (customer would see nothing)
    final_alac = patch.get("alacarte_enabled", menu.get("alacarte_enabled", True))
    final_pkg = patch.get("package_enabled", menu.get("package_enabled", False))
    if not final_alac and not final_pkg:
        raise HTTPException(400, "At least one of à la carte or package must be enabled.")
    await db.weekly_menus.update_one({"week_start": week_start}, {"$set": patch})
    doc = await db.weekly_menus.find_one({"week_start": week_start}, {"_id": 0})
    return {"ok": True, "menu": doc}


class CreateWeekReq(BaseModel):
    week_start: str
    title: Optional[str] = None
    copy_all_master: bool = False


@api.post("/admin/menus/create")
async def admin_create_week(req: CreateWeekReq, admin=Depends(_current_admin)):
    """Create a new weekly menu. Optionally seed the à-la-carte section with ALL
    active Master Menu items (added hidden — the admin turns on the ones they
    want visible this week)."""
    existing = await db.weekly_menus.find_one({"week_start": req.week_start}, {"_id": 0})
    if existing:
        raise HTTPException(400, "A menu for that week already exists.")
    lines: List[dict] = []
    if req.copy_all_master:
        cur = db.master_menu.find({"is_active": {"$ne": False}}, {"_id": 0})
        items = [m async for m in cur]
        items.sort(key=lambda m: (m.get("name") or "").lower())
        for i, m in enumerate(items):
            lines.append(WeeklyMenuLine(
                master_item_id=m["item_id"],
                is_visible=False,          # hidden by default per spec
                display_order=i + 1,
            ).model_dump())
    menu = WeeklyMenu(
        week_start=req.week_start,
        title=(req.title or "").strip() or f"Week of {req.week_start}",
        lines=lines,
        published=True,
        status="published",
    )
    doc = menu.model_dump()
    await db.weekly_menus.update_one(
        {"week_start": req.week_start}, {"$set": doc}, upsert=True
    )
    return {"ok": True, "menu": doc}


class ComplimentaryReq(BaseModel):
    master_ids: List[str] = []


@api.post("/admin/menus/{week_start}/complimentary")
async def admin_set_complimentary(week_start: str, req: ComplimentaryReq,
                                  admin=Depends(_current_admin)):
    """Set the week's Complimentary This Week dishes (picked from Master Menu)."""
    menu = await db.weekly_menus.find_one({"week_start": week_start}, {"_id": 0})
    if not menu:
        raise HTTPException(404, "Weekly menu not found")
    await db.weekly_menus.update_one(
        {"week_start": week_start},
        {"$set": {"complimentary_master_ids": req.master_ids}},
    )
    doc = await db.weekly_menus.find_one({"week_start": week_start}, {"_id": 0})
    return {"ok": True, "menu": doc}


class LineVisibilityReq(BaseModel):
    is_visible: bool


@api.post("/admin/menus/{week_start}/lines/{line_id}/visibility")
async def admin_set_line_visibility(week_start: str, line_id: str,
                                    req: LineVisibilityReq,
                                    admin=Depends(_current_admin)):
    """Toggle whether a single à-la-carte dish is visible to customers this week."""
    r = await db.weekly_menus.update_one(
        {"week_start": week_start, "lines.line_id": line_id},
        {"$set": {"lines.$.is_visible": req.is_visible}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Line not found")
    return {"ok": True, "is_visible": req.is_visible}


class AlwaysAvailableReq(BaseModel):
    master_ids: List[str] = []


@api.get("/admin/always-available")
async def admin_get_always_available(admin=Depends(_current_admin)):
    """Return the global Always Available master-id list."""
    settings = await _get_settings()
    return {"master_ids": settings.get("always_available_master_ids") or []}


@api.post("/admin/always-available")
async def admin_set_always_available(req: AlwaysAvailableReq,
                                     admin=Depends(_current_admin)):
    """Replace the global Always Available master-id list. Reflects on the
    customer app immediately (customer screens poll /menu/anytime)."""
    await db.business_settings.update_one(
        {"key": "default"},
        {"$set": {"always_available_master_ids": req.master_ids}},
        upsert=True,
    )
    return {"ok": True, "master_ids": req.master_ids}


# Refund
@api.post("/admin/orders/{order_id}/refund")
async def admin_refund_order(order_id: str, admin=Depends(_current_admin)):
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    await db.orders.update_one(
        {"order_id": order_id},
        {"$set": {"refund_status": "refunded", "status": "cancelled",
                  "updated_at": datetime.now(timezone.utc)}},
    )
    # Claw back loyalty: remove points earned on this order, and return redeemed points.
    if order.get("refund_status") != "refunded":
        awarded = int(order.get("points_awarded", 0) or 0)
        redeemed = int(order.get("points_redeemed", 0) or 0)
        net = redeemed - awarded
        if net != 0:
            await db.users.update_one({"user_id": order["user_id"]}, {"$inc": {"loyalty_points": net}})
        if awarded or redeemed:
            await db.points_ledger.insert_one({
                "user_id": order["user_id"], "order_id": order_id, "delta": net,
                "type": "refund", "ts": datetime.now(timezone.utc),
                "note": f"Refund of order {order_id[-6:].upper()}"})
        # Release coupon usage so the customer can use it again.
        if order.get("coupon_code"):
            await db.coupon_redemptions.delete_many({"order_id": order_id})
            await db.coupons.update_one({"code": order["coupon_code"], "used_count": {"$gt": 0}},
                                        {"$inc": {"used_count": -1}})
    return {"ok": True}


# ==========================================================
# ADMIN — Coupon management (FR-04)
# ==========================================================
class CouponUpsertReq(BaseModel):
    code: str
    discount_type: str = "percent"
    value: int
    active: bool = True
    min_order_cents: int = 0
    description: str = ""
    expiry: Optional[str] = None
    usage_limit: int = 0
    per_customer_limit: int = 0
    first_time_only: bool = False


@api.get("/admin/coupons")
async def admin_list_coupons(admin=Depends(_current_admin)):
    cur = db.coupons.find({}, {"_id": 0}).sort("created_at", -1)
    return {"coupons": [c async for c in cur]}


@api.post("/admin/coupons")
async def admin_upsert_coupon(req: CouponUpsertReq, admin=Depends(_current_admin)):
    code = req.code.strip().upper()
    if not code:
        raise HTTPException(400, "Coupon code is required.")
    if req.discount_type == "percent" and not (0 < req.value <= 100):
        raise HTTPException(400, "Percentage must be between 1 and 100.")
    existing = await db.coupons.find_one({"code": code}, {"_id": 0})
    doc = req.model_dump()
    doc["code"] = code
    if existing:
        doc["used_count"] = existing.get("used_count", 0)
        doc["owner_user_id"] = existing.get("owner_user_id")
        doc["created_at"] = existing.get("created_at", datetime.now(timezone.utc))
        await db.coupons.update_one({"code": code}, {"$set": doc})
    else:
        doc["used_count"] = 0
        doc["owner_user_id"] = None
        doc["created_at"] = datetime.now(timezone.utc)
        await db.coupons.insert_one(doc)
    return {"ok": True, "coupon": {k: v for k, v in doc.items() if k != "_id"}}


@api.delete("/admin/coupons/{code}")
async def admin_delete_coupon(code: str, admin=Depends(_current_admin)):
    await db.coupons.delete_one({"code": code.strip().upper()})
    return {"ok": True}


# ==========================================================
# CUSTOMER — My coupons + points history (FR-01/02/03/04)
# ==========================================================
@api.get("/me/coupons")
async def my_coupons(user: User = Depends(_current_user)):
    """Personal (first-time) coupons owned by this customer + public active coupons."""
    today = datetime.now(timezone.utc).date()
    out = []
    seen = set()

    async def _add(c):
        code = c["code"]
        if code in seen:
            return
        exp = c.get("expiry")
        expired = False
        if exp:
            try:
                expired = datetime.strptime(exp, "%Y-%m-%d").date() < today
            except Exception:
                expired = False
        used_by_me = await db.coupon_redemptions.count_documents({"code": code, "user_id": user.user_id})
        pcl = c.get("per_customer_limit", 0)
        used_up = bool(pcl and used_by_me >= pcl) or bool(c.get("usage_limit", 0) and c.get("used_count", 0) >= c["usage_limit"])
        out.append({
            "code": code, "discount_type": c.get("discount_type", "percent"), "value": c.get("value"),
            "description": c.get("description", ""), "min_order_cents": c.get("min_order_cents", 0),
            "expiry": exp, "expired": expired, "used": used_up, "personal": bool(c.get("owner_user_id")),
        })
        seen.add(code)

    async for c in db.coupons.find({"owner_user_id": user.user_id, "active": True}, {"_id": 0}):
        await _add(c)
    async for c in db.coupons.find({"owner_user_id": None, "active": True, "first_time_only": False}, {"_id": 0}):
        await _add(c)
    return {"coupons": out}


@api.get("/me/points-history")
async def my_points_history(user: User = Depends(_current_user)):
    cur = db.points_ledger.find({"user_id": user.user_id}, {"_id": 0}).sort("ts", -1).limit(100)
    entries = [e async for e in cur]
    return {"balance": user.loyalty_points, "entries": entries}


# ==========================================================
# ADMIN — Integrations (Google Drive + Twilio SMS)
# ==========================================================
# Credentials are stored encrypted in business_settings.integrations.
# Only the encryption key lives in .env (INTEGRATIONS_FERNET_KEY).
# ==========================================================
from settings_crypto import (
    encrypt_service_account_json, encrypt_str, is_configured as crypto_configured,
)
from exports import build_orders_xlsx, build_customers_xlsx, default_filename, expand_order_items
import drive_client as _drive
import twilio_client as _twilio
import email_client as _email


# ==========================================================
# Temporary XLSX host — used by "email" and "sms" export
# destinations. Files live in MongoDB for 48 hours, then are
# auto-cleaned by a TTL index.
# ==========================================================
import secrets as _secrets
import base64 as _b64

async def _stash_xlsx(data: bytes, filename: str) -> str:
    """Store XLSX bytes with a random token; returns the token.
    Also opportunistically evicts already-expired rows to keep the collection lean
    (we removed the destructive TTL index — see startup notes)."""
    try:
        await db.export_files.delete_many({
            "expires_at": {"$lt": datetime.now(timezone.utc)}
        })
    except Exception as _cleanup_err:
        log.warning(f"export_files lazy-cleanup skipped: {_cleanup_err}")
    token = _secrets.token_urlsafe(24)
    await db.export_files.insert_one({
        "token": token,
        "filename": filename,
        "content_b64": _b64.b64encode(data).decode(),
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=48),
    })
    return token


def _download_url(token: str) -> str:
    """Build the full public download URL from the current request context.
    Falls back to a relative path if not available.
    """
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}/api/exports/{token}"
    # In production the K8s ingress serves this at same origin; caller can
    # append their frontend host. Return a full-ish URL that Twilio/Resend
    # will accept via `PUBLIC_BASE_URL` env or the request.base_url in the
    # handler below.
    return f"/api/exports/{token}"


@app.get("/api/exports/{token}")
async def get_export_file(token: str):
    """Public download endpoint. Time-limited via `expires_at`.
    The token is 32 URL-safe bytes → 256 bits of entropy, unguessable."""
    doc = await db.export_files.find_one({"token": token})
    if not doc:
        raise HTTPException(404, "Download link expired or invalid")
    expires = doc.get("expires_at")
    if expires:
        # MongoDB may return naive datetime — coerce to UTC before comparing.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            # Best-effort cleanup (TTL index also runs)
            await db.export_files.delete_one({"token": token})
            raise HTTPException(410, "Download link expired")
    import base64
    data = base64.b64decode(doc["content_b64"])
    from fastapi.responses import Response
    return Response(
        content=data,
        media_type=doc.get("content_type",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={
            "Content-Disposition": f'attachment; filename="{doc["filename"]}"',
            "Cache-Control": "no-store, private",
        },
    )


class DriveSettingsIn(BaseModel):
    service_account_json: Optional[str] = None  # full JSON blob; None = leave unchanged
    folder_id: str
    user_email: EmailStr


class TwilioSettingsIn(BaseModel):
    account_sid: str
    auth_token: Optional[str] = None  # None = leave unchanged
    from_number: str


class TestSmsIn(BaseModel):
    to_number: str


class TestDriveIn(BaseModel):
    # No fields needed; uses stored config
    pass


async def _get_integrations() -> dict:
    doc = await db.business_settings.find_one({"key": "default"}, {"_id": 0}) or {}
    return (doc.get("integrations") or {})


@api.get("/admin/integrations")
async def admin_get_integrations(admin=Depends(_current_admin)):
    """Return integration settings WITH secrets masked (never return ciphertext)."""
    ints = await _get_integrations()
    drive = ints.get("google_drive") or {}
    twilio = ints.get("twilio") or {}
    email_cfg = ints.get("email") or {}
    return {
        "crypto_ready": crypto_configured(),
        "email": {
            "configured": _email.is_configured(),  # Resend key present
            "recipient": email_cfg.get("recipient", ""),  # where exports get emailed to
            "last_test_ok": email_cfg.get("last_test_ok"),
            "last_test_at": email_cfg.get("last_test_at"),
        },
        "google_drive": {
            "configured": bool(drive.get("service_account_json_encrypted")),
            "folder_id": drive.get("folder_id", ""),
            "user_email": drive.get("user_email", ""),
            "client_email": drive.get("client_email", ""),  # service-account email (non-secret)
            "last_test_ok": drive.get("last_test_ok"),
            "last_test_at": drive.get("last_test_at"),
        },
        "twilio": {
            "configured": bool(twilio.get("auth_token_encrypted")),
            "account_sid": twilio.get("account_sid", ""),
            "from_number": twilio.get("from_number", ""),
            "last_test_ok": twilio.get("last_test_ok"),
            "last_test_at": twilio.get("last_test_at"),
        },
    }


class EmailSettingsIn(BaseModel):
    recipient: EmailStr


class TestEmailIn(BaseModel):
    to: Optional[EmailStr] = None  # override recipient for testing


@api.put("/admin/integrations/email")
async def admin_save_email_settings(payload: EmailSettingsIn,
                                     admin=Depends(_current_admin)):
    await db.business_settings.update_one(
        {"key": "default"},
        {"$set": {"integrations.email.recipient": str(payload.recipient)}},
        upsert=True,
    )
    return {"ok": True}


@api.post("/admin/integrations/email/test")
async def admin_test_email(payload: TestEmailIn, admin=Depends(_current_admin)):
    ints = await _get_integrations()
    to = (payload.to and str(payload.to)) or (ints.get("email") or {}).get("recipient")
    if not to:
        raise HTTPException(400, "Add a recipient email in Settings first")
    subject = f"{_email.EMAIL_FROM_NAME} — email integration test"
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;'
        'font-family:Arial,sans-serif;color:#2A1D18">'
        f'<h2 style="margin:0 0 12px;color:#B14F36">{_email.EMAIL_FROM_NAME}</h2>'
        f'<p>This is a test email from your {BRAND_NAME} Admin Portal.</p>'
        '<p>If you received this, your email integration is working — every '
        'export you trigger with the &quot;Email me&quot; button will land in this inbox.</p>'
        '<p style="font-size:12px;color:#888;margin-top:24px">Sent by '
        f'{_email.EMAIL_FROM_NAME} · Admin Exports. We never ask for your password '
        'or card details by email.</p>'
        '</td></tr></table>'
    )
    try:
        msg_id = await _email.send_email(to=to, subject=subject, html=html)
    except _email.EmailError as e:
        await db.business_settings.update_one(
            {"key": "default"},
            {"$set": {"integrations.email.last_test_ok": False,
                      "integrations.email.last_test_at": datetime.now(timezone.utc).isoformat(),
                      "integrations.email.last_test_error": e.message}},
        )
        raise HTTPException(e.status, e.message)
    await db.business_settings.update_one(
        {"key": "default"},
        {"$set": {"integrations.email.last_test_ok": True,
                  "integrations.email.last_test_at": datetime.now(timezone.utc).isoformat(),
                  "integrations.email.last_test_error": ""}},
    )
    return {"ok": True, "message_id": msg_id, "to": to}


@api.put("/admin/integrations/google-drive")
async def admin_save_drive_settings(payload: DriveSettingsIn,
                                     admin=Depends(_current_admin)):
    if not crypto_configured():
        raise HTTPException(500, "INTEGRATIONS_FERNET_KEY not configured on backend")
    upd: dict = {
        "integrations.google_drive.folder_id": payload.folder_id.strip(),
        "integrations.google_drive.user_email": str(payload.user_email),
    }
    if payload.service_account_json and payload.service_account_json.strip():
        try:
            enc = encrypt_service_account_json(payload.service_account_json)
            # Extract non-secret client_email for display in UI
            import json as _json
            client_email = _json.loads(payload.service_account_json).get("client_email", "")
        except Exception as e:
            raise HTTPException(400, f"Invalid service-account JSON: {e}")
        upd["integrations.google_drive.service_account_json_encrypted"] = enc
        upd["integrations.google_drive.client_email"] = client_email
    await db.business_settings.update_one(
        {"key": "default"}, {"$set": upd}, upsert=True,
    )
    return {"ok": True}


@api.post("/admin/integrations/google-drive/test")
async def admin_test_drive(admin=Depends(_current_admin)):
    ints = await _get_integrations()
    gd = ints.get("google_drive") or {}
    if not gd.get("service_account_json_encrypted") or not gd.get("folder_id"):
        raise HTTPException(400, "Google Drive settings incomplete — paste JSON + folder ID first")
    try:
        folder = await _drive.test_folder(
            gd["service_account_json_encrypted"], gd["folder_id"],
        )
    except _drive.DriveError as e:
        # Store last test failure so UI can surface it
        await db.business_settings.update_one(
            {"key": "default"},
            {"$set": {"integrations.google_drive.last_test_ok": False,
                      "integrations.google_drive.last_test_at": datetime.now(timezone.utc).isoformat(),
                      "integrations.google_drive.last_test_error": e.message}},
        )
        raise HTTPException(e.status, e.message)
    if folder.get("mimeType") != "application/vnd.google-apps.folder":
        raise HTTPException(400, "Configured ID is not a Drive folder")
    await db.business_settings.update_one(
        {"key": "default"},
        {"$set": {"integrations.google_drive.last_test_ok": True,
                  "integrations.google_drive.last_test_at": datetime.now(timezone.utc).isoformat(),
                  "integrations.google_drive.last_test_error": ""}},
    )
    return {"ok": True, "folder": {"id": folder["id"], "name": folder["name"]}}


@api.put("/admin/integrations/twilio")
async def admin_save_twilio_settings(payload: TwilioSettingsIn,
                                      admin=Depends(_current_admin)):
    if not crypto_configured():
        raise HTTPException(500, "INTEGRATIONS_FERNET_KEY not configured on backend")
    upd: dict = {
        "integrations.twilio.account_sid": payload.account_sid.strip(),
        "integrations.twilio.from_number": payload.from_number.strip(),
    }
    if payload.auth_token and payload.auth_token.strip():
        upd["integrations.twilio.auth_token_encrypted"] = encrypt_str(payload.auth_token.strip())
    await db.business_settings.update_one(
        {"key": "default"}, {"$set": upd}, upsert=True,
    )
    return {"ok": True}


@api.post("/admin/integrations/twilio/test")
async def admin_test_twilio(payload: TestSmsIn, admin=Depends(_current_admin)):
    ints = await _get_integrations()
    tw = ints.get("twilio") or {}
    if not tw.get("auth_token_encrypted") or not tw.get("account_sid") or not tw.get("from_number"):
        raise HTTPException(400, "Twilio settings incomplete — enter SID, token & from number first")
    try:
        res = await _twilio.send_test_sms(
            tw["account_sid"], tw["auth_token_encrypted"],
            tw["from_number"], payload.to_number,
        )
    except _twilio.TwilioError as e:
        await db.business_settings.update_one(
            {"key": "default"},
            {"$set": {"integrations.twilio.last_test_ok": False,
                      "integrations.twilio.last_test_at": datetime.now(timezone.utc).isoformat(),
                      "integrations.twilio.last_test_error": e.message}},
        )
        raise HTTPException(e.status, e.message)
    await db.business_settings.update_one(
        {"key": "default"},
        {"$set": {"integrations.twilio.last_test_ok": True,
                  "integrations.twilio.last_test_at": datetime.now(timezone.utc).isoformat(),
                  "integrations.twilio.last_test_error": ""}},
    )
    return {"ok": True, "message_sid": res["sid"], "status": res["status"]}


# ==========================================================
# ADMIN — Orders export (download / drive / sms)
# ==========================================================
class OrdersExportReq(BaseModel):
    order_ids: List[str] = Field(default_factory=list)  # empty = ALL current filter
    destination: str  # "download" | "email" | "sms" | "drive"
    sms_to: Optional[str] = None  # required if destination == "sms"
    sms_message: Optional[str] = None  # optional custom SMS body
    email_to: Optional[EmailStr] = None  # override recipient; else use configured


async def _resolve_orders(order_ids: List[str]) -> List[dict]:
    q: dict = {}
    if order_ids:
        q["order_id"] = {"$in": order_ids}
    cur = db.orders.find(q, {"_id": 0}).sort("created_at", -1).limit(2000)
    orders = await cur.to_list(2000)
    # Attach user summary like admin_list_orders does
    user_ids = list({o["user_id"] for o in orders if o.get("user_id")})
    users: dict = {}
    if user_ids:
        async for u in db.users.find({"user_id": {"$in": user_ids}},
                                     {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1}):
            users[u["user_id"]] = u
    for o in orders:
        u = users.get(o.get("user_id")) or {}
        addr_name = ((o.get("address") or {}).get("name") or "").strip()
        o["customer_name"] = addr_name or u.get("name") or "Guest"
        o["user_summary"] = u
    return orders


def _abs_export_url(request: Request, token: str) -> str:
    """Build an absolute /api/exports/{token} URL using the incoming request host.
    Always returns an https URL — the email guardrail rejects http links, and in
    production K8s always terminates TLS at the ingress anyway.
    """
    env = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if env:
        return f"{env}/api/exports/{token}"
    # Take request.base_url and force scheme to https.
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(str(request.base_url))
    # If we're on localhost dev, prefer the preview tunnel host if set.
    host = parts.hostname or ""
    if host in ("localhost", "127.0.0.1"):
        preview = os.environ.get("EXPO_PACKAGER_HOSTNAME", "").rstrip("/")
        if preview:
            return f"{preview.replace('http://', 'https://')}/api/exports/{token}"
    forced = urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
    return forced.rstrip("/") + f"/api/exports/{token}"


async def _finalize_export(
    request: Request,
    kind_label: str,  # "orders" | "customers"
    payload_destination: str,
    payload_sms_to: Optional[str],
    payload_sms_message: Optional[str],
    payload_email_to: Optional[str],
    xlsx: bytes,
    filename: str,
    count: int,
    sms_default_body: Optional[str] = None,  # detailed body built by caller
) -> dict:
    """Shared final step for both export endpoints. Handles download/email/sms/drive."""
    import base64
    if payload_destination == "download":
        return {
            "kind": "download", "filename": filename,
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "b64": base64.b64encode(xlsx).decode(),
            "count": count,
        }

    ints = await _get_integrations()

    if payload_destination == "email":
        recipient = (payload_email_to and str(payload_email_to)) or \
                    (ints.get("email") or {}).get("recipient")
        if not recipient:
            raise HTTPException(400, "No recipient email — set one in Settings or pass email_to")
        if not _email.is_configured():
            raise HTTPException(500, "Email integration is not configured on the backend")
        token = await _stash_xlsx(xlsx, filename)
        link = _abs_export_url(request, token)
        subject = f"{_email.EMAIL_FROM_NAME} — {kind_label.capitalize()} export ({count})"
        html = (
            '<table role="presentation" width="100%"><tr><td style="padding:24px;'
            'font-family:Arial,sans-serif;color:#2A1D18;max-width:560px">'
            f'<h2 style="margin:0 0 12px;color:#B14F36">{_email.EMAIL_FROM_NAME}</h2>'
            f'<p>Your <strong>{kind_label}</strong> export is ready — {count} '
            f'{"row" if count == 1 else "rows"}.</p>'
            f'<p style="margin:20px 0"><a href="{link}" style="background:#B14F36;'
            'color:#fff;padding:12px 20px;border-radius:24px;text-decoration:none;'
            'font-weight:800;display:inline-block">Download report</a></p>'
            f'<p style="font-size:12px;color:#666">File name: {filename}<br>'
            'Link expires in 48 hours.</p>'
            '<p style="font-size:11px;color:#aaa;margin-top:24px;border-top:1px solid #eee;padding-top:12px">'
            f'Sent by {_email.EMAIL_FROM_NAME} · Admin Exports. We never ask for '
            'your password or card details by email.</p>'
            '</td></tr></table>'
        )
        try:
            msg_id = await _email.send_email(to=recipient, subject=subject, html=html)
        except _email.EmailError as e:
            raise HTTPException(e.status, e.message)
        return {"kind": "email", "filename": filename, "recipient": recipient,
                "download_link": link, "message_id": msg_id, "count": count}

    if payload_destination == "sms":
        if not payload_sms_to or not payload_sms_to.strip():
            raise HTTPException(400, "sms_to (phone number) is required")
        tw = ints.get("twilio") or {}
        if not tw.get("auth_token_encrypted") or not tw.get("account_sid") or not tw.get("from_number"):
            raise HTTPException(400, "Twilio is not configured — set it up in Settings first")
        token = await _stash_xlsx(xlsx, filename)
        link = _abs_export_url(request, token)
        if payload_sms_message:
            body = payload_sms_message
        elif sms_default_body:
            body = sms_default_body.replace("{link}", link)
        else:
            body = (f"{_email.EMAIL_FROM_NAME}: {kind_label} export ({count}). "
                    f"Download (48h): {link}")
        try:
            sms = await _twilio.send_sms(
                tw["account_sid"], tw["auth_token_encrypted"],
                tw["from_number"], payload_sms_to.strip(), body,
            )
        except _twilio.TwilioError as e:
            raise HTTPException(e.status, e.message)
        return {"kind": "sms", "filename": filename, "download_link": link,
                "sms_status": sms["status"], "count": count}

    if payload_destination == "drive":
        gd = ints.get("google_drive") or {}
        if not gd.get("service_account_json_encrypted") or not gd.get("folder_id"):
            raise HTTPException(400, "Google Drive is not configured — set it up in Settings first")
        try:
            result = await _drive.upload_xlsx(
                gd["service_account_json_encrypted"], gd["folder_id"],
                gd.get("user_email"), filename, xlsx,
            )
        except _drive.DriveError as e:
            raise HTTPException(e.status, e.message)
        return {"kind": "drive", "filename": filename, "web_view_link": result["web_view_link"],
                "count": count}

    raise HTTPException(400, "destination must be download|email|sms|drive")


def _build_orders_sms_body(orders: list[dict]) -> str:
    """Build a delivery-driver-friendly SMS body listing each order's customer,
    address and itemized dishes. Uses `{link}` placeholder so the actual URL
    is substituted after the file is stashed. Safety-capped at ~1400 chars so
    Twilio doesn't fragment into 15+ segments.
    """
    def _addr(a: dict) -> str:
        parts = [a.get("line1", "")]
        if a.get("line2"): parts.append(a["line2"])
        parts.append(a.get("city", ""))
        if a.get("postal_code"): parts.append(a["postal_code"])
        return ", ".join([p for p in parts if p])

    lines: list[str] = ["{link}", ""]
    over = 0
    for i, o in enumerate(orders):
        us = o.get("user_summary") or {}
        addr = o.get("address") or {}
        name = ((addr.get("name") or "").strip()
                or us.get("name") or o.get("customer_name") or "Guest")
        phone = us.get("phone") or o.get("phone") or ""
        block: list[str] = []
        block.append(name)
        if phone:
            block.append(f"📞 {phone}")
        block.append(_addr(addr))
        block.append("Orders:")
        items = expand_order_items(o)
        if items:
            for nm, q in items:
                block.append(f"  • {nm} x {q}")
        else:
            block.append("  (no items)")
        candidate = "\n".join(block)
        # Length safety: if we'd blow past 1400 chars, stop and mention omitted count
        projected = sum(len(s) + 1 for s in lines) + len(candidate) + 40
        if projected > 1400 and i > 0:
            over = len(orders) - i
            break
        lines.append(candidate)
        if i < len(orders) - 1:
            lines.append("-" * 25)
    if over > 0:
        lines.append(f"\n… +{over} more in the XLS")
    return "\n".join(lines)


@api.post("/admin/orders/export")
async def admin_export_orders(payload: OrdersExportReq, request: Request,
                              admin=Depends(_current_admin)):
    if payload.destination not in ("download", "email", "sms", "drive"):
        raise HTTPException(400, "destination must be download|email|sms|drive")
    orders = await _resolve_orders(payload.order_ids)
    if not orders:
        raise HTTPException(400, "No orders match the selection")
    xlsx = build_orders_xlsx(orders)
    filename = default_filename("orders")
    sms_default = _build_orders_sms_body(orders) if payload.destination == "sms" else None
    return await _finalize_export(
        request, "orders", payload.destination,
        payload.sms_to, payload.sms_message, payload.email_to,
        xlsx, filename, len(orders),
        sms_default_body=sms_default,
    )


# ==========================================================
# ADMIN — Manual order creation (Admin creates an order on behalf of a customer)
# ==========================================================
class AdminCustomerIn(BaseModel):
    name: str
    phone: str
    email: Optional[EmailStr] = None
    address: Optional[Address] = None


class AdminCreateOrderReq(BaseModel):
    # Customer selection: EITHER pass user_id (existing customer) OR new_customer (create inline)
    user_id: Optional[str] = None
    new_customer: Optional[AdminCustomerIn] = None
    # Order details (same shape as customer flow, but no coupon/redeem/stripe)
    items: List[OrderItemIn]
    address: Address
    slot: DeliverySlot
    phone: str
    special_instructions: Optional[str] = ""
    payment_method: str = "cod"  # "cod" | "interac" | "card" — admin-created always non-Stripe
    mark_as_paid: bool = False  # if True, order marked paid immediately
    driver_partner_id: Optional[str] = None  # optional driver assignment


@api.post("/admin/customers")
async def admin_create_customer(payload: AdminCustomerIn, admin=Depends(_current_admin)):
    """Create a new customer inline (from Admin New Order flow)."""
    if not payload.name.strip() or not payload.phone.strip():
        raise HTTPException(400, "Name and phone are required")

    # De-dupe: if a user already exists with this phone, return that instead.
    existing = None
    if payload.email:
        existing = await db.users.find_one({"email": str(payload.email).lower()}, {"_id": 0})
    if not existing:
        existing = await db.users.find_one({"phone": payload.phone.strip()}, {"_id": 0})
    if existing:
        return {"user_id": existing["user_id"], "existed": True, "user": existing}

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "name": payload.name.strip(),
        "phone": payload.phone.strip(),
        "role": "customer",
        "loyalty_points": 0,
        "created_at": datetime.now(timezone.utc),
        "default_address": payload.address.model_dump() if payload.address else None,
    }
    if payload.email:
        doc["email"] = str(payload.email).lower()
    await db.users.insert_one(doc)
    doc.pop("_id", None)
    return {"user_id": user_id, "existed": False, "user": doc}


@api.get("/admin/order-builder")
async def admin_order_builder(admin=Depends(_current_admin)):
    """One-shot helper: returns everything the admin needs to build a new order.
    Cuts down on the client's parallel-fetch dance."""
    from datetime import date as _date
    settings = await _get_settings()
    today = _date.today()

    # Current + next 3 weekly menus (published or draft) so admin has options
    weeks = await db.weekly_menus.find({}, {"_id": 0}).sort("week_start", -1).limit(6).to_list(6)

    # Master menu items keyed by item_id for enrichment
    master = {m["item_id"]: m async for m in db.master_menu.find({"is_active": {"$ne": False}}, {"_id": 0})}

    # Normalize each week: build a unified `items[]` list from BOTH the legacy embedded
    # `items[]` shape AND the newer `lines[]` (v2) shape so the Admin New Order modal
    # can render à la carte + combo picks regardless of which schema the menu uses.
    today_iso = today.isoformat()
    current_week_start: Optional[str] = None
    for wk in weeks:
        merged: list[dict] = []
        # legacy embedded items
        for it in (wk.get("items") or []):
            m = master.get(it.get("item_id"))
            if m:
                it.setdefault("name", m.get("name", ""))
                it.setdefault("image_url", m.get("image_url", ""))
                it.setdefault("veg_type", m.get("veg_type"))
                it.setdefault("price_cents", it.get("price_cents") or m.get("default_price_cents"))
            merged.append(it)
        # v2 lines[] → each line references a master_menu doc
        for ln in (wk.get("lines") or []):
            mid = ln.get("master_item_id")
            m = master.get(mid)
            if not m:
                continue
            merged.append({
                "item_id": mid,
                "master_item_id": mid,
                "name": m.get("name", ""),
                "image_url": m.get("image_url", ""),
                "veg_type": m.get("veg_type"),
                "price_cents": ln.get("price_override_cents") or m.get("default_price_cents"),
                "default_price_cents": m.get("default_price_cents"),
                "availability": ln.get("availability", "available"),
                "is_featured": ln.get("is_featured", False),
                "display_order": ln.get("display_order", 0),
            })
        # De-dupe by item_id preserving first (legacy wins if both present).
        seen_ids: set = set()
        deduped: list[dict] = []
        for it in merged:
            iid = it.get("item_id")
            if iid and iid in seen_ids:
                continue
            if iid:
                seen_ids.add(iid)
            deduped.append(it)
        wk["items"] = deduped
        # Backfill package.eligible_master_ids from lines[] when not explicitly set
        if wk.get("package_enabled") and wk.get("package"):
            pkg = wk["package"]
            if not pkg.get("eligible_master_ids"):
                pkg["eligible_master_ids"] = [
                    ln.get("master_item_id") for ln in (wk.get("lines") or [])
                    if ln.get("master_item_id")
                ]
        # Determine which week is "current" (today falls within week_start..+6)
        ws = wk.get("week_start")
        if ws and ws <= today_iso:
            wk_end = (datetime.fromisoformat(ws).date() + timedelta(days=6)).isoformat()
            if today_iso <= wk_end and current_week_start is None:
                current_week_start = ws

    # Active catering packages
    catering = await db.catering_packages.find({"is_active": True}, {"_id": 0}).sort("sort_order", 1).to_list(20)

    # Active delivery partners for the driver dropdown
    partners = await db.delivery_partners.find({"is_active": True},
        {"_id": 0, "partner_id": 1, "name": 1, "phone": 1, "vehicle": 1}).sort("name", 1).to_list(50)

    # Compute delivery slots — next 4 weeks. Configured delivery_cycles win
    # over legacy delivery_days; occurrences whose cutoff already passed are
    # excluded so customers can only pick a bookable slot.
    from zoneinfo import ZoneInfo as _ZoneInfo
    cycles = settings.get("delivery_cycles") or []
    slots: list[dict] = []
    if cycles:
        now_toronto = datetime.now(timezone.utc).astimezone(_ZoneInfo("America/Toronto"))
        for wk_offset in range(4):
            for cycle in cycles:
                dow = int(cycle.get("delivery_day", 0))
                if not 0 <= dow <= 6:
                    continue
                py_dow = (dow - 1) % 7  # 0=Sun → 6, 1=Mon → 0 …
                days_ahead = (py_dow - today.weekday()) % 7 + wk_offset * 7
                d = today + timedelta(days=days_ahead)
                cutoff_day = int(cycle.get("cutoff_day", 0))
                cutoff_hour = int(cycle.get("cutoff_hour", 12))
                days_back = (dow - cutoff_day) % 7
                cutoff_date = d - timedelta(days=days_back)
                cutoff = datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day,
                                  cutoff_hour, tzinfo=_ZoneInfo("America/Toronto"))
                if now_toronto > cutoff:
                    continue
                slots.append({
                    "date": d.isoformat(),
                    "window": f"{['sunday','monday','tuesday','wednesday','thursday','friday','saturday'][dow]}_delivery",
                    "label": d.strftime("%a, %b %d, %Y"),
                    "cycle": cycle.get("label") or "",
                })
    else:
        delivery_days = settings.get("delivery_days", [5, 6])
        for wk_offset in range(4):
            for dow in sorted(set(int(d) for d in delivery_days if 0 <= int(d) <= 6)):
                # dow is 0=Sun..6=Sat (JS convention)
                # Python weekday(): 0=Mon..6=Sun. Convert.
                py_dow = (dow - 1) % 7  # 0=Sun → 6, 1=Mon → 0 …
                days_ahead = (py_dow - today.weekday()) % 7 + wk_offset * 7
                if days_ahead == 0 and wk_offset == 0:
                    # today: only allow if there's still time (skip past dates)
                    pass
                d = today + timedelta(days=days_ahead)
                slots.append({
                    "date": d.isoformat(),
                    "window": f"{['sunday','monday','tuesday','wednesday','thursday','friday','saturday'][dow]}_delivery",
                    "label": d.strftime("%a, %b %d, %Y"),
                })
    # De-dupe (same date might sneak in with different offsets) + sort
    seen: set = set()
    unique_slots = []
    for s in sorted(slots, key=lambda x: x["date"]):
        if s["date"] < today.isoformat():
            continue
        if s["date"] in seen:
            continue
        seen.add(s["date"])
        unique_slots.append(s)

    return {
        "weeks": weeks,
        "current_week_start": current_week_start,
        "master_menu": list(master.values()),
        "catering": catering,
        "delivery_partners": partners,
        "delivery_slots": unique_slots,
        "settings": {
            "delivery_fee_cents": settings.get("default_delivery_fee_cents", DELIVERY_FEE_CENTS),
            "tax_rate_bps": settings.get("tax_rate_bps", 1300),
            "tax_label": settings.get("tax_label", "HST"),
            "tax_enabled": settings.get("tax_enabled", True),
            "currency": settings.get("currency", "CAD"),
            "payment_methods": settings.get("payment_methods", {}),
        },
    }


@api.post("/admin/orders/create")
async def admin_create_manual_order(req: AdminCreateOrderReq, admin=Depends(_current_admin)):
    """Admin creates an order on behalf of a customer. Optionally assigns a driver.

    Flow:
      1. Resolve or create the customer
      2. Compute totals (uses same _resolve_items + settings as customer flow)
      3. Insert the order (status="confirmed" for paid, "new" for unpaid)
      4. If driver_partner_id → assign & bump status to "packed"
    """
    # 1) Resolve customer
    if req.user_id:
        user_doc = await db.users.find_one({"user_id": req.user_id}, {"_id": 0})
        if not user_doc:
            raise HTTPException(404, "Customer not found")
    elif req.new_customer:
        if not req.new_customer.name.strip() or not req.new_customer.phone.strip():
            raise HTTPException(400, "New customer needs name + phone")
        # De-dupe check
        existing = None
        if req.new_customer.email:
            existing = await db.users.find_one({"email": str(req.new_customer.email).lower()}, {"_id": 0})
        if not existing:
            existing = await db.users.find_one({"phone": req.new_customer.phone.strip()}, {"_id": 0})
        if existing:
            user_doc = existing
        else:
            uid = f"user_{uuid.uuid4().hex[:12]}"
            user_doc = {
                "user_id": uid,
                "name": req.new_customer.name.strip(),
                "phone": req.new_customer.phone.strip(),
                "role": "customer",
                "loyalty_points": 0,
                "created_at": datetime.now(timezone.utc),
                "default_address": (req.new_customer.address or req.address).model_dump(),
            }
            if req.new_customer.email:
                user_doc["email"] = str(req.new_customer.email).lower()
            await db.users.insert_one(user_doc)
    else:
        raise HTTPException(400, "Must supply either user_id or new_customer")

    # 2) Compute pricing (reuse existing helpers)
    snaps, subtotal = await _resolve_items(req.items)
    if not snaps:
        raise HTTPException(400, "Order must include at least one item")
    settings = await _get_settings()
    delivery_fee = settings.get("default_delivery_fee_cents", DELIVERY_FEE_CENTS)
    taxable = max(0, subtotal + delivery_fee)
    tax_cents = (taxable * settings.get("tax_rate_bps", 1300)) // 10000 \
        if _tax_enabled_for_method(settings, req.payment_method) else 0
    total = taxable + tax_cents

    # 3) Build order
    now = datetime.now(timezone.utc)
    payment_method = req.payment_method if req.payment_method in ("card", "cod", "interac", "paypal") else "cod"
    if req.mark_as_paid:
        payment_status = "paid"
        status = "confirmed"
    else:
        payment_status = {"cod": "cod_pending", "interac": "interac_pending",
                          "card": "pending", "paypal": "pending"}.get(payment_method, "pending")
        status = "confirmed"  # admin-entered = trust it, never "pending_payment"
    tracking = [
        {"status": "new", "ts": now.isoformat(), "note": "Order created by admin"},
        {"status": "confirmed", "ts": now.isoformat(),
         "note": f"Admin entered · {payment_method.upper()} · {'PAID' if req.mark_as_paid else 'unpaid'}"},
    ]

    order = Order(
        user_id=user_doc["user_id"],
        items_snapshot=snaps,
        address=req.address.model_dump(),
        slot=req.slot.model_dump(),
        phone=req.phone,
        subtotal_cents=subtotal,
        delivery_fee_cents=delivery_fee,
        tax_cents=tax_cents,
        tax_label=settings.get("tax_label", "HST"),
        discount_cents=0,
        points_redeemed_cents=0,
        total_cents=total,
        coupon_code=None,
        special_instructions=req.special_instructions or "",
        payment_method=payment_method,
        status=status,
        payment_status=payment_status,
        points_awarded=0,
        tracking_events=tracking,
    )
    order_doc = order.model_dump()
    # Extra marker: created_by_admin
    order_doc["created_by_admin"] = True
    await db.orders.insert_one(order_doc)
    order_doc.pop("_id", None)  # Motor mutates the dict with the ObjectId — strip it

    # Save default address on customer if they don't have one yet
    if not user_doc.get("default_address"):
        await db.users.update_one(
            {"user_id": user_doc["user_id"]},
            {"$set": {"default_address": req.address.model_dump()}},
        )

    # 4) Optional driver assignment → status "packed" + tracking event
    if req.driver_partner_id:
        partner = await db.delivery_partners.find_one(
            {"partner_id": req.driver_partner_id, "is_active": True}, {"_id": 0})
        if not partner:
            raise HTTPException(400, f"Driver {req.driver_partner_id} not found or inactive")
        await db.orders.update_one(
            {"order_id": order_doc["order_id"]},
            {"$set": {
                "delivery_partner_id": partner["partner_id"],
                "delivery_status": "assigned",
                "status": "packed",
                "updated_at": now,
            },
             "$push": {"tracking_events": {
                 "status": "packed", "ts": now.isoformat(),
                 "note": f"Auto-packed & assigned to driver {partner.get('name', partner['partner_id'])}"
             }}},
        )
        order_doc["delivery_partner_id"] = partner["partner_id"]
        order_doc["delivery_status"] = "assigned"
        order_doc["status"] = "packed"

    return {"ok": True, "order": order_doc,
            "customer": {"user_id": user_doc["user_id"],
                         "name": user_doc.get("name"),
                         "phone": user_doc.get("phone")}}


# ==========================================================
# ADMIN — Customers (list, detail, export)
# ==========================================================
async def _customer_summaries(user_ids: Optional[List[str]] = None) -> List[dict]:
    """
    Aggregate customers with their order stats.
    If user_ids is provided, restrict to those. Otherwise all customers (limit 500).
    """
    match: dict = {"role": {"$ne": "delivery_partner"}}
    if user_ids:
        match["user_id"] = {"$in": user_ids}
    users_cur = db.users.find(match, {"_id": 0}).sort("created_at", -1).limit(500)
    users_list = await users_cur.to_list(500)
    ids = [u["user_id"] for u in users_list]
    if not ids:
        return []

    # Aggregate per-user order stats in a single pipeline
    pipe = [
        {"$match": {"user_id": {"$in": ids},
                    "status": {"$ne": "pending_payment"}}},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$user_id",
            "total_orders": {"$sum": 1},
            "total_spent_cents": {"$sum": "$total_cents"},
            "last_order_date": {"$first": "$created_at"},
            "last_order_status": {"$first": "$status"},
        }},
    ]
    stats_map: dict = {}
    async for row in db.orders.aggregate(pipe):
        stats_map[row["_id"]] = row

    out: List[dict] = []
    for u in users_list:
        st = stats_map.get(u["user_id"]) or {}
        addresses = u.get("addresses") or []
        out.append({
            "user_id": u["user_id"],
            "name": u.get("name") or "",
            "email": u.get("email") or "",
            "phone": u.get("phone") or "",
            "role": u.get("role") or "customer",
            "created_at": u.get("created_at"),
            "loyalty_points": int(u.get("loyalty_points") or 0),
            "total_orders": st.get("total_orders", 0),
            "total_spent_cents": st.get("total_spent_cents", 0),
            "last_order_date": st.get("last_order_date"),
            "last_order_status": st.get("last_order_status", ""),
            "addresses": addresses,
            # Include default_address so the admin "New Order" flow can
            # pre-populate the delivery address when picking an existing
            # customer + render the address preview line in the picker.
            "default_address": u.get("default_address"),
        })
    return out


@api.get("/admin/customers")
async def admin_list_customers(admin=Depends(_current_admin),
                               q: Optional[str] = None):
    """List customers with aggregated order stats. Optional 'q' searches name/email/phone."""
    rows = await _customer_summaries()
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows
                if needle in (r["name"] or "").lower()
                or needle in (r["email"] or "").lower()
                or needle in (r["phone"] or "").lower()]
    return rows


@api.get("/admin/customers/{user_id}")
async def admin_customer_detail(user_id: str, admin=Depends(_current_admin)):
    summary = await _customer_summaries([user_id])
    if not summary:
        raise HTTPException(404, "Customer not found")
    orders = await db.orders.find({"user_id": user_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(200)
    return {"customer": summary[0], "orders": orders}


class CustomersExportReq(BaseModel):
    user_ids: List[str] = Field(default_factory=list)  # empty = ALL
    destination: str  # "download" | "email" | "sms" | "drive"
    include_order_history: bool = True
    sms_to: Optional[str] = None
    sms_message: Optional[str] = None
    email_to: Optional[EmailStr] = None


@api.post("/admin/customers/export")
async def admin_export_customers(payload: CustomersExportReq, request: Request,
                                  admin=Depends(_current_admin)):
    if payload.destination not in ("download", "email", "sms", "drive"):
        raise HTTPException(400, "destination must be download|email|sms|drive")
    customers = await _customer_summaries(payload.user_ids or None)
    if not customers:
        raise HTTPException(400, "No customers match the selection")

    orders_by_user: dict[str, list[dict]] = {}
    if payload.include_order_history:
        uids = [c["user_id"] for c in customers]
        async for o in db.orders.find({"user_id": {"$in": uids}}, {"_id": 0}).sort("created_at", -1):
            orders_by_user.setdefault(o["user_id"], []).append(o)

    xlsx = build_customers_xlsx(customers, orders_by_user)
    filename = default_filename("customers")
    return await _finalize_export(
        request, "customers", payload.destination,
        payload.sms_to, payload.sms_message, payload.email_to,
        xlsx, filename, len(customers),
    )


# Invoice HTML (print-friendly, no auth for now — order_id is opaque)
@app.get("/api/invoice/{order_id}")
async def invoice_html(order_id: str):
    from fastapi.responses import HTMLResponse
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Not found")
    settings = await _get_settings()
    user = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0})
    dollars = lambda c: f"CA${(c/100):.2f}"
    rows = "".join(
        f"<tr><td>{it['name']}"
        f"{' · '+str(it.get('catering_guest_count'))+' guests' if it.get('catering_guest_count') else ''}"
        f"</td><td class='r'>{it['quantity']}</td>"
        f"<td class='r'>{dollars(it['unit_price_cents'])}</td>"
        f"<td class='r'>{dollars(it['line_total_cents'])}</td></tr>"
        for it in order.get("items_snapshot", [])
    )
    tax_row = (f"<tr><td colspan='3' class='r muted'>{order.get('tax_label','HST')}</td>"
               f"<td class='r'>{dollars(order.get('tax_cents',0))}</td></tr>") if order.get("tax_cents") else ""
    discount_row = (f"<tr><td colspan='3' class='r muted'>Discount ({order.get('coupon_code','')})</td>"
                    f"<td class='r'>−{dollars(order.get('discount_cents',0))}</td></tr>") if order.get("discount_cents") else ""
    points_row = (f"<tr><td colspan='3' class='r muted'>Loyalty points</td>"
                  f"<td class='r'>−{dollars(order.get('points_redeemed_cents',0))}</td></tr>") if order.get("points_redeemed_cents") else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Invoice {order_id}</title>
<style>
:root{{--brand:#B14F36;--muted:#6B7280;}}
*{{box-sizing:border-box}}body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111;max-width:720px;margin:24px auto;padding:20px}}
.head{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid #eee;padding-bottom:16px;margin-bottom:16px}}
.brand{{color:var(--brand);font-size:26px;font-weight:800;letter-spacing:-.5px}}.sub{{color:var(--muted);font-size:12px;margin-top:4px}}
.badge{{display:inline-block;background:#FBF3EF;color:var(--brand);padding:4px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:2px}}
h2{{margin:0;font-size:20px}}h3{{margin:16px 0 4px;font-size:12px;letter-spacing:2px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:14px}}th,td{{padding:8px 6px;border-bottom:1px solid #eee}}th{{text-align:left;background:#FAF9F6;font-size:11px;letter-spacing:2px;color:var(--muted)}}
.r{{text-align:right}}.muted{{color:var(--muted)}}.total{{font-size:20px;font-weight:800;color:var(--brand)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.card{{border:1px solid #eee;border-radius:12px;padding:12px}}
@media print{{body{{margin:0}}.no-print{{display:none}}}}
button{{background:var(--brand);color:#fff;border:0;padding:10px 16px;border-radius:999px;cursor:pointer;font-weight:800}}
</style></head><body>
<div class="head"><div><div class="brand">{BRAND_NAME}</div><div class="sub">{settings.get('kitchen_address','Greater Toronto Area · GTA')} · {settings.get('phone','')}</div></div>
<div style="text-align:right"><span class="badge">INVOICE</span><h2>#{order_id[-6:].upper()}</h2><div class="sub">{(order['created_at'].isoformat() if hasattr(order['created_at'], 'isoformat') else str(order['created_at']))[:10]}</div></div></div>
<div class="grid"><div class="card"><h3>BILL TO</h3><div><strong>{(user or {{}}).get('name','Guest')}</strong></div><div class="muted">{(user or {{}}).get('email','')}</div><div>{order.get('phone','')}</div></div>
<div class="card"><h3>DELIVER TO</h3><div>{order['address'].get('line1','')}{', '+order['address']['line2'] if order['address'].get('line2') else ''}</div><div class="muted">{order['address'].get('city','')}, {order['address'].get('postal_code','')}</div><div>Slot: {order['slot'].get('window','').replace('_',' ')} · {order['slot'].get('date','')}</div></div></div>
<h3>ITEMS</h3><table><thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit</th><th class="r">Total</th></tr></thead>
<tbody>{rows}
<tr><td colspan="3" class="r muted">Subtotal</td><td class="r">{dollars(order['subtotal_cents'])}</td></tr>
<tr><td colspan="3" class="r muted">Delivery</td><td class="r">{dollars(order['delivery_fee_cents'])}</td></tr>
{discount_row}{points_row}{tax_row}
<tr><td colspan="3" class="r"><strong>Total</strong></td><td class="r total">{dollars(order['total_cents'])}</td></tr>
</tbody></table>
<h3>PAYMENT</h3><div>{'Cash on Delivery' if order.get('payment_method')=='cod' else 'Card (Stripe) · '+order.get('payment_status','').title()}</div>
<div class="no-print" style="margin-top:24px;text-align:right"><button onclick="window.print()">Print / Save PDF</button></div>
</body></html>"""
    return HTMLResponse(content=html)


@app.get("/api/track/{order_id}")
async def track_html(order_id: str):
    """Public, no-login order tracking page (for the SMS tracking link). Shows the
    live delivery status + ETA and auto-refreshes."""
    from fastapi.responses import HTMLResponse
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    settings = await _get_settings()
    dstatus = order.get("delivery_status") or order.get("status") or "confirmed"
    labels = {
        "confirmed": ("Order confirmed", "We're getting your order ready."),
        "preparing": ("Preparing your food", "Our kitchen is cooking your order."),
        "assigned": ("Driver assigned", "A driver has been assigned to your order."),
        "picked_up": ("Picked up", "Your order has left the kitchen."),
        "on_the_way": ("On the way 🚗", "Your driver is heading to you."),
        "arrived": ("Driver has arrived 🛵", "Your driver is at your location."),
        "delivered": ("Delivered ✅", "Enjoy your meal!"),
    }
    title, sub = labels.get(dstatus, ("Order received", "We're processing your order."))
    steps = ["confirmed", "preparing", "on_the_way", "delivered"]
    idx_map = {"confirmed": 0, "preparing": 1, "assigned": 1, "picked_up": 2, "on_the_way": 2, "arrived": 2, "delivered": 3}
    cur_idx = idx_map.get(dstatus, 0)
    eta_s = order.get("delivery_eta_seconds") or 0
    eta_html = ""
    if dstatus in ("on_the_way", "arrived") and eta_s:
        mins = max(1, round(eta_s / 60))
        eta_html = f"<div class='eta'>Estimated arrival: <strong>~{mins} min</strong></div>"
    dollars = lambda c: f"CA${(c/100):.2f}"
    item_rows = "".join(
        f"<li>{it['name']} × {it.get('quantity',1)}{_item_selection_suffix(it)}</li>"
        for it in order.get("items_snapshot", [])
    )
    step_html = "".join(
        f"<div class='step {'on' if i <= cur_idx else ''}'><div class='dot'></div>"
        f"<div class='lbl'>{s.replace('_',' ').title()}</div></div>"
        for i, s in enumerate(steps)
    )
    invoice_url = _invoice_link(order)
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track order #{order_id[-6:].upper()}</title>
<style>
:root{{--brand:#B14F36;--muted:#6B7280}}
*{{box-sizing:border-box}}body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111;max-width:560px;margin:0 auto;padding:20px;background:#FAF9F6}}
.brand{{color:var(--brand);font-size:24px;font-weight:800}}.badge{{display:inline-block;background:#FBF3EF;color:var(--brand);padding:4px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:2px}}
.card{{background:#fff;border:1px solid #eee;border-radius:16px;padding:20px;margin-top:16px}}
h1{{font-size:22px;margin:8px 0 4px}}.sub{{color:var(--muted)}}
.eta{{margin-top:12px;background:#FFF7F3;border:1px solid var(--brand);color:var(--brand);padding:10px 14px;border-radius:12px;font-size:15px}}
.steps{{display:flex;justify-content:space-between;margin:20px 0 4px}}
.step{{flex:1;text-align:center;position:relative}}
.step .dot{{width:16px;height:16px;border-radius:50%;background:#ddd;margin:0 auto 6px}}
.step.on .dot{{background:var(--brand)}}
.step .lbl{{font-size:11px;color:var(--muted)}}.step.on .lbl{{color:#111;font-weight:700}}
ul{{padding-left:18px;color:#333}}li{{margin:4px 0}}
a.btn{{display:inline-block;margin-top:8px;background:var(--brand);color:#fff;padding:10px 18px;border-radius:999px;text-decoration:none;font-weight:800}}
</style>
<meta http-equiv="refresh" content="30"></head><body>
<div class="brand">{BRAND_NAME}</div>
<div class="card">
<span class="badge">ORDER #{order_id[-6:].upper()}</span>
<h1>{title}</h1><div class="sub">{sub}</div>
{eta_html}
<div class="steps">{step_html}</div>
</div>
<div class="card"><h3>Your items</h3><ul>{item_rows}</ul>
<div class="sub">Deliver to: {order['address'].get('line1','')}, {order['address'].get('city','')}</div>
<div class="sub" style="margin-top:6px">Total: <strong>{dollars(order.get('total_cents',0))}</strong></div>
<a class="btn" href="{invoice_url}">View invoice / PDF</a></div>
<div class="sub" style="text-align:center;margin-top:14px;font-size:12px">This page refreshes automatically · {settings.get('phone','')}</div>
</body></html>"""
    return HTMLResponse(content=html)


# ==========================================================
# DELIVERY PARTNER APP (v3)
# ==========================================================
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")


class DeliveryLoginReq(BaseModel):
    email: str
    password: str


class DeliveryPartnerCreateReq(BaseModel):
    name: str
    email: str
    phone: str = ""
    vehicle: str = "car"
    password: str


class DeliveryPartnerUpdateReq(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    vehicle: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class DeliveryLocationReq(BaseModel):
    lat: float
    lng: float


class DeliveryStatusReq(BaseModel):
    status: str  # "picked_up" | "on_the_way" | "arrived" | "delivered"
    note: Optional[str] = None


class DeliveryRouteReq(BaseModel):
    origin_lat: float
    origin_lng: float
    order_ids: List[str]
    optimize: bool = True  # False = respect order_ids order (used after user manually reorders stops)


async def _current_partner(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing partner bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        raise HTTPException(401, "Invalid partner token")
    if payload.get("role") != "delivery_partner":
        raise HTTPException(403, "Not a delivery partner token")
    partner_id = payload.get("sub")
    partner = await db.delivery_partners.find_one({"partner_id": partner_id}, {"_id": 0, "password_hash": 0})
    if not partner or not partner.get("is_active", True):
        raise HTTPException(403, "Partner not active")
    return partner


def _partner_public(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k not in ("password_hash", "_id")}
    return out


# ---- Google Maps helpers ----
async def _google_directions_optimize(origin: str, destination: str, waypoints: List[str], optimize: bool = True) -> Optional[dict]:
    """Call Google Directions API.
    optimize=True → let Google reorder waypoints (waypoints:optimize:true).
    optimize=False → preserve given waypoint order (used after user manually reorders stops).
    origin/destination/waypoints must be "lat,lng" strings (or addresses).
    Returns { waypoint_order: [int], legs: [{duration_sec, distance_m, end_address}] } or None on failure.
    """
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("AIzaSy_PLACEHOLDER"):
        return None
    params = {
        "origin": origin,
        "destination": destination,
        "key": GOOGLE_MAPS_API_KEY,
        "mode": "driving",
    }
    if waypoints:
        prefix = "optimize:true|" if optimize else ""
        params["waypoints"] = prefix + "|".join(waypoints)
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            r = await client.get("https://maps.googleapis.com/maps/api/directions/json", params=params)
        data = r.json()
        if data.get("status") != "OK" or not data.get("routes"):
            logging.warning(f"Google Directions status={data.get('status')} err={data.get('error_message')}")
            return None
        route = data["routes"][0]
        legs = [
            {
                "duration_sec": (leg.get("duration") or {}).get("value", 0),
                "distance_m": (leg.get("distance") or {}).get("value", 0),
                "start_address": leg.get("start_address"),
                "end_address": leg.get("end_address"),
                "end_location": leg.get("end_location"),
            }
            for leg in route.get("legs", [])
        ]
        return {
            "waypoint_order": route.get("waypoint_order", []),
            "legs": legs,
            "overview_polyline": (route.get("overview_polyline") or {}).get("points"),
        }
    except Exception as e:
        logging.error(f"Google Directions call failed: {e}")
        return None


async def _google_geocode(address: str) -> Optional[dict]:
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("AIzaSy_PLACEHOLDER"):
        return None
    try:
        async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": address, "key": GOOGLE_MAPS_API_KEY},
            )
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        loc = data["results"][0]["geometry"]["location"]
        return {"lat": loc["lat"], "lng": loc["lng"],
                "formatted": data["results"][0]["formatted_address"]}
    except Exception as e:
        logging.error(f"Geocode failed: {e}")
        return None


async def _google_reverse_geocode(lat: float, lng: float) -> Optional[dict]:
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("AIzaSy_PLACEHOLDER"):
        return None
    try:
        async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lng}", "key": GOOGLE_MAPS_API_KEY},
            )
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        return {"lat": lat, "lng": lng,
                "formatted": data["results"][0]["formatted_address"]}
    except Exception as e:
        logging.error(f"Reverse-geocode failed: {e}")
        return None


def _address_string(addr: dict) -> str:
    parts = [addr.get(k) for k in ("line1", "line2", "city", "province", "postal_code")]
    return ", ".join([p for p in parts if p])


async def _ensure_order_coords(order: dict) -> Optional[dict]:
    """Ensure the order.address has lat/lng — geocode & persist if missing."""
    addr = order.get("address") or {}
    if addr.get("lat") and addr.get("lng"):
        return addr
    geo = await _google_geocode(_address_string(addr))
    if not geo:
        return None
    addr["lat"] = geo["lat"]
    addr["lng"] = geo["lng"]
    addr["geocoded_at"] = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"order_id": order["order_id"]}, {"$set": {"address": addr}})
    return addr


# ---- Admin: Delivery Partner CRUD ----
@api.post("/admin/delivery-partners")
async def admin_create_partner(req: DeliveryPartnerCreateReq, admin=Depends(_current_admin)):
    if await db.delivery_partners.find_one({"email": req.email.lower()}, {"_id": 0}):
        raise HTTPException(409, "A partner with this email already exists")
    partner = DeliveryPartner(
        name=req.name, email=req.email.lower(), phone=req.phone,
        vehicle=req.vehicle, password_hash=_pwd.hash(req.password),
    ).model_dump()
    await db.delivery_partners.insert_one(partner)
    return {"ok": True, "partner": _partner_public(partner)}


@api.get("/admin/delivery-partners")
async def admin_list_partners(admin=Depends(_current_admin)):
    cur = db.delivery_partners.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1)
    partners = await cur.to_list(200)
    # Attach live counts
    for p in partners:
        p["active_orders"] = await db.orders.count_documents({
            "delivery_partner_id": p["partner_id"],
            "delivery_status": {"$in": ["assigned", "picked_up", "on_the_way", "arrived"]},
        })
    return partners


@api.patch("/admin/delivery-partners/{partner_id}")
async def admin_update_partner(partner_id: str, req: DeliveryPartnerUpdateReq, admin=Depends(_current_admin)):
    patch: Dict[str, Any] = {}
    for f in ("name", "phone", "vehicle", "is_active"):
        v = getattr(req, f)
        if v is not None:
            patch[f] = v
    if req.password:
        patch["password_hash"] = _pwd.hash(req.password)
    if patch:
        patch["updated_at"] = datetime.now(timezone.utc)
        r = await db.delivery_partners.update_one({"partner_id": partner_id}, {"$set": patch})
        if r.matched_count == 0:
            raise HTTPException(404, "Partner not found")
    partner = await db.delivery_partners.find_one({"partner_id": partner_id}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "partner": partner}


@api.delete("/admin/delivery-partners/{partner_id}")
async def admin_delete_partner(partner_id: str, admin=Depends(_current_admin)):
    # Soft delete: deactivate + unassign live orders
    await db.delivery_partners.update_one(
        {"partner_id": partner_id}, {"$set": {"is_active": False}}
    )
    await db.orders.update_many(
        {"delivery_partner_id": partner_id,
         "delivery_status": {"$in": [None, "assigned", "picked_up", "on_the_way", "arrived"]}},
        {"$set": {"delivery_partner_id": None, "delivery_status": None,
                  "delivery_partner_name": None, "delivery_partner_phone": None}},
    )
    return {"ok": True}


# ---- Admin: Assign order to a partner ----
class OrderAssignReq(BaseModel):
    partner_id: Optional[str] = None  # None -> unassign


@api.post("/admin/orders/{order_id}/assign")
async def admin_assign_order(order_id: str, req: OrderAssignReq, admin=Depends(_current_admin)):
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    if req.partner_id is None:
        await db.orders.update_one(
            {"order_id": order_id},
            {"$set": {"delivery_partner_id": None, "delivery_status": None,
                      "delivery_partner_name": None, "delivery_partner_phone": None,
                      "updated_at": datetime.now(timezone.utc)}},
        )
        return {"ok": True, "unassigned": True}
    partner = await db.delivery_partners.find_one({"partner_id": req.partner_id, "is_active": True}, {"_id": 0})
    if not partner:
        raise HTTPException(404, "Delivery partner not found or inactive")
    await db.orders.update_one(
        {"order_id": order_id},
        {"$set": {
            "delivery_partner_id": partner["partner_id"],
            "delivery_partner_name": partner["name"],
            "delivery_partner_phone": partner.get("phone", ""),
            "delivery_status": "assigned",
            "status": "preparing" if order.get("status") in ("new", "confirmed") else order.get("status"),
            "updated_at": datetime.now(timezone.utc),
        }, "$push": {"tracking_events": {
            "event": "assigned_to_partner",
            "partner_id": partner["partner_id"],
            "partner_name": partner["name"],
            "ts": datetime.now(timezone.utc).isoformat(),
        }}},
    )
    # TODO push notify partner (MOCKED — real delivery needs prod build).
    logging.info(f"[push MOCK] order {order_id} assigned to partner {partner['partner_id']}")
    return {"ok": True, "assigned_to": partner["partner_id"]}


# ---- Delivery Partner: Auth ----
@api.post("/delivery/login")
async def delivery_login(req: DeliveryLoginReq):
    # Platform gate — driver app is blocked when the tenant is suspended.
    from platform_client import should_block_driver, snapshot
    if should_block_driver():
        snap = snapshot()
        raise HTTPException(
            402,
            snap.get("banner_text") or (
                f"Delivery is paused because the {BRAND_NAME} owner has not completed "
                "their platform subscription payment. Please contact the restaurant."
            )
        )
    partner = await db.delivery_partners.find_one({"email": req.email.lower()}, {"_id": 0})
    if not partner or not partner.get("is_active", True) or not _pwd.verify(req.password, partner.get("password_hash", "")):
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode(
        {"sub": partner["partner_id"], "role": "delivery_partner",
         "exp": datetime.now(timezone.utc) + timedelta(days=14)},
        JWT_SECRET, algorithm=JWT_ALG,
    )
    return {"access_token": token, "token_type": "bearer",
            "partner": _partner_public(partner)}


@api.get("/delivery/me")
async def delivery_me(partner=Depends(_current_partner)):
    return partner


class GeocodeReq(BaseModel):
    address: str


class ReverseGeocodeReq(BaseModel):
    lat: float
    lng: float


@api.post("/delivery/geocode")
async def delivery_geocode(req: GeocodeReq, partner=Depends(_current_partner)):
    """Turn a free-form address into {lat, lng, formatted}. Partner-scoped to avoid key abuse."""
    if not req.address or not req.address.strip():
        raise HTTPException(400, "Address is required")
    result = await _google_geocode(req.address.strip())
    if not result:
        raise HTTPException(404, "Could not geocode that address")
    return result


@api.post("/delivery/reverse-geocode")
async def delivery_reverse_geocode(req: ReverseGeocodeReq, partner=Depends(_current_partner)):
    """Turn {lat,lng} into a human-readable address for display."""
    result = await _google_reverse_geocode(req.lat, req.lng)
    if not result:
        raise HTTPException(404, "Could not resolve that location")
    return result


@api.get("/delivery/orders")
async def delivery_list_orders(partner=Depends(_current_partner),
                               status: Optional[str] = None):
    q: Dict[str, Any] = {"delivery_partner_id": partner["partner_id"]}
    if status == "active":
        q["delivery_status"] = {"$in": ["assigned", "picked_up", "on_the_way", "arrived"]}
    elif status == "completed":
        q["delivery_status"] = "delivered"
    elif status:
        q["delivery_status"] = status
    cur = db.orders.find(q, {"_id": 0, "stripe_session_id": 0}).sort("created_at", 1)
    orders = await cur.to_list(200)
    # Enrich each order with customer_name resolved from the linked user
    user_ids = list({o.get("user_id") for o in orders if o.get("user_id")})
    users = {}
    if user_ids:
        async for u in db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}):
            users[u["user_id"]] = u
    for o in orders:
        u = users.get(o.get("user_id")) or {}
        # priority: address.name (checkout override) > user.name > "Guest"
        addr_name = ((o.get("address") or {}).get("name") or "").strip()
        user_name = (u.get("name") or "").strip()
        o["customer_name"] = addr_name or user_name or "Guest"
    return orders


@api.post("/delivery/location")
async def delivery_update_location(req: DeliveryLocationReq, partner=Depends(_current_partner)):
    """Live GPS heartbeat from the delivery-partner app.

    Alongside stashing the coords, we:
      1. Broadcast the fresh lat/lng onto every ACTIVE order for this partner
         (assigned / picked_up / on_the_way / arrived), so admins + fallback
         readers stay in sync.
      2. Recompute each order's `delivery_eta_seconds` using a straight-line
         (haversine) distance ÷ 30 km/h — this keeps the customer's
         "Arriving in ~X min" *decreasing* on every ping without spending
         a Directions call per heartbeat.
      3. Optionally refresh the per-order `route_polyline` (driver → home)
         via Google Directions, but ONLY when the driver has moved ≥300m
         since the last refresh OR the polyline is >60s stale. Throttled so
         a moving driver at 40 km/h costs at most ~1 Directions call/min/order.
    """
    ts = datetime.now(timezone.utc)
    await db.delivery_partners.update_one(
        {"partner_id": partner["partner_id"]},
        {"$set": {"current_lat": req.lat, "current_lng": req.lng, "current_location_updated_at": ts}},
    )

    # Pull all active orders for this partner — we'll fan out per-order updates below.
    active_orders = await db.orders.find(
        {"delivery_partner_id": partner["partner_id"],
         "delivery_status": {"$in": ["assigned", "picked_up", "on_the_way", "arrived"]}},
        {"_id": 0, "order_id": 1, "address": 1, "route_polyline": 1,
         "route_polyline_updated_at": 1, "route_polyline_origin": 1},
    ).to_list(50)

    for o in active_orders:
        addr = o.get("address") or {}
        dlat, dlng = addr.get("lat"), addr.get("lng")
        patch: Dict[str, Any] = {
            "delivery_partner_lat": req.lat,
            "delivery_partner_lng": req.lng,
            "delivery_partner_updated_at": ts,
        }
        if dlat is not None and dlng is not None:
            dist_m = _haversine_m(req.lat, req.lng, dlat, dlng)
            # 30 km/h avg city speed + 20s idle buffer. This is a straight-line
            # heuristic — Directions is the source of truth when it refreshes.
            eta_s = max(0, int((dist_m / 1000.0) / 30.0 * 3600) + 20)
            patch["delivery_eta_seconds"] = eta_s
            patch["delivery_distance_m"] = int(dist_m)
            patch["delivery_eta_updated_at"] = ts

            # Refresh the per-order polyline if we've moved far enough or it's stale.
            last_ts = o.get("route_polyline_updated_at")
            last_origin = o.get("route_polyline_origin") or {}
            moved_m = _haversine_m(
                req.lat, req.lng,
                last_origin.get("lat", req.lat), last_origin.get("lng", req.lng),
            ) if last_origin else 999_999
            # MongoDB round-trips datetimes as offset-naive; normalise to UTC
            # so the (ts - last_ts) subtraction against our offset-aware `ts`
            # doesn't raise TypeError.
            if last_ts and last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            stale = not last_ts or (ts - last_ts).total_seconds() > 60
            if (moved_m >= 300 or stale) and not o.get("route_polyline_refreshing"):
                # Fire-and-forget so we don't stall the heartbeat.
                asyncio.create_task(_refresh_order_polyline(
                    order_id=o["order_id"], from_lat=req.lat, from_lng=req.lng,
                    to_lat=dlat, to_lng=dlng,
                ))
        await db.orders.update_one({"order_id": o["order_id"]}, {"$set": patch})

    return {"ok": True}


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres. Good enough for ETA + arrival alerts."""
    import math
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


async def _refresh_order_polyline(order_id: str, from_lat: float, from_lng: float,
                                   to_lat: float, to_lng: float) -> None:
    """Fetch a fresh driver→home polyline from Google Directions and store it
    on the order. Best-effort — silently no-ops if the Maps key isn't set."""
    try:
        # Flag so concurrent heartbeats don't stack refresh calls.
        await db.orders.update_one({"order_id": order_id},
                                    {"$set": {"route_polyline_refreshing": True}})
        route = await _google_directions_optimize(
            origin=f"{from_lat},{from_lng}",
            destination=f"{to_lat},{to_lng}",
            waypoints=[],
            optimize=False,
        )
        patch: Dict[str, Any] = {"route_polyline_refreshing": False}
        if route and route.get("overview_polyline"):
            patch["route_polyline"] = route["overview_polyline"]
            patch["route_polyline_updated_at"] = datetime.now(timezone.utc)
            patch["route_polyline_origin"] = {"lat": from_lat, "lng": from_lng}
            # Also use Directions' real duration if we got one (more accurate than haversine).
            legs = route.get("legs") or []
            if legs and legs[0].get("duration_sec"):
                patch["delivery_eta_seconds"] = int(legs[0]["duration_sec"]) + 20
        await db.orders.update_one({"order_id": order_id}, {"$set": patch})
    except Exception as e:
        logging.warning(f"polyline refresh failed for {order_id}: {e}")
        await db.orders.update_one({"order_id": order_id},
                                    {"$set": {"route_polyline_refreshing": False}})


def _public_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    base = (os.environ.get("PUBLIC_BASE_URL", "") or os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")
    return f"{base}{path}" if base else path


def _public_base_from_request(request: Request, client_base_url: Optional[str] = None) -> str:
    """Resolve the public origin for building clickable links. Priority:
    explicit env → forwarded/host header from the ingress → client-provided origin.
    Never returns a localhost origin (unusable in SMS/email)."""
    env = (os.environ.get("PUBLIC_BASE_URL", "") or os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")
    if env:
        return env
    try:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
        host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        if host and "localhost" not in host and "127.0.0.1" not in host:
            return f"{proto}://{host}"
    except Exception:
        pass
    if client_base_url:
        return client_base_url.rstrip("/")
    return ""


def _order_base(order: dict) -> str:
    """Absolute base origin stored on the order (falls back to env)."""
    base = (order or {}).get("public_base_url") or ""
    if base:
        return base.rstrip("/")
    return (os.environ.get("PUBLIC_BASE_URL", "") or os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")


def _invoice_link(order: dict) -> str:
    base = _order_base(order)
    return f"{base}/api/invoice/{order.get('order_id','')}" if base else f"/api/invoice/{order.get('order_id','')}"


def _track_link(order: dict) -> str:
    base = _order_base(order)
    return f"{base}/api/track/{order.get('order_id','')}" if base else f"/api/track/{order.get('order_id','')}"


NOTIFY_PHONE_DEFAULT = "+14374999453"  # restaurant owner's number


async def _notify_owner_delivered(order: dict):
    """Best-effort Email + SMS to the restaurant owner when an order is delivered.
    Never raises — notification failures must not block the delivery flow."""
    settings = await _get_settings()
    oid = order.get("order_id", "")
    cust = (order.get("address") or {}).get("name") or "Customer"
    total = order.get("total_cents", 0) / 100
    partner = order.get("delivery_partner_name") or "driver"
    proof = order.get("delivery_proof_photo_url") or ""
    proof_line = f" Proof photo: {_public_url(proof)}" if proof else ""

    # ---- Email (Resend) ----
    owner_emails = _notify_list(settings.get("notify_email")) or ([ADMIN_EMAIL] if ADMIN_EMAIL else [])
    try:
        if _email.is_configured():
            html = (
                f"<h2>Order {oid} delivered ✅</h2>"
                f"<p><b>{BRAND_NAME}</b></p>"
                f"<p>Customer: {cust}<br/>Total: ${total:.2f}<br/>Delivered by: {partner}</p>"
                + (f'<p><a href="{_public_url(proof)}">View delivery proof photo</a></p>' if proof else "")
            )
            for to_email in owner_emails:
                try:
                    await _email.send_email(to=to_email, subject=f"{BRAND_NAME} — Order {oid} delivered", html=html)
                except Exception as e:
                    logging.warning(f"[notify.email] {e}")
    except Exception as e:
        logging.warning(f"[notify.email] {e}")

    # ---- SMS (Twilio, using owner-captured settings) ----
    tw = (settings.get("integrations") or {}).get("twilio") or {}
    owner_phones = _notify_list(settings.get("notify_phone")) or ([NOTIFY_PHONE_DEFAULT] if NOTIFY_PHONE_DEFAULT else [])
    try:
        if tw.get("account_sid") and tw.get("auth_token_encrypted") and tw.get("from_number"):
            body = f"{BRAND_NAME}: Order {oid} delivered to {cust}. Total ${total:.2f} by {partner}.{proof_line}"
            for to_phone in owner_phones:
                try:
                    await _twilio.send_sms(tw["account_sid"], tw["auth_token_encrypted"], tw["from_number"], to_phone, body)
                except Exception as e:
                    logging.warning(f"[notify.sms] {e}")
    except Exception as e:
        logging.warning(f"[notify.sms] {e}")


def _item_selection_suffix(it: dict) -> str:
    """Human bracket listing the actual dishes chosen for a weekly plan / catering
    line, e.g. ' (Chicken Biryani × 2, Paneer Butter Masala)'."""
    if it.get("kind") == "weekly_package":
        names = it.get("package_selection_names") or []
        if names:
            return f" ({', '.join(names)})"
    if it.get("kind") == "catering":
        picks = []
        for grp in it.get("selection_summary") or []:
            picks.extend(grp.get("items") or [])
        if picks:
            return f" ({', '.join(picks)})"
    return ""


def _order_items_text(order: dict) -> str:
    """One line per item: 'Weekly Combo x1 (Chicken Biryani × 2, Paneer) — CA$69.99'."""
    lines = []
    for it in order.get("items_snapshot", []):
        qty = it.get("quantity", 1)
        lines.append(f"• {it['name']} x{qty}{_item_selection_suffix(it)} — CA${it.get('line_total_cents', 0)/100:.2f}")
    return "\n".join(lines)


def _payment_note(order: dict, settings: dict) -> str:
    pm = order.get("payment_method")
    total = order.get("total_cents", 0) / 100
    if pm == "cod":
        return f"Cash on Delivery — please keep CA${total:.2f} ready for the driver."
    if pm == "interac":
        interac_email = (settings.get("payment_methods") or {}).get("interac", {}).get("email", "")
        return f"Interac e-Transfer — please send CA${total:.2f} to {interac_email} (add order {order.get('order_id','')} in the note)."
    return f"Total CA${total:.2f}."


def _notify_list(value) -> list:
    """Split a comma-separated notify field into clean values.

    Single values pass through unchanged; empty pieces are dropped, so
    "a@x, b@y" notifies both owners while "a@x" behaves exactly as before.
    """
    if not value:
        return []
    parts = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(p).strip() for p in parts if str(p).strip()]


async def _send_sms_via_settings(settings: dict, to: str, body: str):
    tw = (settings.get("integrations") or {}).get("twilio") or {}
    if to and tw.get("account_sid") and tw.get("auth_token_encrypted") and tw.get("from_number"):
        await _twilio.send_sms(tw["account_sid"], tw["auth_token_encrypted"], tw["from_number"], to, body)


async def _notify_order_created(order: dict, settings: dict, user_doc: dict):
    """Best-effort order-confirmation to the customer (Email + SMS) and the owner
    (Email + SMS). Never raises — a messaging failure must not fail the order."""
    oid = order.get("order_id", "")
    cust = (order.get("address") or {}).get("name") or (user_doc or {}).get("name") or "Customer"
    cust_email = (order.get("address") or {}).get("email") or (user_doc or {}).get("email") or ""
    cust_phone = order.get("phone") or ""
    total = order.get("total_cents", 0) / 100
    items_txt = _order_items_text(order)
    pay_note = _payment_note(order, settings)
    invoice_url = _invoice_link(order)
    ref = oid[-6:].upper()

    # ---- Customer email (Resend) ----
    try:
        if cust_email and _email.is_configured():
            rows = "".join(
                f"<tr><td style='padding:4px 0'>{it['name']} × {it.get('quantity',1)}{_item_selection_suffix(it)}</td>"
                f"<td style='padding:4px 0;text-align:right'>CA${it.get('line_total_cents',0)/100:.2f}</td></tr>"
                for it in order.get("items_snapshot", [])
            )
            html = (
                f"<h2>Thanks for your order, {cust}! 🎉</h2>"
                f"<p><b>{BRAND_NAME}</b> — Order #{ref}</p>"
                f"<table style='width:100%;max-width:420px;border-collapse:collapse'>{rows}"
                f"<tr><td style='padding:6px 0;border-top:1px solid #eee'><b>Total</b></td>"
                f"<td style='padding:6px 0;border-top:1px solid #eee;text-align:right'><b>CA${total:.2f}</b></td></tr></table>"
                f"<p>{pay_note}</p>"
                f"<p><a href='{invoice_url}' style='background:#011838;color:#fff;padding:10px 18px;border-radius:24px;text-decoration:none;font-weight:800'>View / download invoice (PDF)</a></p>"
                f"<p style='color:#666;font-size:12px'>Delivery: {order.get('slot',{}).get('window','').replace('_',' ')} · {order.get('slot',{}).get('date','')}</p>"
            )
            await _email.send_email(to=cust_email, subject=f"{BRAND_NAME} — Order #{ref} confirmed", html=html)
    except Exception as e:
        logging.warning(f"[order.notify.cust_email] {e}")

    # ---- Customer SMS (Twilio) ----
    try:
        body = (f"{BRAND_NAME}: Order #{ref} confirmed!\n{items_txt}\nTotal CA${total:.2f}\n{pay_note}\nInvoice: {invoice_url}")
        await _send_sms_via_settings(settings, cust_phone, body)
    except Exception as e:
        logging.warning(f"[order.notify.cust_sms] {e}")

    # ---- Owner email + SMS (notify fields accept comma-separated multiples) ----
    owner_emails = _notify_list(settings.get("notify_email")) or ([ADMIN_EMAIL] if ADMIN_EMAIL else [])
    owner_phones = _notify_list(settings.get("notify_phone"))
    try:
        if _email.is_configured():
            html = (
                f"<h2>New order #{ref} 🛎️</h2>"
                f"<p>Customer: {cust} · {cust_phone} · {cust_email}</p>"
                f"<pre style='font-family:inherit'>{items_txt}</pre>"
                f"<p><b>Total CA${total:.2f}</b> · {order.get('payment_method','').upper()}</p>"
                f"<p>Deliver to: {(order.get('address') or {}).get('line1','')}, {(order.get('address') or {}).get('city','')}</p>"
                f"<p><a href='{invoice_url}'>Invoice</a></p>"
            )
            for to_email in owner_emails:
                try:
                    await _email.send_email(to=to_email, subject=f"{BRAND_NAME} — New order #{ref} (CA${total:.2f})", html=html)
                except Exception as e:
                    logging.warning(f"[order.notify.owner_email] {e}")
    except Exception as e:
        logging.warning(f"[order.notify.owner_email] {e}")
    try:
        if owner_phones:
            addr = order.get("address") or {}
            slot = order.get("slot") or {}
            body = (
                f"{BRAND_NAME}: New order #{ref} — {cust}\n"
                f"{items_txt}\n"
                f"Total CA${total:.2f} ({order.get('payment_method','').upper()})\n"
                f"Deliver: {addr.get('line1','')}, {addr.get('city','')}\n"
                f"Slot: {slot.get('date','')} {slot.get('window','').replace('_',' ')}"
            )
            for to_phone in owner_phones:
                try:
                    await _send_sms_via_settings(settings, to_phone, body)
                except Exception as e:
                    logging.warning(f"[order.notify.owner_sms] {e}")
    except Exception as e:
        logging.warning(f"[order.notify.owner_sms] {e}")


async def _notify_customer_eta(order: dict, settings: dict, exact: bool):
    """Notify the customer of a delivery ETA. Registered users get an in-app push;
    guests get an SMS with a tracking link. Best-effort (never raises)."""
    oid = order.get("order_id", "")
    eta_s = order.get("delivery_eta_seconds") or 0
    mins = max(1, round(eta_s / 60)) if eta_s else None
    when = (f"in {mins} min" if mins else "shortly")
    title = "Your order is on the way 🚗" if not exact else "Arriving soon 🛵"
    msg = (f"Your {BRAND_NAME} order is out for delivery — arriving {('~' if not exact else '')}{when}."
           if not exact else f"Your {BRAND_NAME} order is arriving {when}. Please be ready!")
    track_url = _track_link(order)
    user_doc = await db.users.find_one({"user_id": order.get("user_id")}, {"_id": 0}) or {}
    is_guest = (user_doc.get("role") == "guest")
    # In-app push (works on real builds; no-op otherwise)
    try:
        await send_push(recipients=[order.get("user_id")],
                        data={"title": title, "message": msg, "action_url": f"/order/{oid}"})
    except Exception as e:
        logging.warning(f"[eta.push] {e}")
    # Guests: SMS with tracking link
    if is_guest:
        try:
            await _send_sms_via_settings(settings, order.get("phone") or "",
                                         f"{BRAND_NAME}: {msg} Track: {track_url}")
        except Exception as e:
            logging.warning(f"[eta.sms] {e}")


@api.post("/delivery/orders/{order_id}/proof")
async def delivery_upload_proof(order_id: str, photo: UploadFile = File(...), partner=Depends(_current_partner)):
    """Delivery partner uploads a proof-of-delivery photo."""
    order = await db.orders.find_one({"order_id": order_id, "delivery_partner_id": partner["partner_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found for this partner")
    ext = (photo.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "webp", "heic"):
        ext = "jpg"
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = UPLOADS_DIR / "delivery" / fname
    data = await photo.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(400, "Photo too large (max 12 MB)")
    dest.write_bytes(data)
    url = f"/api/uploads/delivery/{fname}"
    await db.orders.update_one({"order_id": order_id}, {"$set": {"delivery_proof_photo_url": url, "updated_at": datetime.now(timezone.utc)}})
    return {"ok": True, "delivery_proof_photo_url": url}


@api.post("/delivery/orders/{order_id}/status")
async def delivery_update_order_status(order_id: str, req: DeliveryStatusReq, partner=Depends(_current_partner)):
    allowed = {"picked_up", "on_the_way", "arrived", "delivered"}
    if req.status not in allowed:
        raise HTTPException(400, f"Invalid delivery status. Allowed: {sorted(allowed)}")
    order = await db.orders.find_one({"order_id": order_id, "delivery_partner_id": partner["partner_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found for this partner")
    patch: Dict[str, Any] = {
        "delivery_status": req.status,
        "updated_at": datetime.now(timezone.utc),
    }
    if req.status == "picked_up":
        patch["status"] = "out_for_delivery"
    elif req.status == "on_the_way":
        patch["status"] = "out_for_delivery"
    elif req.status == "delivered":
        patch["status"] = "delivered"
        patch["delivery_eta_seconds"] = 0
        # Also stop refreshing the polyline once we're done — prevents a stale
        # driver→home path from lingering on the customer's post-delivery view.
        patch["route_polyline"] = None
        patch["route_polyline_refreshing"] = False
    await db.orders.update_one({"order_id": order_id}, {"$set": patch, "$push": {"tracking_events": {
        "event": req.status, "note": req.note or "", "ts": datetime.now(timezone.utc).isoformat(),
    }}})
    # Push customer notification MOCK
    logging.info(f"[push MOCK] order {order_id} status → {req.status}")
    if req.status == "delivered":
        fresh = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
        if fresh:
            await _notify_owner_delivered(fresh)
        # The next stop is now "1 stop away" — send it an exact ETA (once).
        try:
            settings = await _get_settings()
            nxt = await db.orders.find({
                "delivery_partner_id": partner["partner_id"],
                "delivery_status": {"$in": ["assigned", "picked_up", "on_the_way", "arrived"]},
                "exact_eta_sent": {"$ne": True},
            }, {"_id": 0}).sort("delivery_eta_seconds", 1).to_list(1)
            if nxt:
                await _notify_customer_eta(nxt[0], settings, exact=True)
                await db.orders.update_one({"order_id": nxt[0]["order_id"]}, {"$set": {"exact_eta_sent": True}})
        except Exception as e:
            logging.warning(f"[next.eta] {e}")
    return {"ok": True, "status": req.status}


class JourneyStopSnapshot(BaseModel):
    order_id: str
    route_index: int
    eta_seconds: int
    duration_sec: int
    distance_m: int
    address: str
    lat: float
    lng: float


class DeliveryJourneyStartReq(BaseModel):
    order_ids: List[str]
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    origin_address: Optional[str] = None
    # Full snapshot of the route so we can restore the same view on re-login.
    stops: Optional[List[JourneyStopSnapshot]] = None
    polyline: Optional[str] = None
    total_duration_sec: Optional[int] = None
    optimized: Optional[bool] = None


@api.post("/delivery/journey/start")
async def delivery_start_journey(req: DeliveryJourneyStartReq, partner=Depends(_current_partner)):
    """Delivery partner presses START DELIVERY.
    - Marks all provided orders (must belong to partner and currently 'assigned' or 'picked_up') as 'on_the_way'.
    - Stamps a journey_started_at and delivery_partner location so the customer tracking screen shows a live ETA.
    - Persists the full route snapshot on the partner doc so re-login restores the same plan.
    - Returns the count of orders flipped.
    """
    now = datetime.now(timezone.utc)
    # Update partner journey state + last known location + persisted route snapshot
    partner_patch: Dict[str, Any] = {
        "journey_started_at": now,
        "journey_active": True,
        "journey_order_ids": req.order_ids,
    }
    if req.origin_lat is not None and req.origin_lng is not None:
        partner_patch["current_lat"] = req.origin_lat
        partner_patch["current_lng"] = req.origin_lng
        partner_patch["current_location_updated_at"] = now
        partner_patch["journey_origin_lat"] = req.origin_lat
        partner_patch["journey_origin_lng"] = req.origin_lng
    if req.origin_address:
        partner_patch["journey_origin_address"] = req.origin_address
    if req.stops is not None:
        partner_patch["journey_stops"] = [s.dict() for s in req.stops]
    if req.polyline is not None:
        partner_patch["journey_polyline"] = req.polyline
    if req.total_duration_sec is not None:
        partner_patch["journey_total_duration_sec"] = req.total_duration_sec
    if req.optimized is not None:
        partner_patch["journey_optimized"] = req.optimized
    await db.delivery_partners.update_one(
        {"partner_id": partner["partner_id"]}, {"$set": partner_patch}
    )
    # Flip orders → on_the_way (customer sees ETA) AND back-fill the customer's
    # status timeline: preparing → packed → out_for_delivery.
    # We do this per-order (not update_many) so we can append MISSING events without
    # duplicating any that already exist (e.g. if admin already marked "preparing").
    orders_to_flip = await db.orders.find({
        "order_id": {"$in": req.order_ids},
        "delivery_partner_id": partner["partner_id"],
        "delivery_status": {"$in": ["assigned", "picked_up"]},
    }, {"_id": 0}).to_list(200)

    flipped = 0
    now_iso = now.isoformat()
    for o in orders_to_flip:
        existing = [e.get("status") for e in (o.get("tracking_events") or []) if e.get("status")]
        # Any of these steps that haven't been logged yet should be logged now,
        # sequentially, so the customer app ticks them all green.
        auto_steps = [
            ("preparing",         "Kitchen prepared your order"),
            ("packed",            "Order packed and ready"),
            ("out_for_delivery",  "Driver started the delivery journey"),
        ]
        to_add = [
            {"status": s, "ts": now_iso, "note": note}
            for s, note in auto_steps if s not in existing
        ]
        patch: Dict[str, Any] = {
            "delivery_status": "on_the_way",
            "status": "out_for_delivery",
            "journey_started_at": now,
            "updated_at": now,
        }
        if req.origin_lat is not None and req.origin_lng is not None:
            patch["delivery_partner_lat"] = req.origin_lat
            patch["delivery_partner_lng"] = req.origin_lng
            patch["delivery_partner_updated_at"] = now
        push: Dict[str, Any] = {}
        if to_add:
            push["tracking_events"] = {"$each": to_add}
        update: Dict[str, Any] = {"$set": patch}
        if push:
            update["$push"] = push
        r = await db.orders.update_one({"order_id": o["order_id"]}, update)
        if r.modified_count:
            flipped += 1

    logging.info(f"[journey start] partner={partner['partner_id']} flipped={flipped}")

    # ETA notifications: the immediate next stop gets an EXACT ETA; the rest get
    # a tentative "on the way" heads-up. Guests receive an SMS w/ tracking link.
    try:
        settings = await _get_settings()
        stop_eta = {s.order_id: s.eta_seconds for s in (req.stops or [])}
        ordered_ids = ([s.order_id for s in sorted(req.stops, key=lambda x: x.route_index)]
                       if req.stops else [o["order_id"] for o in orders_to_flip])
        for idx, oid in enumerate(ordered_ids):
            od = await db.orders.find_one({"order_id": oid}, {"_id": 0})
            if not od:
                continue
            if oid in stop_eta:
                await db.orders.update_one({"order_id": oid}, {"$set": {"delivery_eta_seconds": stop_eta[oid]}})
                od["delivery_eta_seconds"] = stop_eta[oid]
            is_next = (idx == 0)
            await _notify_customer_eta(od, settings, exact=is_next)
            if is_next:
                await db.orders.update_one({"order_id": oid}, {"$set": {"exact_eta_sent": True}})
    except Exception as e:
        logging.warning(f"[journey.eta] {e}")

    return {"ok": True, "flipped": flipped, "journey_started_at": now.isoformat()}


@api.post("/delivery/journey/end")
async def delivery_end_journey(partner=Depends(_current_partner)):
    """Delivery partner presses END DELIVERY (or all orders delivered)."""
    await db.delivery_partners.update_one(
        {"partner_id": partner["partner_id"]},
        {"$set": {"journey_active": False, "journey_ended_at": datetime.now(timezone.utc)},
         "$unset": {"journey_stops": "", "journey_polyline": "",
                    "journey_origin_lat": "", "journey_origin_lng": "",
                    "journey_origin_address": "", "journey_total_duration_sec": "",
                    "journey_optimized": "", "journey_order_ids": ""}},
    )
    return {"ok": True}


@api.get("/delivery/journey/current")
async def delivery_current_journey(partner=Depends(_current_partner)):
    """Return the persisted active journey for this partner (or `null` if none).

    Used by the delivery app on login to restore the exact same route the driver
    was working on before they closed / logged out.
    """
    doc = await db.delivery_partners.find_one({"partner_id": partner["partner_id"]}, {"_id": 0})
    if not doc or not doc.get("journey_active"):
        return {"active": False, "journey": None}
    started = doc.get("journey_started_at")
    return {
        "active": True,
        "journey": {
            "started_at": (started.isoformat() if hasattr(started, "isoformat") else started),
            "origin_lat": doc.get("journey_origin_lat"),
            "origin_lng": doc.get("journey_origin_lng"),
            "origin_address": doc.get("journey_origin_address"),
            "order_ids": doc.get("journey_order_ids", []),
            "stops": doc.get("journey_stops", []),
            "polyline": doc.get("journey_polyline"),
            "total_duration_sec": doc.get("journey_total_duration_sec", 0),
            "optimized": doc.get("journey_optimized", True),
        },
    }


@api.post("/delivery/route")
async def delivery_optimize_route(req: DeliveryRouteReq, partner=Depends(_current_partner)):
    """Build a route from origin through all provided orders back to origin.
    When req.optimize is True, Google reorders waypoints for shortest total time.
    When False, the given order_ids order is respected (used after user drags stops)."""
    orders = await db.orders.find(
        {"order_id": {"$in": req.order_ids}, "delivery_partner_id": partner["partner_id"]},
        {"_id": 0}
    ).to_list(50)
    if not orders:
        raise HTTPException(404, "No matching orders for this partner")
    # Ensure every order has a lat/lng
    resolved: List[dict] = []
    for o in orders:
        addr = await _ensure_order_coords(o)
        if not addr or not addr.get("lat") or not addr.get("lng"):
            continue
        resolved.append({**o, "address": addr})
    if not resolved:
        raise HTTPException(400, "Could not geocode any of the order addresses.")

    # If user manually reordered, honour that order — sort `resolved` by req.order_ids position.
    if not req.optimize:
        order_pos = {oid: i for i, oid in enumerate(req.order_ids)}
        resolved.sort(key=lambda o: order_pos.get(o["order_id"], 999))

    origin = f"{req.origin_lat},{req.origin_lng}"
    waypoints = [f"{o['address']['lat']},{o['address']['lng']}" for o in resolved]
    # Return-to-origin route: destination == origin, all stops as waypoints
    result = await _google_directions_optimize(origin, origin, waypoints, optimize=req.optimize)

    if not result:
        # Fallback: preserve given order, compute a naive Haversine ETA per leg (5min per stop)
        stops = []
        total_dur = 0
        for idx, o in enumerate(resolved):
            eta = (idx + 1) * 900  # 15min per stop
            stops.append({
                "order_id": o["order_id"], "route_index": idx,
                "eta_seconds": eta,
                "duration_sec": 900, "distance_m": 5000,
                "address": _address_string(o["address"]),
                "lat": o["address"]["lat"], "lng": o["address"]["lng"],
            })
            total_dur += 900
        return {"ok": True, "optimized": False, "stops": stops, "total_duration_sec": total_dur,
                "polyline": None, "note": "Google Maps unavailable — using naive ETA."}

    # Reorder resolved based on Google's optimized waypoint_order
    order_indices = result.get("waypoint_order") or list(range(len(resolved)))
    stops = []
    cumulative_dur = 0
    for pos, orig_idx in enumerate(order_indices):
        o = resolved[orig_idx]
        # legs[pos] is origin → this stop; legs[pos].duration is time from previous stop to this stop
        leg = result["legs"][pos] if pos < len(result["legs"]) else {"duration_sec": 0, "distance_m": 0}
        cumulative_dur += leg.get("duration_sec", 0)
        stops.append({
            "order_id": o["order_id"], "route_index": pos,
            "eta_seconds": cumulative_dur,
            "duration_sec": leg.get("duration_sec", 0),
            "distance_m": leg.get("distance_m", 0),
            "address": _address_string(o["address"]),
            "lat": o["address"]["lat"], "lng": o["address"]["lng"],
        })

    # Persist route order + ETA on each order for customer polling
    now = datetime.now(timezone.utc)
    for s in stops:
        await db.orders.update_one(
            {"order_id": s["order_id"]},
            {"$set": {
                "delivery_route_order": s["route_index"],
                "delivery_eta_seconds": s["eta_seconds"],
                "delivery_leg_duration_sec": s["duration_sec"],  # time for THIS leg only (previous → this)
                "delivery_leg_distance_m": s["distance_m"],
                "delivery_eta_updated_at": now,
            }},
        )

    return {"ok": True, "optimized": req.optimize, "stops": stops,
            "total_duration_sec": cumulative_dur,
            "polyline": result.get("overview_polyline")}


# ---- Customer: Tracking endpoint (polling) ----
@api.get("/orders/{order_id}/tracking")
async def order_tracking(order_id: str, user: User = Depends(_current_user)):
    order = await db.orders.find_one({"order_id": order_id, "user_id": user.user_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")

    # Compute how many stops are between the driver's current position and this order.
    # Only meaningful if this order is on an active route (assigned/picked_up/on_the_way/arrived).
    stops_away: Optional[int] = None
    partner_id = order.get("delivery_partner_id")
    my_route_idx = order.get("delivery_route_order")
    my_delivery_status = order.get("delivery_status")
    if partner_id and my_route_idx is not None and my_delivery_status not in ("delivered", None):
        stops_away = await db.orders.count_documents({
            "delivery_partner_id": partner_id,
            "delivery_status": {"$in": ["assigned", "picked_up", "on_the_way", "arrived"]},
            "delivery_route_order": {"$lt": my_route_idx},
        })
    elif my_delivery_status == "delivered":
        stops_away = 0

    # Live partner location — read directly from the delivery_partners doc so
    # we always show the driver's CURRENT GPS ping, not the stale snapshot that
    # was stamped onto the order when the journey started. Falls back to the
    # order's copy if the partner doc has no live coords yet.
    partner_loc: Optional[dict] = None
    partner_doc: Optional[dict] = None
    if partner_id:
        partner_doc = await db.delivery_partners.find_one(
            {"partner_id": partner_id},
            {"_id": 0, "current_lat": 1, "current_lng": 1,
             "current_location_updated_at": 1, "journey_polyline": 1},
        )
    if partner_doc and partner_doc.get("current_lat") is not None:
        partner_loc = {
            "lat": partner_doc.get("current_lat"),
            "lng": partner_doc.get("current_lng"),
            "updated_at": partner_doc.get("current_location_updated_at"),
        }
    elif order.get("delivery_partner_lat") is not None:
        partner_loc = {
            "lat": order.get("delivery_partner_lat"),
            "lng": order.get("delivery_partner_lng"),
            "updated_at": order.get("delivery_partner_updated_at"),
        }

    return {
        "order_id": order_id,
        "status": order.get("status"),
        "delivery_status": order.get("delivery_status"),
        "delivery_partner": {
            "name": order.get("delivery_partner_name"),
            "phone": order.get("delivery_partner_phone"),
        } if order.get("delivery_partner_id") else None,
        "partner_location": partner_loc,
        "destination": {
            "lat": (order.get("address") or {}).get("lat"),
            "lng": (order.get("address") or {}).get("lng"),
            "address": _address_string(order.get("address") or {}),
        } if (order.get("address") or {}).get("lat") else None,
        "eta_seconds": order.get("delivery_eta_seconds"),              # cumulative from driver's start location
        "leg_duration_sec": order.get("delivery_leg_duration_sec"),   # time for JUST this leg (previous → me)
        "eta_updated_at": order.get("delivery_eta_updated_at"),
        "stops_away": stops_away,
        "route_polyline": order.get("route_polyline") or (partner_doc or {}).get("journey_polyline"),
        "tracking_events": order.get("tracking_events", [])[-6:],
    }


# ============================================================
# Public downloads (marketing collateral)
# ============================================================
@api.get("/downloads/pitch-deck")
async def download_pitch_deck():
    """Serve the Curry & Co. sales pitch deck PDF for download.

    Public — no auth required so it can be shared with prospects directly.
    """
    from pathlib import Path
    pdf_path = Path("/app/exports/CurryCo_Sales_Pitch.pdf")
    if not pdf_path.exists():
        raise HTTPException(404, "Pitch deck not generated yet.")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename="CurryCo_Sales_Pitch.pdf",
    )


@api.get("/legal/privacy")
async def public_privacy_policy():
    """Publicly-hosted Privacy Policy + Terms — used by Apple/Google store metadata."""
    from pathlib import Path
    p = Path("/app/exports/privacy.html")
    if not p.exists():
        raise HTTPException(404, "Privacy policy not found.")
    return FileResponse(path=str(p), media_type="text/html")


@api.get("/health/web-bundle")
async def health_web_bundle():
    """Diagnostic endpoint for the SPA web-bundle deploy status.

    Lets us inspect production state without shell:
      * present:   is any dist/index.html available?
      * source:    which of the two candidate dirs is being served
      * dist_size: total bytes of the served bundle
      * frontend_source_shipped: was /app/frontend/package.json included in the
                                 production image (i.e. can we self-build)?
    """
    import shutil as _sh
    served = _resolve_web_dist()
    size = 0
    if served and served.exists():
        for p in served.rglob("*"):
            if p.is_file():
                try:
                    size += p.stat().st_size
                except Exception:
                    pass
    return {
        "present": served is not None,
        "source": str(served) if served else None,
        "prod_dir_exists": _WEB_DIST_PROD.exists(),
        "prod_dir_has_index": (_WEB_DIST_PROD / "index.html").exists(),
        "preview_dir_exists": _WEB_DIST_PREVIEW.exists(),
        "preview_dir_has_index": (_WEB_DIST_PREVIEW / "index.html").exists(),
        "dist_size_bytes": size,
        "frontend_source_shipped": Path("/app/frontend/package.json").exists(),
        "npx_available": _sh.which("npx") is not None,
        "yarn_available": _sh.which("yarn") is not None,
    }


# --- Register router
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------
# SPA static mounts + catch-all fallback.
# MUST be registered AFTER include_router(api) so that /api/* routes
# resolve first — anything else falls back to index.html which lets Expo
# Router handle client-side routing (/admin, /customer, /order/[id] etc.).
# ---------------------------------------------------------------

def _try_build_web_bundle() -> bool:
    """Ensure /app/backend/web_dist/ (or the preview alt) has a working Expo
    web bundle. If NEITHER location has index.html, attempt to build in
    /app/frontend/ and then MIRROR the result into /app/backend/web_dist/ so
    the next production deploy will ship the bundle inside the backend image.

    Returns True if a web bundle is available after this call.
    """
    import subprocess, shutil

    # Fast path — anything already usable?
    if _resolve_web_dist():
        # Make sure production copy exists (mirror if only preview has it).
        preview = _WEB_DIST_PREVIEW / "index.html"
        prod = _WEB_DIST_PROD / "index.html"
        if preview.exists() and not prod.exists():
            try:
                if _WEB_DIST_PROD.exists():
                    shutil.rmtree(_WEB_DIST_PROD)
                shutil.copytree(_WEB_DIST_PREVIEW, _WEB_DIST_PROD)
                log.info(f"[web-build] mirrored preview dist -> {_WEB_DIST_PROD}")
            except Exception as e:
                log.warning(f"[web-build] mirror to prod dir failed: {e}")
        return True

    log.info(f"[web-build] no dist at {_WEB_DIST_PROD} or {_WEB_DIST_PREVIEW} — attempting to build")

    frontend_dir = Path("/app/frontend")
    if not (frontend_dir / "package.json").exists():
        log.warning(
            f"[web-build] frontend source not present at {frontend_dir} — "
            "cannot build web bundle in this container. "
            "Ship /app/backend/web_dist/ pre-built with the image instead."
        )
        return False

    npx = shutil.which("npx") or shutil.which("yarn") or shutil.which("npm")
    if not npx:
        log.warning("[web-build] npx/yarn/npm not on PATH; cannot build")
        return False

    if not (frontend_dir / "node_modules").exists():
        yarn = shutil.which("yarn")
        if yarn:
            log.info("[web-build] node_modules missing — running yarn install …")
            try:
                subprocess.run(
                    [yarn, "install", "--frozen-lockfile", "--production=false"],
                    cwd=str(frontend_dir),
                    timeout=180, check=False,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={**os.environ, "CI": "1", "SKIP_PREINSTALL_GUARD": "1"},
                )
            except Exception as e:
                log.warning(f"[web-build] yarn install failed: {e}")

    try:
        cmd = [npx, "expo", "export", "--platform", "web", "--output-dir", "dist"]
        if npx.endswith("yarn"):
            cmd = [npx, "run", "build:web"]
        log.info(f"[web-build] running: {' '.join(cmd)} (cwd={frontend_dir})")
        proc = subprocess.run(
            cmd, cwd=str(frontend_dir), timeout=240, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "APP_VARIANT": os.environ.get("APP_VARIANT", "customer"), "CI": "1"},
        )
        tail = (proc.stdout[-800:] + proc.stderr[-800:]).decode(errors="replace")
        log.info(f"[web-build] exit={proc.returncode}, tail: {tail}")
    except subprocess.TimeoutExpired:
        log.error("[web-build] expo export timed out after 240s")
    except Exception as e:
        log.error(f"[web-build] exception: {e}")

    # Mirror preview → prod dir if build succeeded.
    if (_WEB_DIST_PREVIEW / "index.html").exists():
        try:
            if _WEB_DIST_PROD.exists():
                shutil.rmtree(_WEB_DIST_PROD)
            shutil.copytree(_WEB_DIST_PREVIEW, _WEB_DIST_PROD)
            log.info(f"[web-build] mirrored to {_WEB_DIST_PROD}")
        except Exception as e:
            log.warning(f"[web-build] mirror step failed: {e}")

    ok = _resolve_web_dist() is not None
    log.info(f"[web-build] result: dist available={ok}")
    return ok


# Fire the build check ONCE at module import.
_try_build_web_bundle()

WEB_DIST = _resolve_web_dist() or _WEB_DIST_PROD  # re-resolve after build
_WEB_DIST_PRESENT = _resolve_web_dist() is not None
log.info(f"[web-build] serving SPA={_WEB_DIST_PRESENT} from {WEB_DIST}")

# ---------------------------------------------------------------
# Icon-font safety net (MUST be registered BEFORE the /assets mount below).
# The production deploy image strips `node_modules` directories, so the
# Ionicons glyph font that Expo emits under
#   assets/node_modules/@react-native-vector-icons/ionicons/fonts/Ionicons.<hash>.ttf
# gets dropped and that URL 404s → every icon renders as a blank box.
# The icon library hardcodes this URL, so we serve it from a committed copy
# that lives OUTSIDE node_modules and therefore survives deployment.
# ---------------------------------------------------------------
_ICON_FONT_FALLBACK = Path("/app/backend/static/Ionicons.ttf")

@app.get("/assets/node_modules/@react-native-vector-icons/ionicons/fonts/{fname}", include_in_schema=False)
async def _ionicons_font(fname: str):
    for p in (
        WEB_DIST / "assets/node_modules/@react-native-vector-icons/ionicons/fonts" / fname,
        _ICON_FONT_FALLBACK,
    ):
        if p.exists():
            return FileResponse(str(p), media_type="font/ttf", headers={
                "Cache-Control": "public, max-age=31536000, immutable",
            })
    raise HTTPException(404)

if _WEB_DIST_PRESENT:
    # Serve the JS bundle & static assets folders that Expo emits.
    if (WEB_DIST / "_expo").exists():
        app.mount("/_expo", StaticFiles(directory=str(WEB_DIST / "_expo")), name="expo-static")
    if (WEB_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="web-assets")


_INDEX_HTML = WEB_DIST / "index.html"
_FAVICON = WEB_DIST / "favicon.ico"


@app.get("/favicon.ico", include_in_schema=False)
async def _favicon():
    if _FAVICON.exists():
        return FileResponse(str(_FAVICON))
    raise HTTPException(404)


# Diagnostic page shown when the Expo web bundle isn't shipped with the deploy.
# This is a fallback so the user gets a clear message instead of a bare JSON 404.
_NO_WEB_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{BRAND_NAME} — Web Bundle Missing</title>
<style>body{font-family:-apple-system,sans-serif;max-width:640px;margin:60px auto;padding:20px;line-height:1.6;color:#2A1D18}
h1{color:#B14F36}code{background:#f4efe9;padding:2px 6px;border-radius:4px}
.card{background:#FFF7E6;border:1px solid #FCD9A5;padding:16px;border-radius:8px;margin:20px 0}
a{color:#B14F36}
</style></head>
<body>
<h1>🛠  Web bundle not deployed</h1>
<p>The FastAPI backend is running (see <a href="/docs">/docs</a> for the API), but the Expo web bundle
<code>/app/frontend/dist/</code> was not included in this Kubernetes deployment.</p>

<div class="card">
<strong>What's missing:</strong> the pre-built <code>dist/index.html</code>, <code>_expo/static/*</code> and
<code>assets/*</code> files that let the admin webapp run in the browser.
</div>

<p><strong>Working URLs on this deploy:</strong></p>
<ul>
  <li><a href="/health">/health</a> — Kubernetes probe (should return JSON <code>{"status":"ok"}</code>)</li>
  <li><a href="/docs">/docs</a> — API Swagger docs</li>
  <li><code>/api/menu/current</code>, <code>/api/admin/login</code>, etc. — all API routes work</li>
</ul>

<p><strong>Fix path:</strong> the deploy pipeline needs to include the pre-built <code>/app/frontend/dist/</code>
directory in the production container.  Contact <a href="mailto:support@emergent.sh">support@emergent.sh</a>
with your job ID and this message.</p>

<p style="color:#7F6E68;font-size:13px">Requested path: <code id="p"></code></p>
<script>document.getElementById('p').textContent = window.location.pathname;</script>
</body></html>"""


# Catch-all: anything that isn't /api/* → served from the web bundle (or SPA fallback).
# This is how single-page apps (SPAs) handle client-side routing — the client
# JS reads the URL and mounts the correct screen (admin, customer tabs, etc.).
# Registered UNCONDITIONALLY so that even without dist/ we give the user a
# helpful diagnostic page instead of a bare FastAPI JSON 404.
#
# IMPORTANT: We intentionally DO NOT exclude /_expo/* and /assets/* here.
# StaticFiles mounts above take precedence when present, but if they weren't
# registered (e.g. dist wasn't materialized when the module first imported),
# we fall through to disk-serving here so icon fonts / images still work.
@app.get("/{full_path:path}", include_in_schema=False)
async def _spa_fallback(full_path: str):
    # Reserved backend-only prefixes MUST NOT be intercepted here.
    if full_path.startswith(("api/", "api", "docs", "openapi.json", "redoc", "health", "healthz")):
        raise HTTPException(404)

    # Try to serve any static file directly if it exists under dist/.
    # This is a safety net for /_expo/* and /assets/* in case the StaticFiles
    # mounts didn't register (e.g. the folder was created after startup).
    web_root = _resolve_web_dist() or WEB_DIST
    if web_root and web_root.exists():
        candidate = web_root / full_path
        if candidate.is_file():
            # Set a long cache header for hashed static assets (JS bundles + fonts + images).
            headers = {}
            if any(s in full_path for s in ("_expo/static/", "assets/")) and "." in full_path.rsplit("/", 1)[-1]:
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(str(candidate), headers=headers)
        # Non-file (SPA route like /admin/menu) → serve index.html with no-cache
        # so the browser always picks up the newest JS bundle hash after a deploy.
        index_html = web_root / "index.html"
        if index_html.exists():
            return FileResponse(str(index_html), headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            })

    # No bundle at all — show the diagnostic page.
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=_NO_WEB_HTML, status_code=200)


@app.on_event("startup")
async def _startup():
    try:
        # Migrate: any legacy docs with email:null cause DuplicateKeyError on new
        # partial-unique index. Strip the null field before recreating the index.
        try:
            await db.users.update_many({"email": None}, {"$unset": {"email": 1}})
        except Exception as _mig_err:
            logger.warning(f"user email null-cleanup skipped: {_mig_err}")

        # Recreate `email` index as partial-unique (only enforces uniqueness when
        # email is a real string) — allows phone-only customers created via Admin
        # New Order flow without collisions.
        try:
            existing_idx = await db.users.index_information()
            if "email_1" in existing_idx and not existing_idx["email_1"].get("partialFilterExpression"):
                await db.users.drop_index("email_1")
        except Exception as _drop_err:
            logger.warning(f"user email index drop skipped: {_drop_err}")

        await db.users.create_index(
            "email",
            unique=True,
            partialFilterExpression={"email": {"$type": "string"}},
            name="email_1",
        )
        await db.users.create_index("user_id", unique=True)
        await db.user_sessions.create_index("session_token", unique=True)
        await db.user_sessions.create_index("user_id")
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
        await db.otp_challenges.create_index("email", unique=True)
        await db.otp_challenges.create_index("expires_at", expireAfterSeconds=0)
        await db.password_resets.create_index("token_hash", unique=True)
        await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
        await db.coupons.create_index("code", unique=True)
        await db.coupons.create_index("owner_user_id")
        await db.coupon_redemptions.create_index([("code", 1), ("user_id", 1)])
        await db.coupon_redemptions.create_index("order_id")
        await db.points_ledger.create_index([("user_id", 1), ("ts", -1)])
        await db.weekly_menus.create_index("week_start", unique=True)
        await db.orders.create_index("order_id", unique=True)
        await db.orders.create_index("user_id")
        await db.payment_transactions.create_index("session_id", unique=True)
        await db.catering_packages.create_index("package_id", unique=True)
        await db.admins.create_index("email", unique=True)
        await db.master_menu.create_index("item_id", unique=True)
        await db.master_menu.create_index([("category", 1), ("cuisine", 1)])
        await db.business_settings.create_index("key", unique=True)
        # Export download tokens: unique-token lookup only. Expiration is
        # enforced LAZILY on read/create instead of via a MongoDB TTL — this
        # keeps startup non-destructive (no auto-hard-delete of user data by
        # the DB engine on cold-boot in production).
        # Migration: if an older deploy created the TTL variant of this index,
        # drop it so the engine stops silently reaping records.
        try:
            _existing_idx = await db.export_files.index_information()
            _exp_idx = _existing_idx.get("expires_at_1") or {}
            if _exp_idx.get("expireAfterSeconds") is not None:
                await db.export_files.drop_index("expires_at_1")
        except Exception as _drop_ttl_err:
            log.warning(f"export_files TTL drop skipped: {_drop_ttl_err}")
        await db.export_files.create_index("token", unique=True)
        await db.export_files.create_index("expires_at")
        # seed default admin (idempotent — password hashed in Python to avoid $ expansion)
        existing = await db.admins.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0})
        if not existing:
            await db.admins.insert_one({
                "email": ADMIN_EMAIL.lower(),
                "password_hash": _pwd.hash(ADMIN_PASSWORD),
                "created_at": datetime.now(timezone.utc),
            })
            log.info(f"seeded default admin: {ADMIN_EMAIL}")

        # seed App Store / Play Store REVIEWER test account (idempotent).
        # These credentials are used ONLY by Apple/Google reviewers to log in
        # during app review. Configure via env vars — if REVIEWER_EMAIL is unset,
        # skip seeding entirely (so production deploys can turn this off).
        reviewer_email = os.environ.get("REVIEWER_EMAIL", "").strip().lower()
        reviewer_pw   = os.environ.get("REVIEWER_PASSWORD", "").strip()
        if reviewer_email and reviewer_pw:
            existing_r = await db.users.find_one({"email": reviewer_email}, {"_id": 0})
            if not existing_r:
                await db.users.insert_one({
                    "user_id": f"user_reviewer_{uuid.uuid4().hex[:6]}",
                    "email": reviewer_email,
                    "name": "App Reviewer",
                    "phone": "+14165550100",
                    "password_hash": _pwd.hash(reviewer_pw),
                    "provider": "password",
                    "loyalty_points": 500,
                    "created_at": datetime.now(timezone.utc),
                    "is_reviewer_account": True,
                })
                log.info(f"seeded reviewer test account: {reviewer_email}")
        log.info("indexes ready")
    except Exception as e:
        log.warning(f"index setup: {e}")

    # Kick off the Suparna Dey platform phone-home poller. Fires every N
    # seconds (default 300) to fetch tenant + subscription enforcement flags.
    # No-op when brand.json has no `platform.tenant_id`, so preview/dev boots
    # cleanly without a control-plane URL.
    try:
        from platform_client import start_platform_poller
        start_platform_poller()
    except Exception as _plat_err:
        log.warning(f"platform poller start skipped: {_plat_err}")


@app.on_event("shutdown")
async def _shutdown():
    from platform_client import stop_platform_poller
    await stop_platform_poller()
    await _push_client.aclose()
    # The old Motor client close() lived here; the Postgres pool is closed
    # instead (no-op when the pool was never created).
    await db.close()
