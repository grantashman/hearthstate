from __future__ import annotations

from datetime import date
import re

from .store import PlannerStore


# Curated Coles product matches. Product pages and observed prices are kept
# explicit so a match is explainable rather than pretending to be a live
# retailer search result. Coles prices vary by store and location.
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
        "aliases": ("2l coke zero", "coke zero 2l", "coca cola zero sugar 2l"),
        "note": "Exact 2L Coca-Cola Zero Sugar bottle selected; do not substitute a different size or diet variant. Price is location-sensitive.",
    },
    "franks hot sauce": {
        "price": 3.50,
        "source": "Frank's Redhot Original Sauce 148mL",
        "url": "https://www.coles.com.au/product/frank's-redhot-original-sauce-148ml-1957139",
        "aliases": ("franks hot sauce", "frank's hot sauce", "franks redhot", "frank's redhot", "franks redhot original", "frank's redhot original"),
        "note": "Standard Frank's RedHot Original Cayenne Pepper Sauce selected: 148mL; Buffalo and Xtra Hot variants are not substituted. Price is location-sensitive.",
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
        if not key or item.get("price_confidence") == "manual":
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
