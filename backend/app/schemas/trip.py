from datetime import date as Date
from pydantic import BaseModel, Field


class TripPreferences(BaseModel):
    destination: str | None = Field(
        description="The destination mentioned by the user, or null if not provided."
    )

    date: Date | None = Field(
        description="The starting date of the trip, or null if not provided."
    )

    days: int | None = Field(
        description="Number of travel days, or null if not provided."
    )

    budget: float | None = Field(
        description="Maximum or stated trip budget, or null if not provided."
    )

    preferences: list[str] = Field(
        description="The user's stated interests and travel preferences. Return an empty list if none are provided."
    )