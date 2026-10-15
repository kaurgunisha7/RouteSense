"""Travel time/distance between two points.

HeuristicTravel works offline (haversine x road factor x Delhi traffic).
OsrmTravel asks a local OSRM server for the road distance and applies the
same traffic multiplier; it falls back to the heuristic on any error.
"""
from __future__ import annotations

import math


def haversine_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def traffic_multiplier(depart_min: int, weekday: int) -> float:
    """Rule-based slowdown. Replace with a trained model later (same signature)."""
    h = depart_min / 60
    weekend = weekday >= 5
    if 8 <= h < 11 or 17 <= h < 21:
        return 1.2 if weekend else 1.6
    if 11 <= h < 17:
        return 1.1 if weekend else 1.25
    return 1.0


class HeuristicTravel:
    """Offline estimate. `congestion` may be a CongestionModel; otherwise the rule-based multiplier is used."""
    ROAD_FACTOR = 1.35
    BASE_KMH = 28.0

    def __init__(self, congestion=None):
        self.congestion = congestion

    def leg(self, a, b, depart_min: int, weekday: int, date=None) -> tuple[int, float]:
        km = haversine_km(a, b) * self.ROAD_FACTOR
        return self._finish(km, depart_min, weekday, date, a)

    def _finish(self, km, depart_min, weekday, date=None, origin=None, freeflow_min=None):
        if km < 0.4:
            return 5, km
        if freeflow_min is None:
            freeflow_min = km / self.BASE_KMH * 60
        if self.congestion is not None:
            m = self.congestion.factor(depart_min, weekday, km, date,
                                       origin[0] if origin else None, origin[1] if origin else None,
                                       freeflow_min=freeflow_min)
        else:
            m = traffic_multiplier(depart_min, weekday)
        return max(8, math.ceil(freeflow_min * m) + 4), km      # +4 min parking/walking


class MatrixTravel(HeuristicTravel):
    """Uses a precomputed OSRM road distance/duration table (see tools/build_matrix.py).
    Falls back to the heuristic for points that are not in the table (e.g. the user's GPS position)."""

    def __init__(self, csv_path: str, congestion=None):
        super().__init__(congestion)
        import csv
        self.table = {}
        with open(csv_path, newline="") as f:
            for r in csv.DictReader(f):
                k = (round(float(r["from_lat"]), 5), round(float(r["from_lon"]), 5),
                     round(float(r["to_lat"]), 5), round(float(r["to_lon"]), 5))
                self.table[k] = (float(r["meters"]) / 1000, float(r["seconds"]) / 60)

    def leg(self, a, b, depart_min, weekday, date=None):
        hit = self.table.get((round(a[0], 5), round(a[1], 5), round(b[0], 5), round(b[1], 5)))
        if hit is None:
            return super().leg(a, b, depart_min, weekday, date)
        km, free_min = hit
        return self._finish(km, depart_min, weekday, date, a, freeflow_min=free_min)


class OsrmTravel(HeuristicTravel):
    def __init__(self, base_url: str = "http://localhost:5000", timeout: float = 3.0, congestion=None):
        super().__init__(congestion)
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self._cache: dict = {}

    def leg(self, a, b, depart_min, weekday, date=None):
        key = (round(a[0], 5), round(a[1], 5), round(b[0], 5), round(b[1], 5))
        km = self._cache.get(key)
        if km is None:
            try:
                import httpx
                url = f"{self.base_url}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}?overview=false"
                r = httpx.get(url, timeout=self.timeout)
                r.raise_for_status()
                km = r.json()["routes"][0]["distance"] / 1000
            except Exception:
                return super().leg(a, b, depart_min, weekday, date)
            self._cache[key] = km
        return self._finish(km, depart_min, weekday, date, a)
