from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.booking import (
    BookingAddExtrasRequest,
    BookingCreate,
    BookingRead,
    BookedTripRead,
    BookingSummaryRead,
    BookingCancelRequest,
    BookingRescheduleRequest,
    RescheduleResponse,
)
from app.services.booking_service import BookingService


router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("", response_model=list[BookingSummaryRead])
def list_bookings(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[BookingSummaryRead]:
    service = BookingService(session)
    return [BookingSummaryRead.model_validate(booking) for booking in service.list_bookings(limit=limit)]


@router.get("/all-trips-booked", response_model=list[BookedTripRead])
def list_all_trips_booked(
    limit: int = Query(default=500, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[BookedTripRead]:
    service = BookingService(session)
    return [BookedTripRead.model_validate(booking) for booking in service.list_booked_trips(limit=limit)]


@router.post("", response_model=BookingRead, status_code=201)
def create_booking(payload: BookingCreate, session: Session = Depends(get_db_session)) -> BookingRead:
    service = BookingService(session)
    booking = service.create_booking(payload)
    return BookingRead.model_validate(booking)


@router.get("/{booking_reference}", response_model=BookingRead)
def get_booking(booking_reference: str, session: Session = Depends(get_db_session)) -> BookingRead:
    service = BookingService(session)
    booking = service.get_booking_by_reference(booking_reference)
    return BookingRead.model_validate(booking)


@router.post("/{booking_reference}/cancel", response_model=BookingRead)
def cancel_booking(
    booking_reference: str,
    payload: BookingCancelRequest,
    session: Session = Depends(get_db_session),
) -> BookingRead:
    service = BookingService(session)
    booking = service.cancel_booking(booking_reference, payload)
    return BookingRead.model_validate(booking)


@router.post("/{booking_reference}/reschedule", response_model=RescheduleResponse)
def reschedule_booking(
    booking_reference: str,
    payload: BookingRescheduleRequest,
    session: Session = Depends(get_db_session),
) -> RescheduleResponse:
    service = BookingService(session)
    new_booking = service.reschedule_booking(booking_reference, payload)
    return RescheduleResponse(
        previous_booking_reference=booking_reference,
        new_booking=BookingRead.model_validate(new_booking),
    )


@router.post("/{booking_reference}/extras", response_model=BookingRead)
def add_extras(
    booking_reference: str,
    payload: BookingAddExtrasRequest,
    session: Session = Depends(get_db_session),
) -> BookingRead:
    service = BookingService(session)
    booking = service.add_extras(booking_reference, payload)
    return BookingRead.model_validate(booking)
