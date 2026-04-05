from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.flight_schema import ensure_flight_seat_columns
from app.db.seat_inventory import reconcile_seat_state, sync_seat_inventory
from app.db.session import SessionLocal, engine
from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_event import BookingEvent, BookingEventType
from app.models.booking_extra import BookingExtra, ExtraType
from app.models.booking_passenger import BookingPassenger
from app.models.flight import Flight, SeatClass


@dataclass(frozen=True)
class PassengerSeed:
    first_name: str
    last_name: str
    date_of_birth: date
    passenger_type: str = "adult"
    seat_preference: str | None = None
    seat_number: str | None = None
    assistance_type: str | None = None
    assistance_notes: str | None = None
    mobility_assistance_required: bool = False


@dataclass(frozen=True)
class ExtraSeed:
    extra_type: ExtraType
    quantity: int
    price: Decimal
    description: str | None = None


@dataclass(frozen=True)
class BookingSeed:
    booking_reference: str
    flight_number: str
    departure_time: datetime
    seat_class: SeatClass
    contact_name: str
    contact_email: str
    contact_phone: str
    status: BookingStatus
    passengers: tuple[PassengerSeed, ...]
    refund_status: RefundStatus = RefundStatus.NOT_REQUESTED
    refund_amount: Decimal | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    rescheduled_from_reference: str | None = None
    extras: tuple[ExtraSeed, ...] = ()


