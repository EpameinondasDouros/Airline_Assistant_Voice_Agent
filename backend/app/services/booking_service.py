from __future__ import annotations

import secrets
import string
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_event import BookingEvent, BookingEventType
from app.models.booking_extra import BookingExtra, ExtraType
from app.models.booking_passenger import BookingPassenger
from app.models.flight import Flight, FlightStatus, SeatPreference
from app.models.seat_inventory import SeatInventory
from app.db.seat_inventory import refresh_flight_seat_state, seat_inventory_counts
from app.schemas.booking import (
    BookingAddExtrasRequest,
    BookingCancelRequest,
    BookingCreate,
    BookingRescheduleRequest,
)


UNRESOLVED_REFUND_STATUSES = {
    RefundStatus.PENDING,
    RefundStatus.APPROVED,
    RefundStatus.PAID,
}

SHORT_HAUL_CHECKED_BAG_FEE = Decimal("35.00")
LONG_HAUL_CHECKED_BAG_FEE = Decimal("70.00")
SPORTS_EQUIPMENT_FEE = Decimal("55.00")
PET_FEE = Decimal("90.00")
CABIN_BAG_FEE = Decimal("20.00")
SPECIAL_ITEM_FEE = Decimal("45.00")


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

    def list_booked_trips(self, limit: int = 500) -> list[Booking]:
        statement = (
            select(Booking)
            .join(Booking.flight)
            .where(Booking.status == BookingStatus.CONFIRMED)
            .options(
                joinedload(Booking.flight),
                selectinload(Booking.passengers),
                selectinload(Booking.extras),
            )
            .order_by(Flight.departure_time.asc(), Booking.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get_booking_by_reference(self, booking_reference: str) -> Booking:
        statement = (
            select(Booking)
            .where(Booking.booking_reference == booking_reference)
            .options(
                joinedload(Booking.flight),
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
        self._ensure_unique_passengers_in_request(payload.passengers)

        self._ensure_no_duplicate_or_refund_conflicts(flight, payload.passengers)
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
            inventory = self._seat_inventory_for_seat(flight.id, assigned_seat_number)
            if inventory is not None:
                inventory.is_booked = True
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
            extra_price = self._resolved_extra_price(flight, extra)
            total_price += extra_price
            self.session.add(
                BookingExtra(
                    booking_id=booking.id,
                    extra_type=extra.extra_type,
                    quantity=extra.quantity,
                    price=extra_price,
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
        refresh_flight_seat_state(self.session, flight)
        self._add_event(booking.id, BookingEventType.CREATED, "Booking created", "Booking created via API.")

        self.session.commit()
        return self.get_booking_by_reference(booking.booking_reference)

    def cancel_booking(self, booking_reference: str, payload: BookingCancelRequest) -> Booking:
        booking = self.get_booking_by_reference(booking_reference)
        if booking.status == BookingStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is already cancelled.")

        if booking.status != BookingStatus.CANCELLED:
            for passenger in booking.passengers:
                if passenger.seat_number:
                    inventory = self._seat_inventory_for_seat(booking.flight.id, passenger.seat_number.upper().strip())
                    if inventory is not None:
                        inventory.is_booked = False

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

        refresh_flight_seat_state(self.session, booking.flight)
        self.session.commit()
        return self.get_booking_by_reference(booking_reference)

    def add_extras(self, booking_reference: str, payload: BookingAddExtrasRequest) -> Booking:
        booking = self.get_booking_by_reference(booking_reference)
        if booking.status == BookingStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot add extras to a cancelled booking.")

        for extra in payload.extras:
            extra_price = self._resolved_extra_price(booking.flight, extra)
            booking.total_price += extra_price
            self.session.add(
                BookingExtra(
                    booking_id=booking.id,
                    extra_type=extra.extra_type,
                    quantity=extra.quantity,
                    price=extra_price,
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
        self._ensure_no_duplicate_or_refund_conflicts(new_flight, current_booking.passengers)
        self._ensure_flight_bookable(new_flight, passenger_count)
        self._ensure_preferences_available(new_flight, current_booking.passengers)

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
            if passenger.seat_number:
                current_inventory = self._seat_inventory_for_seat(current_booking.flight.id, passenger.seat_number.upper().strip())
                if current_inventory is not None:
                    current_inventory.is_booked = False
            assigned_seat_number = self._assign_default_seat_number(new_flight, passenger.seat_preference)
            new_inventory = self._seat_inventory_for_seat(new_flight.id, assigned_seat_number)
            if new_inventory is not None:
                new_inventory.is_booked = True
            self.session.add(
                BookingPassenger(
                    booking_id=new_booking.id,
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
        refresh_flight_seat_state(self.session, current_booking.flight)
        refresh_flight_seat_state(self.session, new_flight)
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
        inventory_counts = seat_inventory_counts(self.session, flight.id)
        if inventory_counts["available_seats"] < passenger_count:
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

        inventory_counts = seat_inventory_counts(self.session, flight.id)
        availability = {
            SeatPreference.WINDOW: inventory_counts["window_seat_available"],
            SeatPreference.AISLE: inventory_counts["aisle_seat_available"],
            SeatPreference.EXTRA_LEGROOM: inventory_counts["extra_legroom_available"],
        }

        for preference, count in requested.items():
            if count > availability[preference]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Flight does not have enough {preference.value} seats available.",
                )

    def _ensure_seat_numbers_valid(self, flight: Flight, passengers: list[BookingPassenger] | list) -> None:
        for passenger in passengers:
            seat_number = getattr(passenger, "seat_number", None)
            if seat_number is None:
                continue
            normalized_seat_number = seat_number.upper().strip()
            inventory = self._seat_inventory_for_seat(flight.id, normalized_seat_number)
            if inventory is None or inventory.cabin != flight.seat_class.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat_number} is not valid for {flight.seat_class.value.replace('_', ' ')}.",
                )
            preference = self._normalize_preference(getattr(passenger, "seat_preference", None))
            if preference is not None and inventory.seat_type != preference.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat_number} does not match the selected {preference.value.replace('_', ' ')} preference.",
                )
            if inventory.is_booked or self._seat_number_taken(flight.id, normalized_seat_number):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat_number} is already booked for this flight.",
                )

    def _assign_default_seat_number(self, flight: Flight, preference: object | None) -> str:
        preference_value = self._normalize_preference(preference)
        statement = select(SeatInventory).where(
            SeatInventory.flight_id == flight.id,
            SeatInventory.cabin == flight.seat_class.value,
            SeatInventory.is_booked.is_(False),
        )
        if preference_value is not None:
            statement = statement.where(SeatInventory.seat_type == preference_value.value)
        statement = statement.order_by(SeatInventory.id.asc())
        inventory = self.session.scalar(statement)
        if inventory is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No seats available for the selected preference.")
        return inventory.seat_number

    def _ensure_unique_passengers_in_request(self, passengers: list[object]) -> None:
        seen_identities: set[tuple[str, str, date]] = set()
        for passenger in passengers:
            identity = self._passenger_identity(passenger)
            if identity in seen_identities:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Duplicate passenger entries are not allowed in the same booking request.",
                )
            seen_identities.add(identity)

    def _ensure_no_duplicate_or_refund_conflicts(self, flight: Flight, passengers: list[object]) -> None:
        requested_identities = {self._passenger_identity(passenger) for passenger in passengers}
        candidate_bookings = self.session.scalars(
            select(Booking)
            .where(Booking.flight_id == flight.id)
            .options(selectinload(Booking.passengers))
        )

        for booking in candidate_bookings:
            if booking.status == BookingStatus.RESCHEDULED:
                continue

            passenger_identities = {
                self._passenger_identity(passenger)
                for passenger in booking.passengers
                if passenger.date_of_birth is not None
            }
            matching_identities = requested_identities.intersection(passenger_identities)
            if not matching_identities:
                continue

            if booking.status == BookingStatus.CONFIRMED:
                identity = next(iter(matching_identities))
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=self._duplicate_booking_message(identity),
                )

            if booking.refund_status in UNRESOLVED_REFUND_STATUSES:
                identity = next(iter(matching_identities))
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=self._refund_block_message(identity),
                )

    def _passenger_identity(self, passenger: object) -> tuple[str, str, date]:
        first_name = self._normalize_name(getattr(passenger, "first_name", ""))
        last_name = self._normalize_name(getattr(passenger, "last_name", ""))
        date_of_birth = getattr(passenger, "date_of_birth", None)
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passenger first and last name are required.",
            )
        if date_of_birth is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passenger date of birth is required to prevent duplicate bookings.",
            )
        return first_name, last_name, date_of_birth

    def _normalize_name(self, value: object) -> str:
        return " ".join(str(value).split()).casefold()

    def _duplicate_booking_message(self, identity: tuple[str, str, date]) -> str:
        first_name, last_name, date_of_birth = identity
        return (
            "Passenger "
            f"{first_name.title()} {last_name.title()} ({date_of_birth.isoformat()}) already has a booking on this flight."
        )

    def _refund_block_message(self, identity: tuple[str, str, date]) -> str:
        first_name, last_name, date_of_birth = identity
        return (
            "Passenger "
            f"{first_name.title()} {last_name.title()} ({date_of_birth.isoformat()}) has an unresolved refund on this flight."
        )

    def _seat_number_taken(self, flight_id: int, seat_number: str) -> bool:
        statement = select(BookingPassenger.id).join(Booking).where(
            Booking.flight_id == flight_id,
            BookingPassenger.seat_number == seat_number,
            Booking.status == BookingStatus.CONFIRMED,
        )
        return self.session.scalar(statement) is not None

    def _seat_inventory_for_seat(self, flight_id: int, seat_number: str) -> SeatInventory | None:
        statement = select(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.seat_number == seat_number,
        )
        return self.session.scalar(statement)

    def _normalize_preference(self, preference: object) -> SeatPreference | None:
        if preference is None:
            return None
        if isinstance(preference, SeatPreference):
            return preference
        try:
            return SeatPreference(str(preference))
        except ValueError:
            return None

    def _resolved_extra_price(self, flight: Flight, extra: object) -> Decimal:
        provided_price = getattr(extra, "price", None)
        if provided_price is not None and Decimal(provided_price) > Decimal("0.00"):
            return Decimal(provided_price).quantize(Decimal("0.01"))
        return self._default_extra_price(
            flight,
            getattr(extra, "extra_type", None),
            quantity=int(getattr(extra, "quantity", 1) or 1),
            description=getattr(extra, "description", None),
        )

    def _default_extra_price(
        self,
        flight: Flight,
        extra_type: ExtraType | str | None,
        *,
        quantity: int,
        description: str | None,
    ) -> Decimal:
        normalized_quantity = max(quantity, 1)
        if isinstance(extra_type, ExtraType):
            normalized_type = extra_type
        else:
            normalized_type = ExtraType(str(extra_type))

        if normalized_type == ExtraType.CHECKED_BAG:
            unit_price = LONG_HAUL_CHECKED_BAG_FEE if self._is_long_haul(flight) else SHORT_HAUL_CHECKED_BAG_FEE
            return (unit_price * normalized_quantity).quantize(Decimal("0.01"))
        if normalized_type == ExtraType.SPORTS_EQUIPMENT:
            return (SPORTS_EQUIPMENT_FEE * normalized_quantity).quantize(Decimal("0.01"))
        if normalized_type == ExtraType.CABIN_BAG:
            return (CABIN_BAG_FEE * normalized_quantity).quantize(Decimal("0.01"))
        if normalized_type == ExtraType.PET:
            return (PET_FEE * normalized_quantity).quantize(Decimal("0.01"))
        if normalized_type == ExtraType.PRAM:
            return Decimal("0.00")
        if normalized_type == ExtraType.SPECIAL_ITEM:
            if description and any(token in description.lower() for token in ("wheelchair", "mobility aid", "medical")):
                return Decimal("0.00")
            return (SPECIAL_ITEM_FEE * normalized_quantity).quantize(Decimal("0.01"))
        return Decimal("0.00")

    def _is_long_haul(self, flight: Flight) -> bool:
        duration = flight.arrival_time - flight.departure_time
        return duration.total_seconds() >= 6 * 60 * 60

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
