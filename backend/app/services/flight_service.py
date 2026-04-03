from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import Select, exists, select
from sqlalchemy.orm import Session

from app.models.flight import Flight, FlightStatus, SeatClass, SeatPreference
from app.models.seat_inventory import SeatInventory


class FlightService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_flights(self, limit: int = 100) -> list[Flight]:
        statement = select(Flight).order_by(Flight.departure_time, Flight.flight_number).limit(limit)
        return list(self.session.scalars(statement))

    def get_flight(self, flight_id: int) -> Flight | None:
        return self.session.get(Flight, flight_id)

    def search_flights(
        self,
        *,
        origin: str | None = None,
        destination: str | None = None,
        departure_date_from: date | None = None,
        departure_date_to: date | None = None,
        max_price: float | None = None,
        seat_class: SeatClass | None = None,
        seat_preference: SeatPreference | None = None,
        sort_by: str = "departure_time",
        only_available: bool = True,
        limit: int = 100,
    ) -> list[Flight]:
        statement: Select[tuple[Flight]] = select(Flight).where(Flight.status == FlightStatus.SCHEDULED)

        if origin:
            statement = statement.where(Flight.origin_airport == origin.upper())
        if destination:
            statement = statement.where(Flight.destination_airport == destination.upper())
        if departure_date_from:
            start = datetime.combine(departure_date_from, time.min)
            statement = statement.where(Flight.departure_time >= start)
        if departure_date_to:
            end = datetime.combine(departure_date_to, time.max)
            statement = statement.where(Flight.departure_time <= end)
        if max_price is not None:
            statement = statement.where(Flight.price <= max_price)
        if seat_class:
            statement = statement.where(Flight.seat_class == seat_class)
        if only_available:
            statement = statement.where(
                exists(
                    select(1).where(
                        SeatInventory.flight_id == Flight.id,
                        SeatInventory.is_booked.is_(False),
                    )
                )
            )
        if seat_preference is not None:
            statement = statement.where(
                exists(
                    select(1).where(
                        SeatInventory.flight_id == Flight.id,
                        SeatInventory.is_booked.is_(False),
                        SeatInventory.seat_type == seat_preference.value,
                    )
                )
            )

        if sort_by == "price":
            statement = statement.order_by(Flight.price, Flight.departure_time)
        else:
            statement = statement.order_by(Flight.departure_time, Flight.price)

        statement = statement.limit(limit)
        return list(self.session.scalars(statement))
