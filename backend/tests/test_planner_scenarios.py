"""Independent checks on generated plans. Run:  python test_planner.py"""
from datetime import date, timedelta
from pathlib import Path

from app.services.planner import plan_trip, TripRequest, load_pois
from app.services.planner.hours import parse_hours, windows

POIS = load_pois(str(Path(__file__).resolve().parents[1] / "data" / "delhi_pois.csv"))
BY_ID = {p.id: p for p in POIS}


def mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def validate(res, req):
    errs, seen = [], set()
    for day in res["days"]:
        wd = date.fromisoformat(day["date"]).weekday()
        prev_leave = None
        for s in day["stops"]:
            p = BY_ID[s["id"]]
            a, l = mins(s["arrive"]), mins(s["leave"])
            if l < a:
                l += 1440                                   # leaves after midnight
            if s["id"] in seen:
                errs.append(f"duplicate {s['name']}")
            seen.add(s["id"])
            if not any(o <= a and l <= c for o, c in windows(parse_hours(p.hours_raw), wd)):
                errs.append(f"day {day['day']} {s['name']} not open {s['arrive']}-{s['leave']} ({p.hours_raw})")
            if prev_leave is not None and a < prev_leave + s["travel_minutes_from_previous"] - 1:
                errs.append(f"day {day['day']} {s['name']} arrives before travel completes")
            prev_leave = l
        if sum(s["cost_inr"] + s["transport_inr"] for s in day["stops"]) > day["spend_inr"] + len(day["stops"]):
            errs.append(f"day {day['day']} spend mismatch")
    if res["summary"]["total_spend_inr"] > res["summary"]["budget_inr"] + 1:
        errs.append("over budget")
    return errs


SCENARIOS = {
    "history+food 3d ₹9000": TripRequest(days=3, budget_total_inr=9000, interests=["history", "street food"], start_date=date(2026, 10, 12)),
    "tight budget 2d ₹2400": TripRequest(days=2, budget_total_inr=2400, interests=["temples", "markets"], start_date=date(2026, 10, 13)),
    "nightlife+cafes 2d": TripRequest(days=2, budget_total_inr=14000, interests=["nightlife", "cafes", "shopping"], start_date=date(2026, 10, 16)),
    "family 2 people, relaxed": TripRequest(days=2, budget_total_inr=12000, travellers=2, pace="relaxed", interests=["family", "parks"], start_date=date(2026, 10, 17)),
    "no interests, 4 days": TripRequest(days=4, budget_total_inr=20000, start_date=date(2026, 10, 12)),
    "unknown interest word": TripRequest(days=1, budget_total_inr=3000, interests=["museums", "quidditch"], start_date=date(2026, 10, 12)),
    "1 day packed": TripRequest(days=1, budget_total_inr=5000, pace="packed", interests=["history"], start_date=date(2026, 10, 14)),
}

if __name__ == "__main__":
    bad = 0
    for name, req in SCENARIOS.items():
        res = plan_trip(POIS, req)
        errs = validate(res, req)
        n = sum(len(d["stops"]) for d in res["days"])
        print(f"{'FAIL' if errs else 'ok  '} {name:28} stops={n:2} spend=₹{res['summary']['total_spend_inr']}/{res['summary']['budget_inr']} warnings={len(res['warnings'])}")
        for e in errs:
            print("      ", e)
        for w in res["warnings"]:
            print("       warn:", w)
        bad += bool(errs)
    raise SystemExit(bad)
