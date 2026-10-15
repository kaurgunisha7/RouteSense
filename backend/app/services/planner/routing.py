"""Step 5: turn the planned stops into drivable routes.

For every leg (user location -> first stop, stop -> next stop):
  1. ask OSRM for the road routes incl. alternatives  (/route?alternatives=true)
  2. ETA of each option = OSRM free-flow minutes x congestion factor(time, weekday, weather, distance)
  3. choose the option with the lowest ETA, return its polyline + the other options

If OSRM is unreachable the leg falls back to a straight-line estimate (source = "estimate"), so the
API still answers. The planner's schedule is NOT re-timed; each leg reports `delta_min` = route ETA minus
the time the planner assumed, so the UI can warn when a leg is slower than planned.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .cities import MAX_DISTANCE_FROM_CITY_KM
from .travel import HeuristicTravel, haversine_km, traffic_multiplier


@dataclass
class RouteOption:
    distance_km: float
    free_min: float                      # OSRM duration (free flow)
    coords: list                         # [[lat, lon], ...]


class OsrmClient:
    def __init__(self, base_url: str = "http://localhost:5000", timeout: float = 4.0):
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self._cache: dict = {}

    def routes(self, a, b) -> list[RouteOption]:
        key = (round(a[0], 5), round(a[1], 5), round(b[0], 5), round(b[1], 5))
        if key in self._cache:
            return self._cache[key]
        out: list[RouteOption] = []
        try:
            import httpx
            url = f"{self.base_url}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}"
            r = httpx.get(url, params={"alternatives": "true", "overview": "full", "geometries": "geojson"},
                          timeout=self.timeout, headers={"User-Agent": "RouteSense-student-project"})
            r.raise_for_status()
            for rt in r.json().get("routes", []):
                out.append(RouteOption(rt["distance"] / 1000, rt["duration"] / 60,
                                       [[lat, lon] for lon, lat in rt["geometry"]["coordinates"]]))
        except Exception:
            out = []                                    # caller falls back to an estimate
        if out:                                         # never cache failures
            self._cache[key] = out
        return out


def score_options(options, depart_min, weekday, date, congestion):
    """-> list of dicts with eta_min per option (same order as `options`)."""
    scored = []
    for o in options:
        mid = o.coords[len(o.coords) // 2] if o.coords else None
        if congestion is not None:
            f = congestion.factor(depart_min, weekday, o.distance_km, date,
                                  mid[0] if mid else None, mid[1] if mid else None, freeflow_min=o.free_min)
        else:
            f = traffic_multiplier(depart_min, weekday)
        scored.append({"distance_km": round(o.distance_km, 1), "eta_min": round(o.free_min * f), "factor": round(f, 2)})
    return scored


def resolve_start(user_lat, user_lon, centre):
    """Use the user's GPS if it is near the city, otherwise start from the city centre."""
    if user_lat is None or user_lon is None:
        return tuple(centre), "city_centre"
    if haversine_km((user_lat, user_lon), centre) > MAX_DISTANCE_FROM_CITY_KM:
        return tuple(centre), "city_centre"
    return (float(user_lat), float(user_lon)), "user_location"


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def add_routes(plan: dict, start, osrm: OsrmClient | None, congestion=None) -> dict:
    """Attach `route` to every stop of `plan` (mutates and returns it)."""
    est = HeuristicTravel(congestion)
    used_osrm = False
    for day in plan["days"]:
        wd = __import__("datetime").date.fromisoformat(day["date"]).weekday()
        date = __import__("datetime").date.fromisoformat(day["date"])
        prev, total = start, 0
        for s in day["stops"]:
            here = (s["lat"], s["lon"])
            depart = max(0, _mins(s["arrive"]) - s["travel_minutes_from_previous"])
            options = osrm.routes(prev, here) if osrm else []
            if options:
                scored = score_options(options, depart, wd, date, congestion)
                best = min(range(len(scored)), key=lambda i: scored[i]["eta_min"])
                for i, sc in enumerate(scored):
                    sc["chosen"] = i == best
                route = {"source": "osrm", "distance_km": scored[best]["distance_km"],
                         "eta_min": scored[best]["eta_min"], "polyline": options[best].coords,
                         "alternatives": scored}
                used_osrm = True
            else:
                mins, km = est.leg(prev, here, depart, wd, date)
                route = {"source": "estimate", "distance_km": round(km, 1), "eta_min": mins,
                         "polyline": [list(prev), list(here)], "alternatives": []}
            route["delta_min"] = route["eta_min"] - s["travel_minutes_from_previous"]
            route["depart"] = f"{(depart // 60) % 24:02d}:{depart % 60:02d}"
            route["from"] = {"lat": prev[0], "lon": prev[1]}
            s["route"] = route
            total += route["eta_min"]
            prev = here
        day["route_eta_total_min"] = total
    plan["routing"] = {"source": "osrm" if used_osrm else "estimate"}
    return plan
