
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Keep these categories consistent across the database and POI dataset.
POICategory = Literal[
    "attraction",
    "food",
    "cafe",
    "nightlife",
    "shopping",
    "nature",
    "entertainment",
    "religious",
]


class POI(BaseModel):
    """A point of interest stored in the local RouteSense database."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None

    # OSM identifiers may contain a type prefix, for example node/123.
    osm_id: str

    city: str
    name: str
    category: POICategory

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    # Raw opening_hours value from OpenStreetMap, if available.
    opening_hours: str | None = None

    # Estimated values, not verified prices or official visit durations.
    est_cost: float | None = Field(default=None, ge=0)
    visit_minutes: int | None = Field(default=None, gt=0)

    # A proxy based on available OSM metadata, not a user rating.
    popularity_score: float = Field(default=0.0, ge=0)

    tags: dict[str, object] = Field(default_factory=dict)

    # True when opening hours were estimated or supplied as a fallback.
    hours_estimated: bool = False

    # These flags make the provenance of cost and duration explicit.
    cost_estimated: bool = True
    visit_duration_estimated: bool = True
