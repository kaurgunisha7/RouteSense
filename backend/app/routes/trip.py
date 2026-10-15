"""Trip endpoints powered by the local rule-based parser and itinerary planner.

No hosted or local large-language-model service is required.
"""
from datetime import date as Date, datetime
from functools import lru_cache
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas.trip import TripPreferences
from app.services.planner import TripRequest, load_pois, plan_trip
from app.services.planner.cities import CITIES, find_city
from app.services.planner.parser import parse_prompt
from app.services.planner.routing import OsrmClient, add_routes, resolve_start
from app.services.planner.travel import HeuristicTravel

router = APIRouter()
TIMEZONE = ZoneInfo("Asia/Kolkata")
BACKEND_DIR = Path(__file__).resolve().parents[2]
SUPPORTED_CITIES = {"delhi"}


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class PlanRequest(BaseModel):
    """Free-text prompt and/or structured fields; explicit fields take priority."""
    prompt: str | None = Field(default=None, max_length=4000)
    city: str | None = None
    days: int | None = Field(default=None, ge=1, le=14)
    budget: float | None = Field(default=None, gt=0, description="Total trip budget in INR")
    date: Date | None = None
    preferences: list[str] | None = None
    pace: str | None = Field(default=None, pattern="^(relaxed|normal|packed)$")
    travellers: int | None = Field(default=None, ge=1, le=20)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    with_routes: bool = True


class NavigateRequest(BaseModel):
    current_lat: float = Field(ge=-90, le=90)
    current_lon: float = Field(ge=-180, le=180)

    destination_id: str
    destination_lat: float = Field(ge=-90, le=90)
    destination_lon: float = Field(ge=-180, le=180)

@lru_cache(maxsize=1)
def _pois():
    csv_path = BACKEND_DIR / "data" / "delhi_pois.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"POI dataset not found: {csv_path}")
    return load_pois(str(csv_path), city="Delhi")


@lru_cache(maxsize=1)
def _osrm():
    """OSRM is optional. Without OSRM, route geometry/time is estimated locally."""
    url = os.getenv("OSRM_URL", "").strip()
    return OsrmClient(url) if url else None


def _parse(prompt: str):
    today = datetime.now(TIMEZONE).date()
    return parse_prompt(prompt, today=today)


def _preferences_model(parsed) -> TripPreferences:
    city_name = CITIES[parsed.city]["name"] if parsed.city in CITIES else None
    return TripPreferences(
        destination=city_name,
        date=parsed.start_date,
        days=parsed.days,
        budget=parsed.budget_total_inr,
        preferences=parsed.interests,
    )


@router.post("/extract", response_model=TripPreferences)
def extract_trip(request: PromptRequest):
    """Extract structured preferences using the built-in Python parser."""
    return _preferences_model(_parse(request.prompt))


