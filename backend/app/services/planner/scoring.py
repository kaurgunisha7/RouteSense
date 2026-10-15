"""Turn parsed free-text interests into relevance scores per POI."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .pois import POI

# interest group -> (trigger keywords, matching categories, matching tags)
GROUPS: dict[str, tuple[list[str], set[str], set[str]]] = {
    "history & heritage": (
        ["histor", "heritage", "monument", "fort", "ancient", "architect", "mughal", "tomb",
         "ruin", "unesco", "sightsee", "landmark", "historic"],
        set(),
        {"history", "heritage", "monument", "fort", "ancient", "tomb", "ruins", "architecture",
         "unesco", "stepwell", "tughlaq", "colonial", "memorial"},
    ),
    "food": (
        ["food", "eat", "street food", "cuisine", "restaurant", "foodie", "kebab", "chaat", "dining", "biryani"],
        {"food"},
        {"food", "street_food", "chaat", "kebabs", "sweets", "dining", "butter_chicken", "north_indian"},
    ),
    "cafes": (["cafe", "coffee", "brunch", "bakery", "tea"], {"cafe"}, {"cafe", "cafes", "breakfast"}),
    "shopping": (
        ["shop", "market", "bazaar", "souvenir", "mall", "handicraft", "clothes", "fashion"],
        {"shopping"},
        {"shopping", "fashion", "crafts", "wholesale", "mall", "apparel"},
    ),
    "nightlife": (
        ["nightlife", "club", "bar", "party", "pub", "cocktail", "night"],
        {"nightlife"},
        {"nightlife", "cocktails"},
    ),
    "nature & parks": (
        ["nature", "park", "garden", "outdoor", "bird", "lake", "green", "walk", "trek"],
        {"nature"},
        {"nature", "park", "lake", "birds", "walking", "peaceful"},
    ),
    "religious & spiritual": (
        ["relig", "temple", "spiritual", "mosque", "gurudwara", "church", "pilgrim", "dargah", "worship"],
        {"religious"},
        {"religious", "hinduism", "sikhism", "islam", "dargah", "spiritual"},
    ),
    "museums & art": (
        ["museum", "art", "gallery", "culture", "craft", "exhibit"],
        set(),
        {"museum", "art", "culture", "crafts"},
    ),
    "family & fun": (
        ["family", "kid", "child", "fun", "amusement", "adventure", "entertain", "cinema", "movie"],
        {"entertainment"},
        {"family", "kids", "amusement_park", "rides", "cinema", "entertainment"},
    ),
    "romantic": (["romantic", "couple", "date"], set(), {"romantic"}),
    "photography": (["photo", "instagram", "scenic", "view"], set(), {"photography"}),
}


@dataclass
class Group:
    name: str
    cats: set[str]
    tags: set[str]


def build_groups(interests: list[str]) -> tuple[list[Group], list[str]]:
    """Map interest strings to groups. Returns (groups, unmatched interest words)."""
    groups: dict[str, Group] = {}
    unmatched: list[str] = []
    for raw in interests:
        text = raw.lower().strip()
        if not text:
            continue
        hit = False
        for name, (keys, cats, tags) in GROUPS.items():
            if any(re.search(r"\b" + re.escape(k), text) for k in keys):
                groups[name] = Group(name, cats, tags)
                hit = True
        if not hit:  # fall back to raw token match against tags
            toks = {t.rstrip("s") for t in re.findall(r"[a-z]+", text) if len(t) > 3}
            if toks:
                groups[f"custom:{text}"] = Group(f"custom:{text}", set(), toks)
            unmatched.append(raw)
    return list(groups.values()), unmatched


def group_score(poi: POI, g: Group) -> float:
    cat = 0.5 if poi.category in g.cats else 0.0
    tag_set = {t.rstrip("s") for t in poi.tags} | poi.tags
    hits = len(tag_set & g.tags) if not g.name.startswith("custom:") else len(
        {t for t in g.tags if t in tag_set or t in poi.name.lower()})
    tag = min(1.0, 0.55 + 0.2 * (hits - 1)) if hits else 0.0
    return min(1.0, max(cat, tag) + (0.15 if cat and tag else 0.0))


def best_group(poi: POI, groups: list[Group]) -> tuple[float, str | None]:
    best, name = 0.0, None
    for g in groups:
        s = group_score(poi, g)
        if s > best:
            best, name = s, g.name
    return best, name
