from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_event import BookingEvent, BookingEventType
from app.models.booking_extra import BookingExtra
from app.models.booking_passenger import BookingPassenger
from app.models.flight import Flight, FlightStatus
from app.schemas.booking import (
    BookingAddExtrasRequest,
    BookingCancelRequest,
    BookingCreate,
    BookingRescheduleRequest,
)


class BookingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_bookings(self, limit: int = 100) -> list[Booking]:
        statement = (
            select(Booking)
            .options(
                selectinload(Booking.passengers),
                selectinload(Booking.extras),
                selectinload(Booking.events),
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get_booking_by_reference(self, booking_reference: str) -> Booking:
        statement = (
            select(Booking)
            .where(Booking.booking_reference == booking_reference)
            .options(
                selectinload(Booking.passengers),
                selectinload(Booking.extras),
                selectinload(Booking.events),
            )
        )
        booking = self.session.scalar(statement)
        if booking is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
        return booking

    def create_booking(self, payload: BookingCreate) -> Booking:
        flight = self._get_flight_or_404(payload.flight_id)
        passenger_count = len(payload.passengers)
        self._ensure_flight_bookable(flight, passenger_count)

        booking = Booking(
            booking_reference=self._generate_booking_reference(),
            flight_id=flight.id,
            contact_name=payload.contact_name,
            contact_email=str(payload.contact_email),
            contact_phone=payload.contact_phone,
            total_price=Decimal("0.00"),
            status=BookingStatus.CONFIRMED,
            refund_status=RefundStatus.NOT_REQUESTED,
        )
        self.session.add(booking)
        self.session.flush()

        total_price = flight.price * passenger_count

        for passenger in payload.passengers:
            self.session.add(
                BookingPassenger(
                    booking_id=booking.id,
                    first_name=passenger.first_name,
                    last_name=passenger.last_name,
                    date_of_birth=passenger.date_of_birth,
                    passenger_type=passenger.passenger_type,
                    seat_preference=passenger.seat_preference,
                    seat_number=passenger.seat_number,
                    assistance_type=passenger.assistance_type,
                    assistance_notes=passenger.assistance_notes,
                    mobility_assistance_required=passenger.mobility_assistance_required,
                )
            )

        for extra in payload.extras:
            total_price += extra.price
            self.session.add(
                BookingExtra(
                    booking_id=booking.id,
                    extra_type=extra.extra_type,
                    quantity=extra.quantity,
                    price=extra.price,
                    description=extra.description,
                )
            )
            self._add_event(
                booking.id,
                BookingEventType.EXTRA_ADDED,
                f"Added {extra.extra_type.value}",
                extra.description,
            )

        booking.total_price = total_price.quantize(Decimal("0.01"))
        flight.booked_seats += passenger_count
        self._add_event(booking.id, BookingEventType.CREATED, "Booking created", "Booking created via API.")

        self.session.commit()
        return self.get_booking_by_reference(booking.booking_reference)

    def cancel_booking(self, booking_reference: str, payload: BookingCancelRequest) -> Booking:
        booking = self.get_booking_by_reference(booking_reference)
        if booking.status == BookingStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is already cancelled.")

        passenger_count = len(booking.passengers)
        if booking.status != BookingStatus.CANCELLED:
            booking.flight.booked_seats = max(0, booking.flight.booked_seats - passenger_count)

        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime.now(UTC)
        booking.cancellation_reason = payload.reason
        booking.refund_status = payload.refund_status
        booking.refund_amount = payload.refund_amount
        self._add_event(booking.id, BookingEventType.CANCELLED, "Booking cancelled", payload.reason)

        if payload.refund_status in {RefundStatus.PENDING, RefundStatus.APPROVED, RefundStatus.PAID}:
            self._add_event(
                booking.id,
                BookingEventType.REFUND_REQUESTED if payload.refund_status != RefundStatus.PAID else BookingEventType.REFUND_PAID,
                f"Refund {payload.refund_status.value}",
                f"Refund amount: {payload.refund_amount or Decimal('0.00')}",
            )

        self.session.commit()
        return self.get_booking_by_reference(booking_reference)

    def add_extras(self, booking_reference: str, payload: BookingAddExtrasRequest) -> Booking:
        booking = self.get_booking_by_reference(booking_reference)
        if booking.status == BookingStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot add extras to a cancelled booking.")

        for extra in payload.extras:
            booking.total_price += extra.price
            self.session.add(
                BookingExtra(
                    booking_id=booking.id,
                    extra_type=extra.extra_type,
                    quantity=extra.quantity,
                    price=extra.price,
                    description=extra.description,
                )
            )
            self._add_event(
                booking.id,
                BookingEventType.EXTRA_ADDED,
                f"Added {extra.extra_type.value}",
                extra.description,
            )

        booking.total_price = booking.total_price.quantize(Decimal("0.01"))
        self.session.commit()
        return self.get_booking_by_reference(booking_reference)

    def reschedule_booking(self, booking_reference: str, payload: BookingRescheduleRequest) -> Booking:
        current_booking = self.get_booking_by_reference(booking_reference)
        if current_booking.status == BookingStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled bookings cannot be rescheduled.")

        new_flight = self._get_flight_or_404(payload.new_flight_id)
        passenger_count = len(current_booking.passengers)
        self._ensure_flight_bookable(new_flight, passenger_count)

        current_booking.flight.booked_seats = max(0, current_booking.flight.booked_seats - passenger_count)
        current_booking.status = BookingStatus.RESCHEDULED
        self._add_event(
            current_booking.id,
            BookingEventType.RESCHEDULED,
            "Booking rescheduled",
            f"Rescheduled to flight {new_flight.flight_number}.",
        )

        new_booking = Booking(
            booking_reference=self._generate_booking_reference(),
            flight_id=new_flight.id,
            rescheduled_from_booking_id=current_booking.id,
            contact_name=current_booking.contact_name,
            contact_email=current_booking.contact_email,
            contact_phone=current_booking.contact_phone,
            total_price=Decimal("0.00"),
            status=BookingStatus.CONFIRMED,
            refund_status=RefundStatus.NOT_REQUESTED,
        )
        self.session.add(new_booking)
        self.session.flush()

        new_total = new_flight.price * passenger_count

        for passenger in current_booking.passengers:
            self.session.add(
                BookingPassenger(
                    booking_id=new_booking.id,
                    first_name=passenger.first_name,
                    last_name=passenger.last_name,
                    date_of_birth=passenger.date_of_birth,
                    passenger_type=passenger.passenger_type,
                    seat_preference=passenger.seat_preference,
                    seat_number=None,
                    assistance_type=passenger.assistance_type,
                    assistance_notes=passenger.assistance_notes,
                    mobility_assistance_required=passenger.mobility_assistance_required,
                )
            )

        for extra in current_booking.extras:
            new_total += extra.price
            self.session.add(
                BookingExtra(
                    booking_id=new_booking.id,
                    extra_type=extra.extra_type,
                    quantity=extra.quantity,
                    price=extra.price,
                    description=extra.description,
                )
            )

        new_booking.total_price = new_total.quantize(Decimal("0.01"))
        new_flight.booked_seats += passenger_count
        self._add_event(
            new_booking.id,
            BookingEventType.CREATED,
            "Rescheduled booking created",
            f"Created from booking {current_booking.booking_reference}.",
        )
        self._add_event(
            new_booking.id,
            BookingEventType.RESCHEDULED,
            "Booking confirmed on new flight",
            f"Moved from booking {current_booking.booking_reference}.",
        )

        self.session.commit()
        return self.get_booking_by_reference(new_booking.booking_reference)

    def _get_flight_or_404(self, flight_id: int) -> Flight:
        flight = self.session.get(Flight, flight_id)
        if flight is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flight not found.")
        return flight

    def _ensure_flight_bookable(self, flight: Flight, passenger_count: int) -> None:
        if flight.status != FlightStatus.SCHEDULED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Flight is not available for booking.")
        if flight.booked_seats + passenger_count > flight.capacity:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Flight does not have enough available seats.")

    def _generate_booking_reference(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            reference = "TM" + "".join(secrets.choice(alphabet) for _ in range(8))
            exists = self.session.scalar(select(Booking.id).where(Booking.booking_reference == reference))
            if exists is None:
                return reference

    def _add_event(self, booking_id: int, event_type: BookingEventType, summary: str, details: str | None) -> None:
        self.session.add(
            BookingEvent(
                booking_id=booking_id,
                event_type=event_type,
                summary=summary,
                details=details,
            )
        )
