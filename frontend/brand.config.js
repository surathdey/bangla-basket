/**
 * ============================================================
 *  BRAND CONFIG — the ONE file you edit to rebrand this app.
 * ============================================================
 *
 *  To spin up a new restaurant (e.g. "Jomidari") from this template:
 *    1. Fork the repo on GitHub
 *    2. Edit THIS file — change every value below to match your brand
 *    3. Drop new logo assets into `assets/brand/` (keep filenames the same)
 *    4. Commit + deploy in Emergent
 *
 *  Nothing else in the codebase should be edited for a rebrand. If you find
 *  yourself hand-editing UI strings or colors elsewhere, that value belongs
 *  HERE — please add it and reference it instead.
 *
 *  This file is consumed by:
 *    • `app.config.js`         → app name, bundle ID, package, deep-link scheme
 *    • `src/brand.ts`          → runtime brand context (colors, copy, contact)
 *    • `backend/brand.py`      → server-side name/email/phone in receipts
 *
 *  Note: this file uses CommonJS so it can be `require()`'d by app.config.js
 *  AND imported from TypeScript via a companion type re-export.
 * ============================================================
 */

/** @type {import('./brand.types').BrandConfig} */
const brand = {
  // ─── Identity ────────────────────────────────────────────
  key: "bongconnekt",                    // slug used in package IDs + folders
  name: "Bangla Basket",                 // public-facing brand name
  legalName: "Bangla Basket",            // for receipts + T&Cs
  tagline: "Bengali Grocery & Meals · Delivery at Your Doorstep",

  // ─── Colors (all UI palette flows from here) ─────────────
  //   Auto-derived from logo-square.png (Pillow quantize).
  colors: {
    primary:     "#011838",              // deep navy (BONGCONNEKT text + Howrah bridge)
    primaryDark: "#01132D",              // pressed/hover (primary × 0.8)
    secondary:   "#917F52",              // muted gold accent (skyline highlights)
    accent:      "#2F4F4F",              // dark teal (info states)
  },

  // ─── Contact + support ───────────────────────────────────
  support: {
    email: "support@bongconnekt.ca",
    phone: "+1-416-555-0100",
    website: "https://bongconnekt.ca",
    privacyUrl: "https://bongconnekt.ca/privacy",
    termsUrl:   "https://bongconnekt.ca/terms",
  },

  // ─── Regional / operational ──────────────────────────────
  region: {
    country: "CA",
    currency: "CAD",
    currencySymbol: "$",                 // shown in checkout
    timezone: "America/Toronto",
    defaultCity: "Toronto",
    serviceArea: "the Greater Toronto Area",
  },

  // ─── Native app metadata (per platform) ──────────────────
  //   These are consumed by app.config.js. Once shipped they are IMMUTABLE.
  native: {
    customer: {
      bundleIdentifier: "com.bongconnekt.customer",     // iOS
      androidPackage:   "com.bongconnekt.customer",     // Android
      deepLinkScheme:   "bongconnekt",                  // bongconnekt://order/xyz
    },
    delivery: {
      bundleIdentifier: "com.bongconnekt.delivery",
      androidPackage:   "com.bongconnekt.delivery",
      deepLinkScheme:   "bongconnektdelivery",
    },
  },

  // ─── Copy overrides (short strings shown in UI) ──────────
  copy: {
    aboutBlurb:     "Bangla Basket — authentic Bengali groceries & meals, delivered fresh across the Greater Toronto Area.",
    deleteWarning:  "This permanently removes your profile, order history, addresses, and loyalty points from Bangla Basket. This cannot be undone.",
    deleteFarewell: "Your data has been removed. Thanks for trying Bangla Basket.",
    orderTagline:   "Bengali grocery & meals, delivered to your doorstep.",
  },

  // ─── Asset paths (relative to /assets/brand/) ────────────
  //   Keep the filenames identical when rebranding — just replace the pixels.
  assets: {
    logo:            "./assets/brand/logo.png",
    logoSquare:      "./assets/brand/logo-square.png",
    splash:          "./assets/brand/splash.png",
    notificationIcon:"./assets/brand/notification-icon.png",
    adaptiveIcon:    "./assets/brand/adaptive-icon.png",
  },

  // ─── Platform tenant registration (Phase 2/3 — Suparna Dey Platform) ─
  //   These wire this restaurant into the central SaaS platform.
  platform: {
    // Empty until this tenant is registered in the Super Admin portal.
    // In preview these can stay empty — the phone-home poller short-circuits
    // and no platform enforcement gates apply.
    tenantId:     "tnt_264dfe34083a",
    apiKey:       process.env.PLATFORM_TENANT_API_KEY || "",
    statusUrl:    "https://control-plane-11.preview.emergentagent.com/api/tenant/status",
  },
};

module.exports = brand;