BOOKING_SEEDS = (
    BookingSeed(
        booking_reference="TMX4A92K",
        flight_number="TM101",
        departure_time=datetime(2026, 4, 6, 8, 15),
        seat_class=SeatClass.ECONOMY,
        contact_name="Maya Patel",
        contact_email="maya.patel@example.com",
        contact_phone="+30-694-111-2233",
        status=BookingStatus.CONFIRMED,
        passengers=(
            PassengerSeed("Maya", "Patel", date(1990, 5, 14), seat_preference="window", seat_number="18A"),
        ),
        extras=(
            ExtraSeed(ExtraType.CHECKED_BAG, 1, Decimal("35.00")),
        ),
    ),
    BookingSeed(
        booking_reference="TMQ7L5N8",
        flight_number="TM206",
        departure_time=datetime(2026, 4, 7, 15, 20),
        seat_class=SeatClass.PREMIUM_ECONOMY,
        contact_name="Luca Rossi",
        contact_email="luca.rossi@example.com",
        contact_phone="+39-347-555-1001",
        status=BookingStatus.CONFIRMED,
        passengers=(
            PassengerSeed("Luca", "Rossi", date(1985, 2, 3), seat_preference="aisle", seat_number="7C"),
            PassengerSeed("Giulia", "Rossi", date(1987, 11, 19), seat_preference="aisle", seat_number="7D"),
        ),
        extras=(
            ExtraSeed(ExtraType.CHECKED_BAG, 2, Decimal("70.00")),
            ExtraSeed(ExtraType.PRAM, 1, Decimal("0.00"), "folding stroller"),
        ),
    ),
    BookingSeed(
        booking_reference="TMP3D6W1",
        flight_number="TM412",
        departure_time=datetime(2026, 4, 8, 18, 40),
        seat_class=SeatClass.BUSINESS,
        contact_name="Ava Johnson",
        contact_email="ava.johnson@example.com",
        contact_phone="+1-917-555-0188",
        status=BookingStatus.CONFIRMED,
        passengers=(
            PassengerSeed(
                "Ava",
                "Johnson",
                date(1978, 8, 22),
                seat_preference="aisle",
                seat_number="3C",
                assistance_type="wheelchair",
                assistance_notes="wheelchair support from check-in to boarding",
                mobility_assistance_required=True,
            ),
        ),
        extras=(
            ExtraSeed(ExtraType.SPECIAL_ITEM, 1, Decimal("0.00"), "manual wheelchair"),
        ),
    ),
    BookingSeed(
        booking_reference="TMB8R4C7",
        flight_number="TM520",
        departure_time=datetime(2026, 4, 9, 7, 30),
        seat_class=SeatClass.ECONOMY,
        contact_name="Sofia Hernandez",
        contact_email="sofia.hernandez@example.com",
        contact_phone="+34-611-222-778",
        status=BookingStatus.CANCELLED,
        refund_status=RefundStatus.PAID,
        refund_amount=Decimal("105.00"),
        cancelled_at=datetime(2026, 4, 4, 11, 30),
        cancellation_reason="customer requested cancellation within the refund window",
        passengers=(
            PassengerSeed("Sofia", "Hernandez", date(1994, 1, 9), seat_preference="window"),
        ),
        extras=(),
    ),
    BookingSeed(
        booking_reference="TMR6K2S1",
        flight_number="TM630",
        departure_time=datetime(2026, 4, 8, 14, 0),
        seat_class=SeatClass.PREMIUM_ECONOMY,
        contact_name="Omar Al Mansoori",
        contact_email="omar.almansoori@example.com",
        contact_phone="+971-50-777-2201",
        status=BookingStatus.CANCELLED,
        cancelled_at=datetime(2026, 4, 5, 9, 0),
        cancellation_reason="rescheduled to a later departure",
        passengers=(
            PassengerSeed("Omar", "Al Mansoori", date(1988, 6, 17), seat_preference="extra_legroom"),
            PassengerSeed("Layla", "Al Mansoori", date(1991, 4, 28), seat_preference="extra_legroom"),
        ),
        extras=(
            ExtraSeed(ExtraType.SPORTS_EQUIPMENT, 1, Decimal("55.00"), "golf bag"),
        ),
    ),
    BookingSeed(
        booking_reference="TMN2V9J5",
        flight_number="TM631",
        departure_time=datetime(2026, 4, 10, 6, 50),
        seat_class=SeatClass.PREMIUM_ECONOMY,
        contact_name="Omar Al Mansoori",
        contact_email="omar.almansoori@example.com",
        contact_phone="+971-50-777-2201",
        status=BookingStatus.CONFIRMED,
        rescheduled_from_reference="TMR6K2S1",
        passengers=(
            PassengerSeed("Omar", "Al Mansoori", date(1988, 6, 17), seat_preference="window", seat_number="8A"),
            PassengerSeed("Layla", "Al Mansoori", date(1991, 4, 28), seat_preference="aisle", seat_number="8C"),
        ),
        extras=(
            ExtraSeed(ExtraType.SPORTS_EQUIPMENT, 1, Decimal("55.00"), "golf bag"),
        ),
    ),
    BookingSeed(
        booking_reference="TMH5Z1P4",
        flight_number="TM311",
        departure_time=datetime(2026, 4, 11, 9, 10),
        seat_class=SeatClass.BUSINESS,
        contact_name="Claire Dupont",
        contact_email="claire.dupont@example.com",
        contact_phone="+33-6-44-55-66-77",
        status=BookingStatus.CONFIRMED,
        passengers=(
            PassengerSeed("Claire", "Dupont", date(1975, 12, 2), seat_preference="window", seat_number="2A"),
        ),
        extras=(
            ExtraSeed(ExtraType.PET, 1, Decimal("90.00"), "small dog in approved carrier"),
            ExtraSeed(ExtraType.CABIN_BAG, 1, Decimal("20.00")),
        ),
    ),
)


def get_flight(session: Session, seed: BookingSeed) -> Flight | None:
    statement = select(Flight).where(
        Flight.flight_number == seed.flight_number,
        Flight.departure_time == seed.departure_time,
        Flight.seat_class == seed.seat_class,
    )
    return session.scalar(statement)


def build_total_price(seed: BookingSeed, flight: Flight) -> Decimal:
    passengers_total = flight.price * len(seed.passengers)
    extras_total = sum((extra.price for extra in seed.extras), Decimal("0.00"))
    return (passengers_total + extras_total).quantize(Decimal("0.01"))


