from __future__ import annotations

import math
import re


# These are deliberately curated observations, not claims of checkout-time truth.
# Retailer pages and prices are kept with each product so every automatic match
# remains explainable and replaceable by a future policy-compliant live adapter.
COLES_PRICE_CATALOG = {
    "milk": {
        "price": 1.85,
        "source": "Coles Australian Full Cream Long Life Milk 1L",
        "url": "https://www.coles.com.au/product/coles-australian-full-cream-long-life-milk-1l-7667368",
        "aliases": ("milk", "full cream milk", "long life milk", "full cream long life milk"),
        "note": "Coles brand selected: 1L long-life full-cream milk; online price observed and location-sensitive.",
    },
    "eggs": {
        "price": 5.70,
        "source": "Coles Cage Free Eggs 12 Pack 700g",
        "url": "https://www.coles.com.au/product/coles-cage-free-eggs-12-pack-700g-5178633",
        "aliases": ("eggs", "egg", "cage free eggs"),
        "note": "Coles brand selected: 12-pack; online price observed and location-sensitive.",
    },
    "oat milk": {
        "price": 1.80,
        "source": "Coles Unsweetened Oat Milk 1L",
        "url": "https://www.coles.com.au/product/coles-unsweetened-oat-milk-1l-6337674",
        "aliases": ("oat milk", "unsweetened oat milk"),
        "note": "Coles brand selected: 1L pack; online price observed and location-sensitive.",
    },
    "bananas": {
        "price": 0.83,
        "source": "Coles Bananas approx. 170g",
        "url": "https://www.coles.com.au/product/coles-bananas-approx.-170g-409499",
        "aliases": ("bananas", "banana"),
        "note": "Coles product selected; final price is weight-based and location-sensitive.",
    },
    "bread": {
        "price": 3.30,
        "source": "Coles Bakery Wholemeal Sandwich Loaf 680g",
        "url": "https://www.coles.com.au/product/coles-bakery-wholemeal-sandwich-loaf-680g-8145620",
        "aliases": ("bread", "wholemeal bread", "sandwich loaf"),
        "note": "Coles product selected: wholemeal 680g loaf; choose another product if a different bread is intended.",
    },
    "mince": {
        "price": 9.00,
        "source": "Coles No Added Hormone Beef Regular Mince 500g",
        "url": "https://www.coles.com.au/product/coles-no-added-hormone-beef-regular-mince-500g-9012814",
        "aliases": ("mince", "beef mince", "beef mince meat"),
        "note": "Coles product selected: regular beef mince 500g; online price observed and location-sensitive.",
    },
    "chicken breast": {
        "price": 8.70,
        "source": "Coles RSPCA Approved Chicken Breast Fillets Small Pack approx. 600g",
        "url": "https://www.coles.com.au/product/coles-rspca-approved-chicken-breast-fillets-small-pack-approx.-600g-2263168",
        "aliases": ("chicken breast", "chicken breast fillets", "breast fillets"),
        "note": "Closest Coles plain chicken-breast pack selected: approximate 600g small pack; final price is weight-based and location-sensitive.",
    },
    "coke zero 2l": {
        "price": 4.00,
        "source": "Coca-Cola Zero Sugar Soft Drink Bottle 2L",
        "url": "https://www.coles.com.au/product/coca-cola-zero-sugar-soft-drink-bottle-2l-3029790",
        "aliases": ("2l coke zero", "coke zero 2l", "coca cola zero sugar 2l", "coke zero", "coke zero sugar"),
        "comparison_family": "coke zero",
        "size_quantity_safe": True,
        "note": "Exact 2L Coca-Cola Zero Sugar bottle selected; do not substitute a different size or diet variant. Price is location-sensitive.",
    },
    "franks hot sauce": {
        "price": 3.50,
        "source": "Frank's Redhot Original Sauce 148mL",
        "url": "https://www.coles.com.au/product/frank's-redhot-original-sauce-148ml-1957139",
        "aliases": ("franks hot sauce", "frank's hot sauce", "franks redhot", "frank's redhot", "franks redhot original", "frank's redhot original"),
        "note": "Standard Frank's RedHot Original Cayenne Pepper Sauce selected: 148mL; Buffalo and Xtra Hot variants are not substituted. Price is location-sensitive.",
    },
    "hotdogs": {
        "price": 5.00,
        "source": "The Deli Thin Frankfurts 500g",
        "url": "https://www.coles.com.au/product/the-deli-thin-frankfurts-500g-3566100",
        "aliases": ("hotdogs", "hot dogs", "frankfurts", "franks", "hot dog sausages"),
        "note": "Plain The Deli Thin Frankfurts selected for generic hotdogs: 500g; check the pack label for allergens and dietary requirements.",
    },
    "hotdog buns": {
        "price": 2.60,
        "source": "Coles Simply Hot Dog Rolls 450g",
        "url": "https://www.coles.com.au/product/coles-simply-hot-dog-rolls-450g-5696762",
        "aliases": ("hotdog buns", "hot dog buns", "hot dog rolls", "hotdog rolls"),
        "note": "Coles Simply Hot Dog Rolls selected: 450g, six rolls; price and availability are location-sensitive.",
    },
    "tortillas": {
        "price": 3.75,
        "source": "Coles Street Tortilla Wraps 10 Pack 280g",
        "url": "https://www.coles.com.au/product/coles-street-tortilla-wraps-10-pack-280g-3478997",
        "aliases": ("tortillas", "tortilla", "wraps", "tortilla wraps"),
        "note": "Coles product selected: 10-pack; online price observed and location-sensitive.",
    },
    "white pepper": {
        "price": 5.00,
        "source": "Coles White Pepper 100g",
        "url": "https://www.coles.com.au/product/coles-white-pepper-100g-9044719",
        "aliases": ("white pepper", "coles white pepper", "coles brand white pepper", "coles pepper white"),
        "note": "Coles brand selected: ground white pepper 100g; online price observed and location-sensitive.",
    },
    "potatoes": {
        "price": 8.90,
        "source": "Coles I'm Perfect Potatoes Imperfect 4kg",
        "url": "https://www.coles.com.au/product/coles-i'm-perfect-potatoes-imperfect-4kg-9852032",
        "aliases": ("potatoes", "potato", "im perfect potatoes", "imperfect potatoes", "i m perfect potatoes"),
        "note": "Coles I'm Perfect product selected: 4kg pack; online price observed and location-sensitive.",
    },
    "sweet potatoes": {
        "price": 3.90,
        "source": "Coles I'm Perfect Sweet Potato 1.5kg",
        "url": "https://www.coles.com.au/product/coles-i'm-perfect-sweet-potato-1.5kg-3616751",
        "aliases": ("sweet potatoes", "sweet potato", "im perfect sweet potatoes", "imperfect sweet potatoes", "i m perfect sweet potatoes"),
        "note": "Coles I'm Perfect product selected: 1.5kg pack; online price observed and location-sensitive.",
    },
    "carrots": {
        "price": 2.60,
        "source": "Coles I'm Perfect Carrots Prepacked 1.5kg",
        "url": "https://www.coles.com.au/product/coles-i'm-perfect-carrots-prepacked-1.5kg-3609392",
        "aliases": ("carrots", "carrot", "im perfect carrots", "imperfect carrots", "i m perfect carrots"),
        "note": "Coles I'm Perfect product selected: prepacked 1.5kg; online price observed and location-sensitive.",
    },
    "cannellini beans": {
        "price": 0.95,
        "source": "Coles Simply Cannellini Beans 420g",
        "url": "https://www.coles.com.au/product/coles-simply-cannellini-beans-420g-4774088",
        "aliases": ("cannellini beans", "cannellini bean"),
        "note": "Coles Simply product selected: 420g can; requested quantities and can size may vary.",
    },
    "celery": {
        "price": 4.00,
        "source": "Coles Celery Bunch 1 Each",
        "url": "https://www.coles.com.au/product/coles-celery-bunch-1-each-4845732",
        "aliases": ("celery", "celery stalk", "celery stalks"),
        "note": "Coles celery bunch selected for stalk requests; weight and final price are location-sensitive.",
    },
    "diced tomatoes": {
        "price": 1.30,
        "source": "Coles Australian Diced Tomatoes 400g",
        "url": "https://www.coles.com.au/product/coles-australian-diced-tomatoes-400g-4457019",
        "aliases": ("diced tomatoes", "diced tomato", "chopped tomatoes"),
        "note": "Coles Australian product selected: 400g can; online price observed and location-sensitive.",
    },
    "chicken stock": {
        "price": 1.90,
        "source": "Coles Liquid Real Stock Chicken 1L",
        "url": "https://www.coles.com.au/product/coles-liquid-real-stock-chicken-1l-7152073",
        "aliases": ("chicken stock", "chicken broth"),
        "note": "Coles liquid stock selected: 1L; confirm dietary and salt requirements before purchase.",
    },
    "kale": {
        "price": 3.30,
        "source": "Coles Chopped Kale 140g",
        "url": "https://www.coles.com.au/product/coles-chopped-kale-140g-2674606",
        "aliases": ("kale", "chopped kale"),
        "note": "Coles chopped kale selected: 140g pack; requested quantities and availability may vary.",
    },
    "lemon": {
        "price": 1.60,
        "source": "Coles Lemons 1 Each",
        "url": "https://www.coles.com.au/product/coles-lemons-1-each-5318302",
        "aliases": ("lemon", "lemons"),
        "note": "Coles lemon selected: 1 each; final price and weight are location-sensitive.",
    },
    "popping corn kernels": {
        "price": 1.65,
        "source": "Coles Popping Corn Kernels 400g",
        "url": "https://www.coles.com.au/product/coles-popping-corn-kernels-400g-5374675",
        "aliases": ("popping corn kernels", "popcorn kernels", "coles popping corn kernels"),
        "note": "Coles product selected: 400g kernels; observed online price is location-sensitive.",
    },
    "vegetable oil": {
        "price": 3.50,
        "source": "Coles Simply Vegetable Oil 4L",
        "url": "https://www.coles.com.au/product/coles-simply-vegetable-oil-4l-8211586",
        "aliases": ("vegetable oil", "simply vegetable oil", "coles simply vegetable oil"),
        "note": "Coles Simply product selected: 4L vegetable oil; observed online price is location-sensitive.",
    },
    "table spread": {
        "price": 2.70,
        "source": "Coles Simply Table Spread 1kg",
        "url": "https://www.coles.com.au/product/coles-simply-table-spread-1kg-5428639",
        "aliases": ("table spread", "simply table spread", "coles simply table spread"),
        "note": "Coles Simply product selected: 1kg table spread; observed online price is location-sensitive.",
    },
    "beef strips": {
        "price": 9.95,
        "source": "Coles Beef Stir Fry 500g",
        "url": "https://www.coles.com.au/product/coles-beef-stir-fry-500g-9990965",
        "aliases": ("beef strips", "beef stir fry", "coles beef stir fry"),
        "note": "Closest Coles beef-strip cut selected at 500g; verify the cut and location-sensitive price in store.",
    },
    "broccoli": {
        "price": 1.70,
        "source": "Coles Broccoli Medium approx. 340g",
        "url": "https://www.coles.com.au/product/coles-broccoli-medium-approx.-340g-407755",
        "aliases": ("broccoli", "medium broccoli"),
        "note": "Coles medium broccoli selected; approximate weight and price are location-sensitive.",
    },
    "brown onion": {
        "price": 4.00,
        "source": "Coles Brown Onions 1kg",
        "url": "https://www.coles.com.au/product/coles-brown-onions-1kg-4803991",
        "aliases": ("brown onion", "brown onions", "onion"),
        "note": "Coles brown onions selected: 1kg pack; price is location-sensitive.",
    },
    "garlic": {
        "price": 2.10,
        "source": "Coles Australian Garlic Loose approx. 60g",
        "url": "https://www.coles.com.au/product/coles-australian-garlic-loose-approx.-60g-6105715",
        "aliases": ("garlic", "fresh garlic", "australian garlic"),
        "note": "Coles Australian loose garlic selected; final price is weight-based and location-sensitive.",
    },
    "ginger": {
        "price": 4.29,
        "source": "Coles Australian Ginger Loose approx. 130g",
        "url": "https://www.coles.com.au/product/coles-australian-ginger-loose-approx.-130g-5034484",
        "aliases": ("ginger", "fresh ginger", "australian ginger"),
        "note": "Coles Australian loose ginger selected; final price is weight-based and location-sensitive.",
    },
}


