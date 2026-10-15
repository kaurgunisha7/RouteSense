# RouteSense Backend (planner integration)

This version uses the built-in Python prompt parser and timed itinerary planner. **Ollama and hosted language-model APIs are not required.**

## Features

- Extracts destination, date, duration, budget, interests, pace, and traveller count from natural-language prompts using deterministic Python rules.
- Uses the curated Delhi POI CSV at `data/delhi_pois.csv`.
- Ranks places using interest/category/tag match, popularity, and estimated cost.
- Schedules stops against known opening hours and estimates travel time with a local heuristic.
- Returns route estimates by default; set `OSRM_URL` to use a reachable OSRM server for route geometry and road distances.
- Flags estimated or missing opening hours, prices, and visit durations.
- Keeps the existing database models and Alembic migrations for later persistence work; trip planning itself does not require a database connection.

## Setup (Windows PowerShell)

```powershell
cd Backend
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to test the API.

Run the checks with `python -m pytest -q`. The scenario smoke-test can also be run with `python tests/test_planner_scenarios.py` from the Backend folder (or `PYTHONPATH=. python tests/test_planner_scenarios.py` on shells that do not add the project root to `sys.path`).

## Endpoints

- `POST /api/trips/extract` — parses a prompt into structured preferences.
- `POST /api/trips/plan` — recommended endpoint; returns the full timed itinerary.
- `POST /api/trips/generate` — compatibility alias returning the same full itinerary as `/plan`.

Example body:

```json
{
  "prompt": "Plan 3 days in Delhi from 15 October with a budget of ₹10000. I like history and monuments, cafes, and shopping."
}
```

The planner currently has curated POI data for Delhi only. Dates in the past are rejected. If no date is provided, the current date in the Asia/Kolkata timezone is used. Missing budget defaults to the planner's ₹3,000/day estimate and is disclosed in warnings.

## Data and accuracy notes

- `data/delhi_pois.csv` is the only POI source used by the planner.
- Opening-hour rules are parsed from the CSV. If hours are unknown, the planner uses 09:00–18:00 as a scheduling fallback and flags the uncertainty. It does not verify live opening status or temporary closures.
- Costs, visit durations, and traffic are estimates. The returned warnings and per-stop flags preserve that distinction.
- If `OSRM_URL` is unset or unreachable, route geometry and ETA use the local heuristic; they are estimates, not live traffic.

## Database configuration

Trip planning works without PostgreSQL. The existing database models and Alembic migrations are retained for future account and saved-trip features. To use those features, copy `.env.example` to `.env`, set a valid `DATABASE_URL`, and configure PostgreSQL. Never commit `.env` or share credentials.