def _create_plan(req: PlanRequest):
    today = datetime.now(TIMEZONE).date()
    parsed = _parse(req.prompt) if req.prompt and req.prompt.strip() else None
    start_time = parsed.start_time if parsed and parsed.start_time else "09:00"
    requested_city = req.city or (parsed.city if parsed else None) or "delhi"
    city_key = find_city(requested_city)
    if city_key not in SUPPORTED_CITIES:
        raise HTTPException(
            status_code=400,
            detail="This prototype currently supports Delhi only.",
        )

    def choose(explicit, from_prompt, default=None):
        return explicit if explicit is not None else (from_prompt if from_prompt is not None else default)

    days = choose(req.days, parsed.days if parsed else None, 1)
    if not 1 <= days <= 14:
        raise HTTPException(status_code=400, detail="Trip duration must be from 1 to 14 days.")

    budget = choose(req.budget, parsed.budget_total_inr if parsed else None)
    if budget is not None and budget <= 0:
        raise HTTPException(status_code=400, detail="Budget must be greater than zero.")

    start_date = choose(req.date, parsed.start_date if parsed else None, today)
    start_time = parsed.start_time if parsed and parsed.start_time else "09:00"
    if start_date < today:
        raise HTTPException(status_code=400, detail="Trip start date cannot be in the past.")

    interests = req.preferences if req.preferences is not None else (parsed.interests if parsed else [])
    pace = choose(req.pace, parsed.pace if parsed and parsed.pace != "normal" else None, "normal")
    travellers = choose(req.travellers, parsed.travellers if parsed and parsed.travellers != 1 else None, 1)

    centre = CITIES[city_key]["centre"]
    start_location, start_kind = resolve_start(req.lat, req.lon, centre)
    trip = TripRequest(
    days=days,
    budget_total_inr=budget,
    interests=interests,
    start_date=start_date,
    start_time=start_time,
    pace=pace,
    travellers=travellers,
    start_location=start_location,
    city=CITIES[city_key]["name"],
)

    try:
        result = plan_trip(_pois(), trip, travel=HeuristicTravel())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not generate itinerary: {exc}") from exc

    result["start"] = {
        "lat": start_location[0],
        "lon": start_location[1],
        "kind": start_kind,
    }
    if parsed and parsed.missing:
        result["warnings"].append(
            "Not detected in the prompt; defaults or structured fields used: "
            + ", ".join(parsed.missing)
        )
    if not (req.city or (parsed and parsed.city)):
        result["warnings"].append("Destination was not specified; Delhi was used.")
    if req.days is None and not (parsed and parsed.days is not None):
        result["warnings"].append("Trip duration was not specified; 1 days were used.")
    if req.date is None and not (parsed and parsed.start_date):
        result["warnings"].append("Trip date was not specified; today's date in Delhi was used.")
    if req.preferences is None and not (parsed and parsed.interests):
        result["warnings"].append("No interests were detected; recommendations use general ranking.")

    result["preferences_extracted"] = (
        _preferences_model(parsed).model_dump(mode="json") if parsed else {
            "destination": req.city,
            "date": req.date.isoformat() if req.date else None,
            "days": req.days,
            "budget": req.budget,
            "preferences": req.preferences or [],
        }
    )
    result["planning_method"] = (
        "Rule-based preference parsing, interest/popularity/cost scoring, "
        "opening-hours scheduling, budget checks and heuristic travel estimates"
    )
    if req.with_routes:
        add_routes(result, start_location, _osrm())
    return result



@router.post("/generate")
def generate_trip(request: PromptRequest):
    """Compatibility alias: returns the new full itinerary instead of the old draft."""
    return _create_plan(PlanRequest(prompt=request.prompt))



@router.post("/navigate")
def navigate_to_place(request: NavigateRequest):
    """Calculate a route from the user's current location to one selected place."""
    from datetime import datetime

    from app.services.planner.routing import score_options
    from app.services.planner.travel import haversine_km

    city_centre = CITIES["delhi"]["centre"]
    current = (request.current_lat, request.current_lon)
    destination = (request.destination_lat, request.destination_lon)

    # Apply the same Delhi boundary check used by itinerary generation.
    if haversine_km(current, city_centre) > 50:
        raise HTTPException(
            status_code=400,
            detail="Your current location is outside the supported Delhi area.",
        )

    if haversine_km(destination, city_centre) > 50:
        raise HTTPException(
            status_code=400,
            detail="The destination is outside the supported Delhi area.",
        )

    now = datetime.now(TIMEZONE)
    departure_min = now.hour * 60 + now.minute
    weekday = now.date().weekday()

    osrm = _osrm()
    options = osrm.routes(current, destination) if osrm else []

    if options:
        scored = score_options(
            options,
            departure_min,
            weekday,
            now.date(),
            congestion=None,
        )

        best_index = min(
            range(len(scored)),
            key=lambda i: scored[i]["eta_min"],
        )

        for i, option in enumerate(scored):
            option["chosen"] = i == best_index

        best = options[best_index]
        selected = scored[best_index]

        route = {
            "source": "osrm",
            "distance_km": selected["distance_km"],
            "eta_min": selected["eta_min"],
            "polyline": best.coords,
            "alternatives": scored,
        }
    else:
        # Reuse the local estimate if OSRM is unavailable.
        estimate = HeuristicTravel()
        minutes, distance = estimate.leg(
            current,
            destination,
            departure_min,
            weekday,
            now.date(),
        )

        route = {
            "source": "estimate",
            "distance_km": round(distance, 1),
            "eta_min": minutes,
            "polyline": [list(current), list(destination)],
            "alternatives": [],
        }

    route["from"] = {
        "lat": current[0],
        "lon": current[1],
    }
    route["to"] = {
        "lat": destination[0],
        "lon": destination[1],
    }
    route["destination_id"] = request.destination_id

    return route
