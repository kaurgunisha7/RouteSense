"""Supported cities. Add a city here + import its POIs + build its OSRM table."""
CITIES = {
    "delhi":     {"name": "Delhi",     "centre": (28.6315, 77.2167), "aliases": ["new delhi", "ncr", "dilli"]},
    "hyderabad": {"name": "Hyderabad", "centre": (17.3850, 78.4867), "aliases": ["hyd", "secunderabad"]},
    "pune":      {"name": "Pune",      "centre": (18.5204, 73.8567), "aliases": []},
    "mumbai":    {"name": "Mumbai",    "centre": (19.0760, 72.8777), "aliases": ["bombay"]},
}
MAX_DISTANCE_FROM_CITY_KM = 50      # user GPS farther than this -> start from the city centre


def find_city(text: str) -> str | None:
    t = text.lower()
    for key, c in CITIES.items():
        if key in t or any(a in t for a in c["aliases"]):
            return key
    return None
