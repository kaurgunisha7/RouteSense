"""Itinerary engine: code does geography, time and budget (the parser extracts fields and the planner creates the schedule).

Pipeline
  1. Python parser provides interests; score every POI (preference, popularity, value-for-money)
  2. shortlist sightseeing POIs (round-robin over interest groups so each interest is covered)
  3. each day starts from a "seed": the best unused place that is open that weekday, preferring
     areas dense with other good places (so every day gets one neighbourhood's highlights)
  4. per day, simulate the clock: pick the next stop by score - travel - waiting, only if it is
     OPEN when we arrive and fits the remaining budget (nearby places win); insert
     lunch / snack / dinner / nightlife
  5. return the plan with arrival/leave times, costs, reasons, warnings
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date as Date, timedelta

from .hours import fit_visit, is_open_on, windows
from .pois import POI
from .scoring import Group, best_group, build_groups, group_score
from .travel import HeuristicTravel

SIGHT_CATS = {"attraction", "religious", "nature", "entertainment", "shopping"}
MEAL_CATS = {"food", "cafe"}
PACE_ACTIVE_MIN = {"relaxed": 300, "normal": 420, "packed": 540}   # sightseeing + travel minutes per day
PACE_STOPS = {"relaxed": 4, "normal": 5, "packed": 6}                # rough stops/day, used to size the shortlist
TRANSPORT_INR_PER_KM = 12.0          # auto/cab blend; legs under 1 km are walked
DAY_START, LUNCH_FROM, SNACK_FROM = 9 * 60, 12 * 60, 16 * 60
DINNER_FROM, SIGHT_UNTIL, DAY_END = 19 * 60, 18 * 60 + 30, 22 * 60 + 30
DEFAULT_START = (28.6315, 77.2167)   # Connaught Place

@dataclass
class TripRequest:
    days: int = 1
    budget_total_inr: float | None = None
    interests: list[str] = field(default_factory=list)
    start_date: Date | None = None
    start_time: str = "09:00"
    pace: str = "normal"
    travellers: int = 1
    start_location: tuple[float, float] = DEFAULT_START
    default_daily_budget: float = 3000.0
    city: str = "Delhi"


# ----------------------------------------------------------------- helpers
def _hhmm(m: int) -> str:
    m = int(m)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


# ----------------------------------------------------------------- engine
class _Ctx:
    def __init__(self, pois, req, travel):
        self.req, self.travel = req, travel
        self.groups, self.unmatched = build_groups(req.interests)
        self.wants = {g.name for g in self.groups}
        self.day_budget = (req.budget_total_inr / req.days) if req.budget_total_inr else req.default_daily_budget
        self.n = max(1, req.travellers)
        self.pois = pois
        self.score: dict[str, float] = {}
        self.why: dict[str, str | None] = {}
        for p in pois:
            pref, g = best_group(p, self.groups) if self.groups else (0.5, None)
            value = 1 - min(1.0, p.cost * self.n / max(1.0, self.day_budget * 0.3))
            self.score[p.id] = 0.5 * pref + 0.3 * (p.popularity / 5) + 0.2 * value
            self.why[p.id] = g

    def pref(self, p):                      # 0..1 interest match
        return best_group(p, self.groups)[0] if self.groups else 0.5


def _shortlist(ctx: _Ctx, sights: list[POI], target: int) -> list[POI]:
    if not ctx.groups:
        return sorted(sights, key=lambda p: -ctx.score[p.id])[:target]
    chosen: dict[str, POI] = {}
    ranked = {g.name: sorted((p for p in sights if group_score(p, g) > 0),
                             key=lambda p: -(group_score(p, g) * 0.6 + ctx.score[p.id]))
              for g in ctx.groups if g.name != "nightlife"}
    quota = int(target * 0.75)
    while len(chosen) < quota and any(ranked.values()):
        for name in list(ranked):
            while ranked[name] and ranked[name][0].id in chosen:
                ranked[name].pop(0)
            if ranked[name]:
                p = ranked[name].pop(0)
                chosen[p.id] = p
    for p in sorted(sights, key=lambda p: -ctx.score[p.id]):   # fill with must-sees / best overall
        if len(chosen) >= target:
            break
        chosen.setdefault(p.id, p)
    return list(chosen.values())


def plan_trip(pois: list[POI], req: TripRequest, travel=None) -> dict:
    travel = travel or HeuristicTravel()
    ctx = _Ctx(pois, req, travel)
    warnings: list[str] = []
    if ctx.unmatched:
        warnings.append("Interests not recognised, matched on raw tags only: " + ", ".join(ctx.unmatched))
    if req.budget_total_inr is None:
        warnings.append(f"No budget given; assumed ₹{ctx.day_budget:.0f}/day.")
    start_date = req.start_date or Date.today()
    stops_per_day = PACE_STOPS.get(req.pace, 4)

    sights = [p for p in pois if p.category in SIGHT_CATS]
    pool = _shortlist(ctx, sights, target=int(req.days * stops_per_day * 1.6))
    used: set[str] = set()
    spent_total, days_out = 0.0, []
    for d in range(req.days):
        date = start_date + timedelta(days=d)
        wd = date.weekday()
        cap = ctx.day_budget * (d + 1) - spent_total          # unspent budget rolls forward
        cands = [p for p in pool if p.id not in used and is_open_on(p.hours, wd)]
        seed = _pick_seed(ctx, cands)
        day = _plan_day(ctx, d + 1, date, wd, cands, used, cap, stops_per_day, warnings, seed=seed)
        spent_total += day["spend_inr"]
        days_out.append(day)

    carry = [p for p in pool if p.id not in used]
    not_scheduled = [p.name for p in carry if p.id not in used]
    total_budget = req.budget_total_inr or ctx.day_budget * req.days
    if spent_total > total_budget + 1:
        warnings.append("Plan exceeds the budget.")

    scheduled_stops = [stop for day in days_out for stop in day["stops"]]
    if any(stop["opening_hours_estimated"] for stop in scheduled_stops):
        warnings.append(
            "Some scheduled places have estimated or missing opening hours. "
            "Unknown hours may be treated as 09:00-18:00; verify before visiting."
        )
    if any(stop["cost_estimated"] for stop in scheduled_stops):
        warnings.append("Some costs are estimates, not verified current prices.")
    if any(stop["visit_duration_estimated"] for stop in scheduled_stops):
        warnings.append("Visit durations are estimates; queues and actual visit times may vary.")

    return {
        "city": req.city,
        "days": days_out,
        "summary": {
            "total_spend_inr": round(spent_total),
            "budget_inr": round(total_budget),
            "within_budget": spent_total <= total_budget + 1,
            "per_person": True if req.travellers == 1 else False,
            "travellers": req.travellers,
            "total_travel_km": round(sum(x["travel_km"] for x in days_out), 1),
        },
        "interests_used": [g.name for g in ctx.groups],
        "not_scheduled": not_scheduled,
        "warnings": warnings,
    }


def _pick_seed(ctx: _Ctx, cands: list[POI]) -> POI | None:
    """Best open place, boosted when many other good places lie within ~4 km."""
    from .travel import haversine_km
    best = None
    for p in cands:
        near = sorted((ctx.score[q.id] for q in cands if q.id != p.id and haversine_km(p.loc, q.loc) <= 4.0),
                      reverse=True)[:5]
        v = ctx.score[p.id] + 0.03 * sum(near)
        if best is None or v > best[0]:
            best = (v, p)
    return best[1] if best else None


def round_time_30(total_minutes: int) -> str:
    rounded_minutes = round(total_minutes / 30) * 30
    rounded_minutes %= 24 * 60
    return _hhmm(rounded_minutes)

# ----------------------------------------------------------------- one day
def _plan_day(ctx: _Ctx, day_no, date, wd, cands, used, budget_cap, stops_per_day, warnings, seed=None):
    req, travel, n = ctx.req, ctx.travel, ctx.n
    hour, minute = map(int, req.start_time.split(":"))
    cur, loc = hour * 60 + minute, req.start_location
    spent, km_total = 0.0, 0.0
    stops: list[dict] = []
    done = {"lunch": False, "snack": False, "dinner": False}
    want_snack = bool(ctx.wants & {"food", "cafes"})
    active = 0                                  # sightseeing + travel minutes so far
    active_cap = PACE_ACTIVE_MIN.get(req.pace, 420)

    def leg_to(p, depart):
        mins, km = travel.leg(loc, p.loc, depart, wd, date)
        return mins, km, (km * TRANSPORT_INR_PER_KM if km > 1.0 else 0.0)

    def commit(p, kind, start, end, mins, km, transport, cost, note=None):
        nonlocal cur, loc, spent, km_total
        used.add(p.id)
        spent += cost + transport
        km_total += km
        why = []
        if ctx.why[p.id] and kind in ("sight", "nightlife"):
            why.append(f"matches interest: {ctx.why[p.id]}")
        elif kind != "sight" and ctx.why[p.id]:
            why.append(f"fits your taste: {ctx.why[p.id]}")
        why.append(f"popularity {p.popularity:g}/5")
        display_start = start

        if not stops:
            hour, minute = map(int, req.start_time.split(":"))
            display_start = hour * 60 + minute
        stops.append({
            "id": p.id, "name": p.name, "kind": kind, "category": p.category,
            "lat": p.lat, "lon": p.lon,
            "display_arrive": _hhmm(start),
            "arrive": round_time_30(display_start),
            "leave": _hhmm(end), "visit_minutes": end - start,
            "travel_minutes_from_previous": mins, "travel_km": round(km, 1),
            "cost_inr": round(cost), "transport_inr": round(transport),
            "opening_hours": p.hours_raw or "unknown",
            "opening_hours_estimated": bool(p.extra.get("hours_estimated", True)) or not bool(p.hours_raw),
            "cost_estimated": bool(p.extra.get("cost_estimated", True)),
            "visit_duration_estimated": bool(p.extra.get("visit_duration_estimated", True)),
            "why": why,
            "note": note, "description": p.description,
        })
        cur, loc = end, p.loc

    def remaining():
        return budget_cap - spent

    def pick_meal(kind):
        if len(stops) >= 6:
            done[kind] = True
            return
        nonlocal cur
        dur = {"lunch": 60, "snack": 40, "dinner": 75}[kind]
        earliest = DINNER_FROM if kind == "dinner" else 0
        cap_frac = {"lunch": 0.30, "snack": 0.12, "dinner": 0.40}[kind]
        best = None
        for p in ctx.pois:
            if p.id in used:
                continue
            if kind == "dinner" and p.category != "food":
                continue
            if kind == "lunch" and p.category not in MEAL_CATS:
                continue
            if kind == "snack" and not (p.category == "cafe" or p.tags & {"sweets", "street_food", "chaat"}):
                continue
            cost = p.cost * n
            mins, km, tr = leg_to(p, cur)
            if cost > ctx.day_budget * cap_frac or cost + tr > remaining():
                continue
            fit = fit_visit(p.hours, wd, max(cur + mins, earliest), dur, max_wait=30, min_frac=0.8)
            if not fit:
                continue
            wait = fit[0] - (cur + mins)
            rank = ctx.pref(p) * 25 + p.popularity * 3 - mins * 0.8 - wait * 0.3
            if best is None or rank > best[0]:
                best = (rank, p, fit, mins, km, tr, cost)
        if not best:
            done[kind] = True
            if kind != "snack":
                warnings.append(f"Day {day_no}: no {kind} option found within budget/opening hours.")
            return
        _, p, (s, e), mins, km, tr, cost = best
        commit(p, kind, s, e, mins, km, tr, cost)
        done[kind] = True

    def pick_sight(only=None):
        best = None
        reserve = (0 if done["lunch"] else 150 * n) + (0 if done["dinner"] else 200 * n)
        for p in cands:
            if p.id in used or p.category not in SIGHT_CATS or (only and p.id != only.id):
                continue
            mins, km, tr = leg_to(p, cur)
            cost = p.cost * n
            if cost + tr > remaining() - reserve:
                continue
            fit = fit_visit(p.hours, wd, cur + mins, p.duration)
            if not fit:
                continue
            s, e = fit
            if s >= SIGHT_UNTIL:
                continue
            wait = s - (cur + mins)
            close = max(c for _, c in windows(p.hours, wd))
            urgency = 12 if close - e < 90 else 0           # closes soon: do it now
            travel_pen = mins * (0.4 if not stops else 2)       # the ride from the hotel counts less
            long_trip_pen = max(0, mins - 20) * 1.5
            rank = (
                ctx.score[p.id] * 40 + urgency - travel_pen - long_trip_pen - wait * 0.5)
            if best is None or rank > best[0]:
                best = (rank, p, s, e, mins, km, tr, cost)
        return best

    while True:
        if not done["lunch"] and cur >= LUNCH_FROM:
            pick_meal("lunch"); continue
        if want_snack and not done["snack"] and SNACK_FROM <= cur < 1080:
            pick_meal("snack"); continue
        if not done["dinner"] and cur >= 1110:
            pick_meal("dinner"); continue
        if active < active_cap and cur < SIGHT_UNTIL and len(stops) < 6:
            b = (pick_sight(only=seed) if (seed and not stops) else None) or pick_sight()
            if b:
                _, p, s, e, mins, km, tr, cost = b
                if not done["lunch"] and cur >= 11 * 60 + 30 and e > 14 * 60:
                    pick_meal("lunch")          # this visit would push lunch too late: eat first
                    continue
                note = "shortened: closes before full visit" if e - s < p.duration else None
                commit(p, "sight", s, e, mins, km, tr, cost, note)
                active += mins + (e - s)
                continue
        break

    if not done["lunch"]:
        pick_meal("lunch")                      # sightseeing finished before lunch time
    if not done["dinner"]:
        pick_meal("dinner")

    if (
    "nightlife" in ctx.wants
    and stops
    and len(stops) < 5
    and cur < 23 * 60
):
        best = None
        for p in ctx.pois:
            if p.category != "nightlife" or p.id in used:
                continue
            mins, km, tr = leg_to(p, cur)
            cost = p.cost * n
            if cost + tr > remaining():
                continue
            fit = fit_visit(p.hours, wd, cur + mins, 120, max_wait=60, min_frac=0.5)
            if fit:
                rank = ctx.score[p.id] * 40 - mins
                if best is None or rank > best[0]:
                    best = (rank, p, fit, mins, km, tr, cost)
        if best:
            _, p, (s, e), mins, km, tr, cost = best
            commit(p, "nightlife", s, e, mins, km, tr, cost)

    if not stops:
        warnings.append(f"Day {day_no}: nothing could be scheduled (closed or over budget).")
    return {
        "day": day_no, "date": date.isoformat(), "weekday": date.strftime("%A"),
        "stops": stops, "spend_inr": round(spent), "budget_cap_inr": round(budget_cap),
        "travel_km": round(km_total, 1),
        "ends_at": stops[-1]["leave"] if stops else None,
    }
