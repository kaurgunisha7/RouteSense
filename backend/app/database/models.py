
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class User(Base):
    """Registered RouteSense user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    trips: Mapped[list["Trip"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class POI(Base):
    """A point of interest imported from OpenStreetMap."""

    __tablename__ = "pois"

    __table_args__ = (
        CheckConstraint(
            "lat >= -90 AND lat <= 90",
            name="ck_pois_latitude_range",
        ),
        CheckConstraint(
            "lon >= -180 AND lon <= 180",
            name="ck_pois_longitude_range",
        ),
        CheckConstraint(
            "est_cost IS NULL OR est_cost >= 0",
            name="ck_pois_est_cost_nonnegative",
        ),
        CheckConstraint(
            "visit_minutes IS NULL OR visit_minutes > 0",
            name="ck_pois_visit_minutes_positive",
        ),
        CheckConstraint(
            "popularity_score >= 0",
            name="ck_pois_popularity_nonnegative",
        ),
        Index("ix_pois_city_category", "city", "category"),
        Index("ix_pois_city_name", "city", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Store identifiers as text, for example node/123 or way/456.
    osm_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )

    city: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Preserve the original OSM opening_hours value.
    opening_hours: Mapped[str | None] = mapped_column(Text)

    # These values are estimates, not verified prices or durations.
    est_cost: Mapped[float | None] = mapped_column(Float)
    visit_minutes: Mapped[int | None] = mapped_column(Integer)

    popularity_score: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )

    tags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    hours_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )


class Trip(Base):
    """A saved trip belonging to a user."""

    __tablename__ = "trips"

    __table_args__ = (
        CheckConstraint("days > 0", name="ck_trips_days_positive"),
        CheckConstraint(
            "budget IS NULL OR budget >= 0",
            name="ck_trips_budget_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    budget: Mapped[float | None] = mapped_column(Float)

    # Store the extracted interests and preferences as JSON.
    preferences: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), default="planned", server_default="planned",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="trips")

    itinerary_days: Mapped[list["ItineraryDay"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="ItineraryDay.day_number",
    )


class ItineraryDay(Base):
    """One calendar day within a saved trip."""

    __tablename__ = "itinerary_days"

    __table_args__ = (
        UniqueConstraint(
            "trip_id", "day_number", name="uq_itinerary_days_trip_number"
        ),
        CheckConstraint(
            "day_number > 0", name="ck_itinerary_days_number_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    trip_id: Mapped[int] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)

    estimated_day_cost: Mapped[float | None] = mapped_column(Float)

    trip: Mapped["Trip"] = relationship(back_populates="itinerary_days")

    stops: Mapped[list["ItineraryStop"]] = relationship(
        back_populates="itinerary_day",
        cascade="all, delete-orphan",
        order_by="ItineraryStop.stop_order",
    )


class ItineraryStop(Base):
    """One POI scheduled for a particular day."""

    __tablename__ = "itinerary_stops"

    __table_args__ = (
        UniqueConstraint(
            "itinerary_day_id",
            "stop_order",
            name="uq_itinerary_stops_day_order",
        ),
        CheckConstraint(
            "stop_order > 0", name="ck_itinerary_stops_order_positive"
        ),
        CheckConstraint(
            "visit_minutes > 0",
            name="ck_itinerary_stops_visit_minutes_positive",
        ),
        CheckConstraint(
            "estimated_travel_minutes IS NULL "
            "OR estimated_travel_minutes >= 0",
            name="ck_itinerary_stops_travel_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    itinerary_day_id: Mapped[int] = mapped_column(
        ForeignKey("itinerary_days.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    poi_id: Mapped[int] = mapped_column(
        ForeignKey("pois.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    stop_order: Mapped[int] = mapped_column(Integer, nullable=False)

    planned_arrival: Mapped[time] = mapped_column(Time, nullable=False)
    planned_departure: Mapped[time] = mapped_column(Time, nullable=False)

    visit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    estimated_travel_minutes: Mapped[int | None] = mapped_column(Integer)

    estimated_cost: Mapped[float | None] = mapped_column(Float)

    # Persist provenance so estimated data is not presented as verified.
    cost_estimated: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    visit_duration_estimated: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    opening_hours_estimated: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    travel_time_estimated: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    itinerary_day: Mapped["ItineraryDay"] = relationship(
        back_populates="stops"
    )
    poi: Mapped["POI"] = relationship()


class TrafficSample(Base):
    """A traffic observation or explicitly labelled training sample."""

    __tablename__ = "traffic_samples"

    __table_args__ = (
        CheckConstraint(
            "distance_km >= 0",
            name="ck_traffic_distance_nonnegative",
        ),
        CheckConstraint(
            "free_flow_minutes > 0",
            name="ck_traffic_free_flow_positive",
        ),
        CheckConstraint(
            "observed_minutes > 0",
            name="ck_traffic_observed_positive",
        ),
        Index("ix_traffic_samples_time", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)

    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    free_flow_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    observed_minutes: Mapped[float] = mapped_column(Float, nullable=False)

    # Examples: "measured", "historical", or "synthetic".
    # The application must not treat synthetic data as real observations.
    source: Mapped[str] = mapped_column(String(100), nullable=False)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
