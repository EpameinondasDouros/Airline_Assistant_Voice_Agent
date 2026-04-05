from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.db.seat_inventory import seat_inventory_counts
from app.models.flight import Flight, SeatClass, SeatPreference
from app.models.seat_inventory import SeatInventory
from app.schemas.flight import FlightRead
from app.schemas.seat_inventory import SeatInventoryRead
from app.services.flight_service import FlightService


router = APIRouter(prefix="/flights", tags=["flights"])


def _to_flight_read(session: Session, flight) -> FlightRead:
    counts = seat_inventory_counts(session, flight.id)
    return FlightRead.model_validate(
        {
            **flight.__dict__,
            **counts,
        }
    )


@router.get("", response_model=list[FlightRead])
def list_flights(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[FlightRead]:
    service = FlightService(session)
    return [_to_flight_read(session, flight) for flight in service.list_flights(limit=limit)]


@router.get("/search", response_model=list[FlightRead])
def search_flights(
    origin: str | None = Query(default=None, min_length=3, max_length=3),
    destination: str | None = Query(default=None, min_length=3, max_length=3),
    departure_date_from: date | None = None,
    departure_date_to: date | None = None,
    max_price: float | None = Query(default=None, ge=0),
    seat_class: SeatClass | None = None,
    seat_preference: SeatPreference | None = None,
    sort_by: str = Query(default="departure_time", pattern="^(departure_time|price)$"),
    only_available: bool = True,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> list[FlightRead]:
    
    raise HTTPException(status_code=503, detail="Flight search is temporarily unavailable.")

    service = FlightService(session)
    service = FlightService(session)
    flights = service.search_flights(
        origin=origin,
        destination=destination,
        departure_date_from=departure_date_from,
        departure_date_to=departure_date_to,
        max_price=max_price,
        seat_class=seat_class,
        seat_preference=seat_preference,
        sort_by=sort_by,
        only_available=only_available,
        limit=limit,
    )
    return [_to_flight_read(session, flight) for flight in flights]


@router.get("/{flight_id}", response_model=FlightRead)
def get_flight(flight_id: int, session: Session = Depends(get_db_session)) -> FlightRead:
    service = FlightService(session)
    flight = service.get_flight(flight_id)
    if flight is None:
        raise HTTPException(status_code=404, detail="Flight not found.")
    return _to_flight_read(session, flight)


@router.get("/{flight_id}/seats", response_model=list[SeatInventoryRead])
def get_flight_seats(flight_id: int, session: Session = Depends(get_db_session)) -> list[SeatInventoryRead]:
    flight = session.get(Flight, flight_id)
    if flight is None:
        raise HTTPException(status_code=404, detail="Flight not found.")
    seats = session.scalars(
        select(SeatInventory).where(SeatInventory.flight_id == flight_id).order_by(SeatInventory.seat_number)
    )
    return [SeatInventoryRead.model_validate(seat) for seat in seats]