def build_booking_events(seed: BookingSeed, booking_id: int) -> list[BookingEvent]:
    events = [
        BookingEvent(
            booking_id=booking_id,
            event_type=BookingEventType.CREATED,
            summary="Booking created",
            details=f"Initial booking created for reference {seed.booking_reference}.",
        )
    ]

    for extra in seed.extras:
        events.append(
            BookingEvent(
                booking_id=booking_id,
                event_type=BookingEventType.EXTRA_ADDED,
                summary=f"Added {extra.extra_type.value}",
                details=extra.description,
            )
        )

    if seed.status == BookingStatus.CANCELLED:
        events.append(
            BookingEvent(
                booking_id=booking_id,
                event_type=BookingEventType.CANCELLED,
                summary="Booking cancelled",
                details=seed.cancellation_reason,
            )
        )

    if seed.rescheduled_from_reference is not None:
        events.append(
            BookingEvent(
                booking_id=booking_id,
                event_type=BookingEventType.RESCHEDULED,
                summary="Booking rescheduled",
                details=f"Rescheduled from {seed.rescheduled_from_reference}.",
            )
        )

    if seed.refund_status in {RefundStatus.PENDING, RefundStatus.APPROVED, RefundStatus.PAID}:
        event_type = (
            BookingEventType.REFUND_PAID if seed.refund_status == RefundStatus.PAID else BookingEventType.REFUND_REQUESTED
        )
        events.append(
            BookingEvent(
                booking_id=booking_id,
                event_type=event_type,
                summary=f"Refund status: {seed.refund_status.value}",
                details=f"Refund amount: {seed.refund_amount or Decimal('0.00')}",
            )
        )

    return events


def main() -> None:
    ensure_flight_seat_columns(engine)
    sync_seat_inventory(engine)
    session = SessionLocal()
    try:
        reconcile_seat_state(session)
        existing_refs = set(session.scalars(select(Booking.booking_reference)))
        booking_ids_by_reference = {
            booking.booking_reference: booking.id
            for booking in session.scalars(select(Booking))
        }
        created = 0

        for seed in BOOKING_SEEDS:
            if seed.booking_reference in existing_refs:
                continue

            flight = get_flight(session, seed)
            if flight is None:
                raise ValueError(
                    "Flight not found for booking seed "
                    f"{seed.booking_reference}: {seed.flight_number} {seed.departure_time} {seed.seat_class.value}"
                )

            passenger_count = len(seed.passengers)
            if seed.status != BookingStatus.CANCELLED and flight.booked_seats + passenger_count > flight.capacity:
                raise ValueError(
                    f"Cannot seed booking {seed.booking_reference}: capacity exceeded for flight {flight.flight_number}"
                )

            booking = Booking(
                booking_reference=seed.booking_reference,
                flight_id=flight.id,
                rescheduled_from_booking_id=booking_ids_by_reference.get(seed.rescheduled_from_reference),
                contact_name=seed.contact_name,
                contact_email=seed.contact_email,
                contact_phone=seed.contact_phone,
                total_price=build_total_price(seed, flight),
                status=seed.status,
                cancelled_at=seed.cancelled_at,
                cancellation_reason=seed.cancellation_reason,
                refund_status=seed.refund_status,
                refund_amount=seed.refund_amount,
            )
            session.add(booking)
            session.flush()

            for passenger in seed.passengers:
                session.add(
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

            for extra in seed.extras:
                session.add(
                    BookingExtra(
                        booking_id=booking.id,
                        extra_type=extra.extra_type,
                        description=extra.description,
                        quantity=extra.quantity,
                        price=extra.price,
                    )
                )

            for event in build_booking_events(seed, booking.id):
                session.add(event)

            existing_refs.add(seed.booking_reference)
            booking_ids_by_reference[seed.booking_reference] = booking.id
            created += 1

        reconcile_seat_state(session)
        session.commit()
        print(f"Seed complete. Inserted {created} bookings.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
