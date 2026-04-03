from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.db.seat_inventory import seat_inventory_counts
from app.schemas.booking import BookingSummaryRead
from app.schemas.flight import FlightRead
from app.services.booking_service import BookingService
from app.services.flight_service import FlightService


router = APIRouter(prefix="/admin", tags=["admin"])


def _to_flight_read(session: Session, flight) -> FlightRead:
    counts = seat_inventory_counts(session, flight.id)
    return FlightRead.model_validate(
        {
            **flight.__dict__,
            **counts,
        }
    )


@router.get("/flights", response_model=list[FlightRead])
def admin_list_flights(
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_db_session),
) -> list[FlightRead]:
    service = FlightService(session)
    return [_to_flight_read(session, flight) for flight in service.list_flights(limit=limit)]


@router.get("/bookings", response_model=list[BookingSummaryRead])
def admin_list_bookings(
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_db_session),
) -> list[BookingSummaryRead]:
    service = BookingService(session)
    return [BookingSummaryRead.model_validate(booking) for booking in service.list_bookings(limit=limit)]
