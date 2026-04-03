from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FlightStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class SeatClass(str, enum.Enum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"


class SeatPreference(str, enum.Enum):
    WINDOW = "window"
    AISLE = "aisle"
    EXTRA_LEGROOM = "extra_legroom"


class Flight(Base):
    __tablename__ = "flights"
    __table_args__ = (
        UniqueConstraint(
            "flight_number",
            "departure_time",
            "seat_class",
            name="uq_flights_number_departure_class",
        ),
        CheckConstraint("departure_time < arrival_time", name="ck_flights_departure_before_arrival"),
        CheckConstraint(
            "check_in_open_at IS NULL OR check_in_close_at IS NULL OR check_in_open_at <= check_in_close_at",
            name="ck_flights_check_in_open_before_close",
        ),
        CheckConstraint(
            "boarding_starts_at IS NULL OR boarding_closes_at IS NULL OR boarding_starts_at <= boarding_closes_at",
            name="ck_flights_boarding_start_before_close",
        ),
        CheckConstraint(
            "boarding_closes_at IS NULL OR boarding_closes_at <= departure_time",
            name="ck_flights_boarding_close_before_departure",
        ),
        CheckConstraint("capacity > 0", name="ck_flights_capacity_positive"),
        CheckConstraint("price > 0", name="ck_flights_price_positive"),
        CheckConstraint("booked_seats >= 0", name="ck_flights_booked_seats_nonnegative"),
        CheckConstraint("booked_seats <= capacity", name="ck_flights_booked_seats_within_capacity"),
        CheckConstraint("window_seat_capacity >= 0", name="ck_flights_window_capacity_nonnegative"),
        CheckConstraint("window_seat_booked >= 0", name="ck_flights_window_booked_nonnegative"),
        CheckConstraint("window_seat_booked <= window_seat_capacity", name="ck_flights_window_booked_within_capacity"),
        CheckConstraint("aisle_seat_capacity >= 0", name="ck_flights_aisle_capacity_nonnegative"),
        CheckConstraint("aisle_seat_booked >= 0", name="ck_flights_aisle_booked_nonnegative"),
        CheckConstraint("aisle_seat_booked <= aisle_seat_capacity", name="ck_flights_aisle_booked_within_capacity"),
        CheckConstraint("extra_legroom_capacity >= 0", name="ck_flights_extra_legroom_capacity_nonnegative"),
        CheckConstraint("extra_legroom_booked >= 0", name="ck_flights_extra_legroom_booked_nonnegative"),
        CheckConstraint(
            "extra_legroom_booked <= extra_legroom_capacity",
            name="ck_flights_extra_legroom_booked_within_capacity",
        ),
        CheckConstraint(
            "window_seat_capacity + aisle_seat_capacity + extra_legroom_capacity <= capacity",
            name="ck_flights_preference_capacity_within_total_capacity",
        ),
        CheckConstraint(
            "window_seat_booked + aisle_seat_booked + extra_legroom_booked <= booked_seats",
            name="ck_flights_preference_booked_within_total_booked",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flight_number: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    origin_airport: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    destination_airport: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    departure_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    arrival_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal: Mapped[str | None] = mapped_column(String(16))
    departure_gate: Mapped[str | None] = mapped_column(String(16))
    check_in_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_in_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boarding_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boarding_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seat_class: Mapped[SeatClass] = mapped_column(Enum(SeatClass), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    booked_seats: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    window_seat_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    window_seat_booked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    aisle_seat_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    aisle_seat_booked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    extra_legroom_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    extra_legroom_booked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[FlightStatus] = mapped_column(
        Enum(FlightStatus),
        nullable=False,
        default=FlightStatus.SCHEDULED,
        server_default=FlightStatus.SCHEDULED.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    bookings = relationship("Booking", back_populates="flight")
