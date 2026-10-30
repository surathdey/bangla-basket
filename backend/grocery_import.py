"""
Grocery catalog import helpers.

Transforms a Shopify-style products.json feed (the tenant's own store export)
into our GroceryItem shape, deriving a human category from the product title,
and a display "unit" (weight/pack) hint. Used by:
  * seed_grocery.py           (one-time initial load)
  * POST /api/admin/grocery/import-from-store  (admin bulk re-import)
"""
import re
import html
import uuid
from typing import List, Dict, Any

STORE_PRODUCTS_URL = "https://chefsrhere.com/products.json"

# Ordered category rules — first keyword match wins.
CATEGORY_RULES = [
    ("Rice & Grains", ["rice", "poha", "chira", "sooji", "farina", "atop", "basmati", "chinigura", "muri", "flattened", "puffed"]),
    ("Flour & Baking", ["flour", "atta", "maida", "besan", "gram flour"]),
    ("Lentils & Pulses", ["dal", "daal", "lentil", "moong", "masoor", "chola", "chickpea", "mung", "pulse"]),
    ("Fish & Seafood", ["fish", "hilsa", "ilish", "rui", "rohu", "katla", "pabda", "prawn", "shrimp", "chingri", "pomfret", "tilapia", "shutki", "crab", "koi", "magur", "shol", "bhetki"]),
    ("Meat & Poultry", ["goat", "mutton", "lamb", "chicken", "beef", "kosha", "keema", "meat"]),
    ("Sweets & Desserts", ["laddu", "rosgolla", "rasgulla", "roshmalai", "rasmalai", "sandesh", "mishti", "sweet", "kalojam", "gulab", "jamun", "halwa", "payesh", "kheer", "chumchum", "pantua"]),
    ("Snacks & Namkeen", ["chanachur", "namkeen", "biscuit", "cookie", "chips", "snack", "nimki", "jhalmuri", "papad", "singara", "samosa"]),
    ("Spices & Masala", ["masala", "spice", "turmeric", "haldi", "chili", "chilli", "cumin", "jeera", "coriander", "dhania", "garam", "panch phoron", "paanch", "powder", "seeds", "bay leaf", "cardamom", "clove"]),
    ("Oil & Ghee", ["mustard oil", "oil", "ghee", "vanaspati"]),
    ("Pickles & Chutney", ["pickle", "achar", "chutney"]),
    ("Tea, Coffee & Beverages", ["tea", "coffee", "juice", "drink", "sharbat", "beverage", "borhani", "lassi"]),
    ("Frozen & Ready to Eat", ["frozen", "paratha", "roti", "luchi", "ready", "spring roll", "momo", "cutlet", "singhara"]),
    ("Dairy & Paneer", ["paneer", "milk", "yogurt", "doi", "curd", "cheese", "butter", "cream"]),
    ("Vegetables & Produce", ["potato", "onion", "tomato", "ginger", "garlic", "chili green", "leafy", "shak", "gourd", "brinjal", "eggplant", "okra", "vegetable", "lemon", "coriander leaves"]),
    ("Meal Combos & Plans", ["combo", "meal plan", "weekly", "thali", "platter", "feast"]),
    ("Beauty & Personal Care", ["soap", "shampoo", "cream", "lotion", "oil hair", "toothpaste", "beauty", "personal care", "henna", "mehendi", "sindoor", "cosmetic", "face wash"]),
]

_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s?(?:lb|lbs|kg|kgs|g|gm|gms|gram|grams|oz|ml|l|litre|liter|pcs?|pieces?|pack|box|serving|people|person|plan))",
    re.IGNORECASE,
)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def categorize(title: str, tags=None) -> str:
    t = (title or "").lower()
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw in t:
                return cat
    # tag fallback
    for tg in (tags or []):
        tgl = str(tg).lower()
        for cat, kws in CATEGORY_RULES:
            if any(kw in tgl for kw in kws):
                return cat
    return "Grocery & Pantry"


def extract_unit(title: str) -> str:
    m = _UNIT_RE.search(title or "")
    return m.group(1).strip() if m else ""


def transform_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Map one Shopify product dict → GroceryItem dict (no _id)."""
    title = (p.get("title") or "").strip()
    variants = p.get("variants") or [{}]
    v = variants[0]
    price = float(v.get("price") or 0)
    compare = float(v.get("compare_at_price") or 0) if v.get("compare_at_price") else 0
    images = [img.get("src") for img in (p.get("images") or []) if img.get("src")]
    tags = p.get("tags") or []
    if isinstance(tags, str):
        tags = [x.strip() for x in tags.split(",") if x.strip()]
    desc = _strip_html(p.get("body_html") or "")
    if len(desc) > 300:
        desc = desc[:297].rsplit(" ", 1)[0] + "…"
    in_stock = any(bool(vv.get("available")) for vv in variants) if variants else True
    source_id = str(p.get("id") or p.get("handle") or title)
    return {
        "item_id": f"gr_{uuid.uuid4().hex[:12]}",
        "title": title,
        "handle": p.get("handle") or "",
        "description": desc,
        "category": categorize(title, tags),
        "price_cents": int(round(price * 100)),
        "compare_at_cents": int(round(compare * 100)),
        "unit": extract_unit(title),
        "image_url": images[0] if images else "",
        "images": images[:6],
        "vendor": p.get("vendor") or "",
        "tags": tags[:12],
        "in_stock": in_stock,
        "is_active": True,
        "is_featured": False,
        "sort_order": 0,
        "source_id": source_id,
    }


def fetch_store_products(url: str = STORE_PRODUCTS_URL, max_pages: int = 20) -> List[Dict[str, Any]]:
    """Fetch all pages of a Shopify products.json feed (synchronous)."""
    import urllib.request
    import json as _json
    out: List[Dict[str, Any]] = []
    for pg in range(1, max_pages + 1):
        req = urllib.request.Request(
            f"{url}?limit=250&page={pg}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        products = data.get("products", [])
        if not products:
            break
        out.extend(products)
    return out


def build_grocery_docs(url: str = STORE_PRODUCTS_URL) -> List[Dict[str, Any]]:
    raw = fetch_store_products(url)
    docs = []
    for p in raw:
        d = transform_product(p)
        if d["title"] and d["price_cents"] > 0:
            docs.append(d)
    return docs
