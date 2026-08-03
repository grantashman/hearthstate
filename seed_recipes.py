#!/usr/bin/env python3
"""Seed link-first recipe metadata into the Hearthstate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hearthstate.store import PlannerStore


ILLUSTRATIVE_IMAGES = {
    "Roasted veggies": "/recipe-images/stir-fry.png",
    "Stir-fried vegetables": "/recipe-images/stir-fry.png",
    "Mixed bean salad": "/recipe-images/salad.png",
    "Healthy air-fried spicy roasted chickpeas": "/recipe-images/salad.png",
    "Veggie burgers with lentil patties": "/recipe-images/salad.png",
    "Asian-style mushroom omelette": "/recipe-images/omelette.png",
    "Mexican-style smoky black bean shakshuka": "/recipe-images/curry.png",
    "Ratatouille": "/recipe-images/curry.png",
    "Healthy chicken and vegie stir-fry": "/recipe-images/stir-fry.png",
    "Carrot and chickpea salad with honey coriander dressing": "/recipe-images/salad.png",
    "Healthy sweet potato salad": "/recipe-images/salad.png",
    "Silverbeet, broccoli and apple salad": "/recipe-images/salad.png",
    "Healthy coconut and mango chicken curry": "/recipe-images/curry.png",
    "High-protein chicken soup": "/recipe-images/chicken.png",
    "High protein burrito bowl": "/recipe-images/chicken.png",
    "Grilled salmon": "/recipe-images/salmon.png",
    "Quinoa and salmon salad": "/recipe-images/salmon.png",
    "Beef and broccoli stir-fry": "/recipe-images/beef.png",
    "High-protein beef and barley soup": "/recipe-images/beef.png",
    "Asian-style tofu noodle salad": "/recipe-images/tofu-dhal.png",
    "Speedy sausage and lentil salad": "/recipe-images/tofu-dhal.png",
    "Red lentil dhal with spinach": "/recipe-images/tofu-dhal.png",
}


def seed(database: str, source_file: str) -> int:
    recipes = json.loads(Path(source_file).read_text(encoding="utf-8"))
    store = PlannerStore(database)
    try:
        for recipe in recipes:
            recipe = {**recipe, "image_url": ILLUSTRATIVE_IMAGES.get(recipe["title"])}
            store.add_recipe(**recipe)
    finally:
        store.close()
    return len(recipes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the planner's link-first recipe catalog")
    parser.add_argument("--database", default="hearthstate.db")
    parser.add_argument("--source-file", default="recipe_seeds.json")
    args = parser.parse_args()
    print(json.dumps({"seeded": seed(args.database, args.source_file), "database": args.database}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
