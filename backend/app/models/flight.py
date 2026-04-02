from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FlightStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class SeatClass(str, enum.Enum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"


class Flight(Base):
    __tablename__ = "flights"
    __table_args__ = (
        UniqueConstraint(
            "flight_number",
            "departure_time",
            "seat_class",
            name="uq_flights_number_departure_class",
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
