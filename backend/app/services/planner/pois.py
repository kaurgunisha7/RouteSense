from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field

from .hours import parse_hours


def _csv_bool(value, default=False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _csv_float(value, default=0.0) -> float:
    try:
        number = float(value)
        return number if number == number else default  # NaN check
    except (TypeError, ValueError):
        return default


def _csv_int(value, default=60) -> int:
    try:
        number = float(value)
        return int(number) if number == number else default
    except (TypeError, ValueError):
        return default


@dataclass
class POI:
    id: str
    name: str
    category: str
    lat: float
    lon: float
    cost: float                 # INR per person (entry fee or typical meal/drink spend)
    duration: int               # minutes
    popularity: float           # 1-5
    tags: set[str]
    hours_raw: str
    hours: dict | None
    description: str = ""
    area: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def loc(self):
        return (self.lat, self.lon)


def load_pois(path: str, city: str | None = "Delhi") -> list[POI]:
    out, seen = [], set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            name = (r.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            if city and r.get("city") and r["city"].strip().lower() != city.lower():
                continue
            try:
                lat, lon = float(r["lat"]), float(r["lon"])
            except (TypeError, ValueError):
                continue
            seen.add(name.lower())
            try:
                tags = set(json.loads(r.get("tags") or "[]"))
            except json.JSONDecodeError:
                tags = set()
            out.append(POI(
                id=(r.get("osm_id") or str(i)).replace(".0", "") or str(i),
                name=name,
                category=(r.get("category") or "attraction").strip().lower(),
                lat=lat, lon=lon,
                cost=_csv_float(r.get("est_cost"), 0.0),
                duration=max(15, min(360, _csv_int(r.get("visit_minutes"), 60))),
                popularity=max(0.0, min(5.0, _csv_float(r.get("popularity_score"), 3.0))),
                tags={t.lower() for t in tags},
                hours_raw=r.get("opening_hours") or "",
                hours=parse_hours(r.get("opening_hours")),
                description=r.get("description") or "",
                extra={
                    "hours_estimated": _csv_bool(r.get("hours_estimated"), default=True),
                    "cost_estimated": _csv_bool(r.get("cost_estimated"), default=True),
                    "visit_duration_estimated": True,
                    "website": r.get("website") or "",
                    "wikipedia": r.get("wikipedia") or "",
                },
            ))
    return _drop_near_duplicates(out)


def _tokens(name: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-z]+", name.lower()) if t not in {"the", "of", "and", "ka", "ki", "ke"}}


def _drop_near_duplicates(pois: list[POI]) -> list[POI]:
    """Same place listed twice under reworded names (e.g. 'Lajpat Nagar Central Market' /
    'Central Market Lajpat Nagar'): same spot (<150 m) and mostly the same words -> keep the more popular."""
    from .travel import haversine_km
    keep: list[POI] = []
    for p in sorted(pois, key=lambda x: -x.popularity):
        tp = _tokens(p.name)
        dup = any(
            haversine_km(p.loc, q.loc) < 0.15
            and len(tp & _tokens(q.name)) / max(1, len(tp | _tokens(q.name))) >= 0.5
            for q in keep
        )
        if not dup:
            keep.append(p)
    return keep
