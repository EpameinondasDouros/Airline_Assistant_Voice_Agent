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
from app.models.flight import Flight, FlightStatus, SeatPreference
from app.schemas.booking import (
    BookingAddExtrasRequest,
    BookingCancelRequest,
    BookingCreate,
    BookingRescheduleRequest,
)


SEAT_LAYOUTS: dict[str, dict[str, object]] = {
    "economy": {
        "rows": range(10, 30),
        "columns": ("A", "B", "C", "D", "E", "F"),
        "window_columns": {"A", "F"},
        "aisle_columns": {"C", "D"},
        "extra_legroom_rows": {27, 28, 29},
    },
    "premium_economy": {
        "rows": range(5, 10),
        "columns": ("A", "B", "C", "D", "E", "F"),
        "window_columns": {"A", "F"},
        "aisle_columns": {"C", "D"},
        "extra_legroom_rows": {5, 6, 7, 8, 9},
    },
    "business": {
        "rows": range(1, 5),
        "columns": ("A", "B", "C", "D"),
        "window_columns": {"A", "D"},
        "aisle_columns": {"B", "C"},
        "extra_legroom_rows": {1, 2, 3, 4},
    },
}


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
        self._ensure_preferences_available(flight, payload.passengers)
        self._ensure_seat_numbers_valid(flight, payload.passengers)

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
            assigned_seat_number = (
                passenger.seat_number.upper().strip()
                if passenger.seat_number
                else self._assign_default_seat_number(flight, passenger.seat_preference)
            )
            self.session.add(
                BookingPassenger(
                    booking_id=booking.id,
                    first_name=passenger.first_name,
                    last_name=passenger.last_name,
                    date_of_birth=passenger.date_of_birth,
                    passenger_type=passenger.passenger_type,
                    seat_preference=passenger.seat_preference,
                    seat_number=assigned_seat_number,
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
        self._apply_preference_counts(flight, payload.passengers, delta=1)
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
            self._apply_preference_counts(booking.flight, booking.passengers, delta=-1)

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
        self._ensure_preferences_available(new_flight, current_booking.passengers)

        current_booking.flight.booked_seats = max(0, current_booking.flight.booked_seats - passenger_count)
        self._apply_preference_counts(current_booking.flight, current_booking.passengers, delta=-1)
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
        self._apply_preference_counts(new_flight, current_booking.passengers, delta=1)
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

    def _ensure_preferences_available(self, flight: Flight, passengers: list[BookingPassenger] | list) -> None:
        requested = {
            SeatPreference.WINDOW: 0,
            SeatPreference.AISLE: 0,
            SeatPreference.EXTRA_LEGROOM: 0,
        }
        for passenger in passengers:
            preference = self._normalize_preference(getattr(passenger, "seat_preference", None))
            if preference is not None:
                requested[preference] += 1

        availability = {
            SeatPreference.WINDOW: flight.window_seat_capacity - flight.window_seat_booked,
            SeatPreference.AISLE: flight.aisle_seat_capacity - flight.aisle_seat_booked,
            SeatPreference.EXTRA_LEGROOM: flight.extra_legroom_capacity - flight.extra_legroom_booked,
        }

        for preference, count in requested.items():
            if count > availability[preference]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Flight does not have enough {preference.value} seats available.",
                )

    def _ensure_seat_numbers_valid(self, flight: Flight, passengers: list[BookingPassenger] | list) -> None:
        layout = self._seat_layout_for_class(flight.seat_class.value)
        for passenger in passengers:
            seat_number = getattr(passenger, "seat_number", None)
            if seat_number is None:
                continue
            normalized_seat_number = seat_number.upper().strip()
            if not self._seat_number_allowed_for_class(layout, normalized_seat_number):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat_number} is not valid for {flight.seat_class.value.replace('_', ' ')}.",
                )
            preference = self._normalize_preference(getattr(passenger, "seat_preference", None))
            seat_type = self._seat_type_for_number(layout, normalized_seat_number)
            if preference is not None and seat_type is not None and preference != seat_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat_number} does not match the selected {preference.value.replace('_', ' ')} preference.",
                )
            if self._seat_number_taken(flight.id, normalized_seat_number):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat_number} is already booked for this flight.",
                )

    def _assign_default_seat_number(self, flight: Flight, preference: object | None) -> str:
        seat_class = flight.seat_class.value
        layout = self._seat_layout_for_class(seat_class)
        preference_value = self._normalize_preference(preference)
        if preference_value == SeatPreference.WINDOW:
            return self._next_seat_from_pool(flight.id, layout, columns=layout["window_columns"], rows=layout["rows"])
        if preference_value == SeatPreference.AISLE:
            return self._next_seat_from_pool(flight.id, layout, columns=layout["aisle_columns"], rows=layout["rows"])
        if preference_value == SeatPreference.EXTRA_LEGROOM:
            return self._next_seat_from_pool(
                flight.id,
                layout,
                columns=layout["columns"],
                rows=layout["extra_legroom_rows"],
            )
        return self._next_seat_from_pool(flight.id, layout, columns=layout["columns"], rows=layout["rows"])

    def _seat_layout_for_class(self, seat_class: str) -> dict[str, object]:
        layout = SEAT_LAYOUTS.get(seat_class)
        if layout is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported seat class: {seat_class}.")
        return layout

    def _seat_number_taken(self, flight_id: int, seat_number: str) -> bool:
        statement = select(BookingPassenger.id).join(Booking).where(
            Booking.flight_id == flight_id,
            BookingPassenger.seat_number == seat_number,
        )
        return self.session.scalar(statement) is not None

    def _next_seat_from_pool(
        self,
        flight_id: int,
        layout: dict[str, object],
        *,
        columns: tuple[str, ...] | set[str],
        rows: range | set[int],
    ) -> str:
        # Deterministic seat choice for the seeded demo data; prevents over-allocating a class/pattern.
        ordered_rows = sorted(rows)
        ordered_columns = [column for column in layout["columns"] if column in columns]
        for row in ordered_rows:
            for column in ordered_columns:
                candidate = f"{row}{column}"
                if not self._seat_number_taken(flight_id, candidate):
                    return candidate
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No seats available for the selected preference.")

    def _seat_number_allowed_for_class(self, layout: dict[str, object], seat_number: str) -> bool:
        seat_number = seat_number.upper().strip()
        row_part = "".join(ch for ch in seat_number if ch.isdigit())
        col_part = "".join(ch for ch in seat_number if ch.isalpha())
        if not row_part or not col_part:
            return False
        row = int(row_part)
        column = col_part[-1]
        return row in layout["rows"] and column in layout["columns"]

    def _seat_type_for_number(self, layout: dict[str, object], seat_number: str) -> SeatPreference | None:
        seat_number = seat_number.upper().strip()
        row_part = "".join(ch for ch in seat_number if ch.isdigit())
        col_part = "".join(ch for ch in seat_number if ch.isalpha())
        if not row_part or not col_part:
            return None
        row = int(row_part)
        column = col_part[-1]
        if row not in layout["rows"] or column not in layout["columns"]:
            return None
        if column in layout["window_columns"]:
            return SeatPreference.WINDOW
        if column in layout["aisle_columns"]:
            return SeatPreference.AISLE
        if row in layout["extra_legroom_rows"]:
            return SeatPreference.EXTRA_LEGROOM
        return None

    def _apply_preference_counts(self, flight: Flight, passengers: list[BookingPassenger] | list, *, delta: int) -> None:
        for passenger in passengers:
            preference = self._normalize_preference(getattr(passenger, "seat_preference", None))
            if preference == SeatPreference.WINDOW:
                flight.window_seat_booked = max(0, flight.window_seat_booked + delta)
            elif preference == SeatPreference.AISLE:
                flight.aisle_seat_booked = max(0, flight.aisle_seat_booked + delta)
            elif preference == SeatPreference.EXTRA_LEGROOM:
                flight.extra_legroom_booked = max(0, flight.extra_legroom_booked + delta)

    def _normalize_preference(self, preference: object) -> SeatPreference | None:
        if preference is None:
            return None
        if isinstance(preference, SeatPreference):
            return preference
        try:
            return SeatPreference(str(preference))
        except ValueError:
            return None

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
