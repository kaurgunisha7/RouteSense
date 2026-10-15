from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.services.planner.parser import parse_prompt

client = TestClient(app)


def test_prompt_parser_extracts_trip_fields():
    parsed = parse_prompt(
        "Plan a trip to Delhi on 15 October for 3 days with a budget of ₹10,000. "
        "I like history/monuments, cafes and shopping.",
        today=date(2026, 10, 11),
    )
    assert parsed.city == "delhi"
    assert parsed.start_date == date(2026, 10, 15)
    assert parsed.days == 3
    assert parsed.budget_total_inr == 10000
    assert "history & heritage" in parsed.interests
    assert "cafes" in parsed.interests
    assert "shopping" in parsed.interests


def test_extract_endpoint_is_model_free():
    response = client.post(
        "/api/trips/extract",
        json={"prompt": "3 days in Delhi on 15 October, ₹10000, history and cafes"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["destination"] == "Delhi"
    assert data["days"] == 3
    assert data["budget"] == 10000
    assert data["date"] == "2026-10-15"


def test_plan_endpoint_returns_timed_itinerary_within_budget():
    response = client.post(
        "/api/trips/plan",
        json={
            "prompt": "Plan a trip to Delhi on 15 October for 3 days with a budget of ₹10,000. "
            "I like history/monuments, cafes and shopping."
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["days"]) == 3
    assert data["summary"]["within_budget"] is True
    assert data["summary"]["total_spend_inr"] <= 10000
    assert all("arrive" in stop and "leave" in stop for day in data["days"] for stop in day["stops"])
    assert all("opening_hours_estimated" in stop for day in data["days"] for stop in day["stops"])
    assert data["routing"]["source"] in {"estimate", "osrm"}


def test_past_date_is_rejected():
    yesterday = (datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)).isoformat()
    response = client.post(
        "/api/trips/plan",
        json={"city": "Delhi", "date": yesterday, "days": 1, "budget": 2000},
    )
    assert response.status_code == 400