def _normalize_name(name: str) -> str:
    normalized = str(name or "").lower().replace("’", "'").replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _matching_name(name: str) -> str:
    """Strip recipe quantities and a leading Coles brand marker for alias lookup."""
    normalized = _normalize_name(name)
    normalized = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:kg|g|mg|l|ml|litre|litres|liter|liters|pack|packs|each)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", " ", normalized)
    normalized = re.sub(
        r"\b(?:head|heads|clove|cloves|tbsp|tsp|tablespoon|tablespoons|teaspoon|teaspoons)\b",
        " ",
        normalized,
    )
    if normalized.startswith("coles "):
        normalized = normalized[6:]
    return " ".join(normalized.split())


def _catalog_key(name: str) -> str | None:
    normalized = _normalize_name(name)
    matching_name = _matching_name(name)
    if not normalized:
        return None
    candidates: list[tuple[int, str]] = []
    for key, match in COLES_PRICE_CATALOG.items():
        aliases = (*match.get("aliases", ()), key)
        for alias in aliases:
            alias_normalized = _normalize_name(alias)
            alias_matching = _matching_name(alias)
            if normalized == alias_normalized or matching_name == alias_normalized or matching_name == alias_matching:
                return key
            for value in (normalized, matching_name):
                if alias_normalized and (value.startswith(f"{alias_normalized} ") or value.endswith(f" {alias_normalized}")):
                    candidates.append((len(alias_normalized), key))
    return max(candidates)[1] if candidates else None


