from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.flight import FlightStatus, SeatClass


class FlightRead(BaseModel):
    id: int
    flight_number: str
    origin_airport: str
    destination_airport: str
    departure_time: datetime
    arrival_time: datetime
    terminal: str | None
    departure_gate: str | None
    check_in_open_at: datetime | None
    check_in_close_at: datetime | None
    boarding_starts_at: datetime | None
    boarding_closes_at: datetime | None
    seat_class: SeatClass
    price: Decimal
    capacity: int
    booked_seats: int
    available_seats: int
    window_seat_capacity: int
    window_seat_booked: int
    window_seat_available: int
    aisle_seat_capacity: int
    aisle_seat_booked: int
    aisle_seat_available: int
    extra_legroom_capacity: int
    extra_legroom_booked: int
    extra_legroom_available: int
    status: FlightStatus

    model_config = {"from_attributes": True}