def _is_manual_price(item: dict) -> bool:
    confidence = str(item.get("price_confidence") or "").strip().casefold()
    source = str(item.get("price_source") or "").strip().casefold()
    return confidence == "manual" or source.startswith("manual")


def apply_known_coles_prices(store: PlannerStore, checked_at: str | None = None) -> list[str]:
    """Apply explainable Coles-preferred matches and refresh stale auto-matches.

    Manual prices are never overwritten. Existing observed retailer matches may
    be refreshed when the curated product choice changes, such as milk moving
    from a 2L fresh product to the requested 1L long-life product.
    """
    checked = checked_at or date.today().isoformat()
    updated: list[str] = []
    for item in store.list_grocery_items():
        key = _catalog_key(item["name"])
        if not key or _is_manual_price(item):
            continue
        match = COLES_PRICE_CATALOG[key]
        if (
            item.get("price") == match["price"]
            and item.get("price_source") == match["source"]
            and item.get("price_url") == match["url"]
        ):
            continue
        store.set_grocery_price(
            item["id"], match["price"], match["source"], match["url"],
            "observed", checked, match["note"],
        )
        updated.append(item["name"])
    return updated



WOOLWORTHS_PRICE_CATALOG = {
    "milk": {
        "price": 1.85,
        "source": "Woolworths Full Cream Milk 1L",
        "url": "https://www.woolworths.com.au/shop/productdetails/50923/woolworths-full-cream-milk",
        "aliases": ("milk", "full cream milk", "1l milk", "woolworths milk"),
        "note": "Woolworths full-cream 1L milk; price is location-sensitive and availability may vary.",
        "observed_at": "2026-08-04",
    },
    "eggs": {
        "price": 6.50,
        "source": "Woolworths 12 X-Large Free Range Eggs 700g",
        "url": "https://www.woolworths.com.au/shop/productdetails/224763/woolworths-12-x-large-free-range-eggs",
        "aliases": ("eggs", "egg", "free range eggs", "12 eggs"),
        "note": "Woolworths 12 extra-large free-range eggs 700g; price is location-sensitive and availability may vary.",
        "observed_at": "2026-08-04",
    },
    "bananas": {
        "price": 0.91,
        "source": "Cavendish Bananas each",
        "url": "https://www.woolworths.com.au/shop/productdetails/133211/cavendish-bananas",
        "aliases": ("bananas", "banana", "cavendish bananas"),
        "note": "Woolworths Cavendish banana sold by each; price is location-sensitive and availability may vary.",
        "observed_at": "2026-08-04",
    },
    "butter": {
        "price": 4.50,
        "source": "Woolworths Australian Butter Salted 250g",
        "url": "https://www.woolworths.com.au/shop/productdetails/68978/woolworths-australian-butter-salted",
        "aliases": ("butter", "salted butter"),
        "note": "Woolworths Australian salted butter 250g; price is location-sensitive and availability may vary.",
        "observed_at": "2026-08-04",
    },
    "coke zero": {
        "price": 4.00,
        "source": "Coca-Cola Zero Sugar Soft Drink Bottle 2L",
        "url": "https://www.woolworths.com.au/shop/productdetails/672966/coca-cola-zero-sugar-soft-drink-bottle",
        "aliases": ("coke zero", "coke zero sugar", "coca cola zero sugar", "coca cola zero", "coca-cola zero sugar"),
        "comparison_family": "coke zero",
        "size_quantity_safe": True,
        "note": "Woolworths Coca-Cola Zero Sugar 2L bottle; price is location-sensitive and availability may vary.",
        "size_flexible": True,
        "observed_at": "2026-08-04",
    },
    "chickpeas": {
        "price": 0.95,
        "source": "Woolworths Chickpeas 420g",
        "url": "https://www.woolworths.com.au/shop/productdetails/907050/woolworths-chickpeas",
        "aliases": ("chickpeas", "chick pea", "canned chickpeas"),
        "note": "Woolworths chickpeas 420g; price is location-sensitive and availability may vary.",
        "observed_at": "2026-08-04",
    },
}

RETAILER_LABELS = {
    "coles": "Coles",
    "woolworths": "Woolworths",
}
RETAILER_CATALOGS = {
    "coles": COLES_PRICE_CATALOG,
    "woolworths": WOOLWORTHS_PRICE_CATALOG,
}
RETAILERS = tuple(RETAILER_CATALOGS)

_SIZE_RE = re.compile(r"\b(?:(\d+(?:\.\d+)?)\s*x\s*)?(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml|litre|litres|liter|liters|pack|packs|each)\b")
_INVALID_SIZE_RE = re.compile(r"(?<![a-z0-9])[-+]\s*\d+(?:\.\d+)?\s*(?:kg|g|mg|l|ml|litre|litres|liter|liters|pack|packs|each)\b", re.IGNORECASE)
_VARIANT_PHRASES = (
    "long life", "full cream", "lactose free", "unsweetened", "zero sugar", "zero",
    "free range", "cage free", "barn laid", "organic", "wholemeal", "original",
    "buffalo", "xtra hot", "extra hot", "lite", "fresh", "oat",
)
_ALLOWED_CONTEXT_WORDS = {
    "approx", "approximately", "roughly", "brand", "coles", "select", "loose", "each", "bottle", "pack", "packet",
}
_IGNORED_MEASURE_WORDS = {
    "head", "heads", "clove", "cloves", "tbsp", "tsp", "tablespoon", "tablespoons",
    "teaspoon", "teaspoons", "can", "cans", "bunch", "bunches",
}


def _contextual_alias_extension(value: str, alias: str) -> bool:
    if value.startswith(f"{alias} "):
        extra = value[len(alias):].split()
    elif value.endswith(f" {alias}"):
        extra = value[:-len(alias)].split()
    else:
        return False
    return bool(extra) and set(extra).issubset(_ALLOWED_CONTEXT_WORDS)


def normalize_name(name: object) -> str:
    normalized = str(name or "").lower().replace("’", "'").replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _matching_name(name: object) -> str:
    """Remove recipe quantity language while leaving product words intact."""
    normalized = normalize_name(name)
    normalized = _SIZE_RE.sub(" ", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", " ", normalized)
    normalized = re.sub(r"\b(?:" + "|".join(sorted(_IGNORED_MEASURE_WORDS, key=len, reverse=True)) + r")\b", " ", normalized)
    return " ".join(normalized.split())


def _canonical_size_unit(unit: str) -> str:
    return {"litre": "l", "litres": "l", "liter": "l", "liters": "l", "packs": "pack"}.get(unit, unit)


def _has_invalid_size_notation(value: object) -> bool:
    return bool(_INVALID_SIZE_RE.search(str(value or "")))


def _size_tokens(value: object) -> tuple[str, ...]:
    tokens = []
    for multiplier, number, unit in _SIZE_RE.findall(normalize_name(value)):
        token = f"{number}{_canonical_size_unit(unit)}"
        tokens.append(f"{multiplier}x{token}" if multiplier else token)
    return tuple(tokens)


def _variant_tokens(value: object) -> set[str]:
    normalized = normalize_name(value)
    return {phrase for phrase in _VARIANT_PHRASES if phrase in normalized}


_SIZE_INPUT_UNITS = {"g", "kg", "mg", "ml", "l", "litre", "litres", "liter", "liters"}


def _format_size_quantity(value: object, unit: object) -> str | None:
    normalized_unit = normalize_name(unit)
    if normalized_unit not in _SIZE_INPUT_UNITS:
        return None
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return None
    if quantity <= 0:
        return None
    number = str(int(quantity)) if quantity.is_integer() else str(quantity).rstrip("0").rstrip(".")
    return f"{number}{_canonical_size_unit(normalized_unit)}"


def _count_unit(unit: object) -> bool:
    normalized = normalize_name(unit)
    return not normalized or normalized in {"each", "item", "items", "pack", "packs", "packet", "packets", "bottle", "bottles", "can", "cans"}


def _safe_alias_match(query: object, alias: object) -> int:
    query_normalized = normalize_name(query)
    alias_normalized = normalize_name(alias)
    query_matching = _matching_name(query)
    alias_matching = _matching_name(alias)
    if not query_normalized or not alias_normalized:
        return 0
    if not _size_tokens(query) and _size_tokens(alias):
        return 0
    if query_normalized == alias_normalized:
        return 1000 + len(alias_normalized)
    if query_matching == alias_normalized or query_matching == alias_matching:
        return 800 + len(alias_matching)
    for value in (query_normalized, query_matching):
        if _contextual_alias_extension(value, alias_normalized):
            return 400 + len(alias_normalized)
    return 0


def _compatible_constraints(query: object, product: dict) -> bool:
    query_sizes = set(_size_tokens(query))
    product_sizes = set(_size_tokens(product.get("source", "")))
    if query_sizes and (not product_sizes or not query_sizes.issubset(product_sizes)):
        return False
    query_variants = _variant_tokens(query)
    product_variants = _variant_tokens(product.get("source", ""))
    return query_variants.issubset(product_variants)


def _comparison_key(key: str, product: dict) -> str:
    family = normalize_name(product.get("comparison_family") or key)
    sizes = ",".join(_size_tokens(product.get("source", ""))) or "unspecified"
    variants = ",".join(sorted(_variant_tokens(product.get("source", "")))) or "default"
    return f"{family}|sizes={sizes}|variants={variants}"


_SIZE_MAGNITUDE_RE = re.compile(r"^(?:(\d+(?:\.\d+)?)x)?(\d+(?:\.\d+)?)(kg|g|mg|l|ml|pack|each)$")
_SIZE_MAGNITUDE_UNITS = {
    "mg": ("mass", 0.001),
    "g": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "ml": ("volume", 1.0),
    "l": ("volume", 1000.0),
}


def _size_magnitude(token: str) -> tuple[str, float] | None:
    match = _SIZE_MAGNITUDE_RE.fullmatch(token)
    if not match:
        return None
    multiplier, number, unit = match.groups()
    dimensions = _SIZE_MAGNITUDE_UNITS.get(unit)
    if dimensions is None:
        return None
    magnitude = float(number) * float(multiplier or 1)
    if magnitude <= 0:
        return None
    return dimensions[0], magnitude


def _closest_size_score(query: object, product: dict) -> tuple[int, str, str] | None:
    query_sizes = _size_tokens(query)
    product_sizes = _size_tokens(product.get("source", ""))
    if len(query_sizes) != 1 or len(product_sizes) != 1:
        return None
    query_magnitude = _size_magnitude(query_sizes[0])
    product_magnitude = _size_magnitude(product_sizes[0])
    if not query_magnitude or not product_magnitude or query_magnitude[0] != product_magnitude[0]:
        return None
    ratio = max(query_magnitude[1], product_magnitude[1]) / min(query_magnitude[1], product_magnitude[1])
    distance = abs(math.log(ratio))
    return max(1, int(300 - distance * 100)), query_sizes[0], product_sizes[0]


def _materialize(retailer: str, key: str, product: dict, basis: str, *, requested_size: str | None = None, size_match: str = "exact") -> dict:
    return {
        "retailer": retailer,
        "retailer_label": RETAILER_LABELS[retailer],
        "product_key": key,
        "comparison_key": _comparison_key(key, product),
        "title": product["source"],
        "price": float(product["price"]),
        "url": product["url"],
        "confidence": "curated",
        "observed_at": product.get("observed_at", "2026-08-04"),
        "note": product["note"],
        "match_basis": basis,
        "requested_size": requested_size,
        "product_size": (_size_tokens(product.get("source", "")) or [None])[0],
        "size_match": size_match,
        "size_quantity_safe": bool(product.get("size_quantity_safe")),
    }


def match_item(name: object, retailer: str, unit: object = "each") -> dict | None:
    retailer_key = str(retailer or "").strip().lower()
    if _has_invalid_size_notation(name) or not _count_unit(unit):
        return None
    catalog = RETAILER_CATALOGS.get(retailer_key)
    if catalog is None:
        raise ValueError(f"unsupported retailer: {retailer}")
    requested_size = (_size_tokens(name) or [None])[0]
    candidates: list[tuple[int, str, dict, str, str]] = []
    for key, product in catalog.items():
        if not _compatible_constraints(name, product):
            continue
        aliases = (*product.get("aliases", ()), key)
        score = max((_safe_alias_match(name, alias) for alias in aliases), default=0)
        if score:
            basis = "exact alias" if score >= 1000 else "normalized alias"
            candidates.append((score, key, product, basis, "exact"))
    if candidates:
        score, key, product, basis, size_match = max(candidates, key=lambda item: (item[0], len(item[1])))
        return _materialize(retailer_key, key, product, basis, requested_size=requested_size, size_match=size_match)

    # A closest-pack fallback is opt-in per catalog entry. It is useful for
    # showing a same-family product across retailers, but its size mismatch
    # prevents it from making a cart comparable/recommendable.
    if requested_size:
        closest_candidates: list[tuple[int, str, dict, str, str]] = []
        query_family = _matching_name(name)
        for key, product in catalog.items():
            if not product.get("size_flexible") or not _variant_tokens(name).issubset(_variant_tokens(product.get("source", ""))):
                continue
            family_match = any(_matching_name(alias) == query_family for alias in (*product.get("aliases", ()), key))
            if not family_match:
                continue
            size_score = _closest_size_score(name, product)
            if size_score is None:
                continue
            score, _, _ = size_score
            closest_candidates.append((score, key, product, "closest size alias", "closest"))
        if closest_candidates:
            score, key, product, basis, size_match = max(closest_candidates, key=lambda item: (item[0], len(item[1])))
            return _materialize(retailer_key, key, product, basis, requested_size=requested_size, size_match=size_match)
    return None


def normalize_grocery_item(item: dict) -> dict:
    """Treat a size-qualified packaged product as one purchase, not N units.

    Recipe imports use ``quantity | unit | name``. For a known product, a line
    such as ``600 | ml | Coke Zero`` is canonicalized to ``Coke Zero 600ml``
    with quantity one. Unknown measured ingredients remain untouched.
    """
    normalized = dict(item)
    size = _format_size_quantity(item.get("quantity"), item.get("unit"))
    if size is None:
        return normalized
    name = str(item.get("name") or "").strip()
    if not name:
        return normalized
    sized_name = f"{name} {size}"
    exact_match = any(
        (match := match_item(sized_name, retailer)) is not None
        and match.get("size_match") == "exact"
        and match.get("size_quantity_safe") is True
        for retailer in RETAILERS
    )
    if not exact_match:
        return normalized
    if size not in _size_tokens(name):
        normalized["name"] = sized_name
    normalized["quantity"] = 1
    normalized["unit"] = "each"
    return normalized


def _live_match_for_item(item: dict, retailer: str, live_matches: dict[str, dict[str, dict]] | None) -> dict | None:
    if not live_matches or not item.get("id"):
        return None
    match = live_matches.get(retailer, {}).get(str(item["id"]))
    return dict(match) if isinstance(match, dict) else None


def _best_deals(comparison: dict[str, dict], items: list[dict]) -> list[dict]:
    """Return safe per-item savings only when stores match the same product."""
    deals: list[dict] = []
    for index, item in enumerate(items):
        candidates = []
        for retailer, result in comparison.items():
            line = result["lines"][index]
            match = line.get("match")
            if not match or match.get("size_match") != "exact" or not match.get("comparison_key"):
                continue
            candidates.append((retailer, line, match))
        if len(candidates) < 2:
            continue
        if len({candidate[2].get("comparison_key") for candidate in candidates}) != 1:
            continue
        cheapest = min(candidates, key=lambda candidate: candidate[1].get("line_total") if candidate[1].get("line_total") is not None else math.inf)
        highest = max(candidates, key=lambda candidate: candidate[1].get("line_total") if candidate[1].get("line_total") is not None else -math.inf)
        if cheapest[1].get("line_total") is None or highest[1].get("line_total") is None:
            continue
        savings = round(float(highest[1]["line_total"]) - float(cheapest[1]["line_total"]), 2)
        if savings <= 0:
            continue
        deals.append({
            "item_id": item.get("id"),
            "name": item.get("name"),
            "retailer": cheapest[0],
            "retailer_label": cheapest[2].get("retailer_label", cheapest[0].title()),
            "price": cheapest[2]["price"],
            "savings": savings,
            "comparison_key": cheapest[2]["comparison_key"],
            "stale": any(bool(match.get("stale")) for _, _, match in candidates),
        })
    return sorted(deals, key=lambda deal: (-deal["savings"], str(deal.get("name") or "")))


def compare_cart(
    items: list[dict],
    retailers: tuple[str, ...] = RETAILERS,
    live_matches: dict[str, dict[str, dict]] | None = None,
) -> dict[str, dict]:
    comparison: dict[str, dict] = {}
    for retailer in retailers:
        lines = []
        unknown = []
        total = 0.0
        for raw_item in items:
            item = normalize_grocery_item(raw_item)
            try:
                quantity = float(item.get("quantity") or 1)
            except (TypeError, ValueError):
                quantity = 1.0
            quantity = quantity if quantity > 0 else 1.0
            match = _live_match_for_item(item, retailer, live_matches)
            if match is None:
                item_unit = item.get("unit", "each")
                query_name = item.get("name", "")
                query_unit = item_unit
                if not _count_unit(item_unit):
                    query_name = f"{query_name} {quantity:g}{item_unit}"
                    query_unit = "each"
                match = match_item(query_name, retailer, query_unit)
            purchase_quantity = 1.0 if match and match.get("size_match") == "closest" else quantity
            line_total = round(match["price"] * purchase_quantity, 2) if match else None
            if line_total is None:
                unknown.append(str(item.get("name") or ""))
            else:
                total += line_total
            lines.append({"item_id": item.get("id"), "name": item.get("name"), "quantity": purchase_quantity, "line_total": line_total, "match": match})
        comparison[retailer] = {
            "retailer": retailer,
            "retailer_label": RETAILER_LABELS.get(retailer, retailer.title()),
            "total": round(total, 2),
            "priced_count": len(items) - len(unknown),
            "unknown_count": len(unknown),
            "unknown_items": unknown,
            "complete": not unknown,
            "total_status": "complete" if not unknown else "partial" if lines else "unavailable",
            "lines": lines,
            "live_count": sum(1 for line in lines if (line.get("match") or {}).get("confidence") == "live"),
            "stale_count": sum(1 for line in lines if (line.get("match") or {}).get("stale")),
        }
    item_names = [str(item.get("name") or "") for item in items]
    not_comparable_indexes: set[int] = set()
    for index in range(len(items)):
        keys = {
            None
            if not result["lines"][index]["match"] or result["lines"][index]["match"].get("size_match") != "exact"
            else result["lines"][index]["match"].get("comparison_key")
            for result in comparison.values()
        }
        if len(keys) != 1 or None in keys:
            not_comparable_indexes.add(index)
    comparable = bool(items) and all(result["complete"] for result in comparison.values()) and not not_comparable_indexes
    not_comparable_items = [item_names[index] for index in sorted(not_comparable_indexes)]
    for result in comparison.values():
        result["comparable"] = comparable
        result["not_comparable_items"] = not_comparable_items
        result["comparison_status"] = "comparable" if comparable else "non_equivalent" if not_comparable_items and all(result["complete"] for result in comparison.values()) else "partial"
    for result in comparison.values():
        result["best_deals"] = _best_deals(comparison, items)
    return comparison


def catalog_updates(items: list[dict], retailer: str = "coles") -> list[dict]:
    updates = []
    for raw_item in items:
        item = normalize_grocery_item(raw_item)
        if _is_manual_price(item):
            continue
        match = match_item(item.get("name", ""), retailer, item.get("unit", "each"))
        if match is None or match.get("size_match") != "exact":
            continue
        expected = {
            "price": match["price"],
            "price_source": match["title"],
            "price_url": match["url"],
            "price_confidence": match["confidence"],
            "price_checked_at": match["observed_at"],
        }
        unchanged = True
        for field, value in expected.items():
            current = item.get(field)
            if field == "price_checked_at":
                unchanged = unchanged and str(current or "")[:10] == str(value)[:10]
            else:
                unchanged = unchanged and current == value
        if unchanged and item.get("price_note") == match["note"]:
            continue
        updates.append({"item": item, "match": match})
    return updates
