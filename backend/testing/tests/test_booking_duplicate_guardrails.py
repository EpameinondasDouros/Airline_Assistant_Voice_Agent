from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # ensure ORM models are registered
from app.db.base import Base
from app.models.booking import BookingStatus, RefundStatus
from app.models.booking_extra import ExtraType
from app.models.flight import Flight, FlightStatus, SeatClass
from app.models.seat_inventory import SeatInventory
from app.schemas.booking import (
    BookingAddExtrasRequest,
    BookingCancelRequest,
    BookingCreate,
    BookingRescheduleRequest,
    ExtraCreate,
    PassengerCreate,
)
from app.services.booking_service import BookingService


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _make_flight(session, *, flight_number: str, departure_offset_hours: int = 0) -> Flight:
    departure_time = datetime(2026, 4, 6, 10, 0, tzinfo=UTC) + timedelta(hours=departure_offset_hours)
    flight = Flight(
        flight_number=flight_number,
        origin_airport="ATH",
        destination_airport="JFK",
        departure_time=departure_time,
        arrival_time=departure_time + timedelta(hours=10),
        terminal="T1",
        departure_gate="A12",
        check_in_open_at=departure_time - timedelta(hours=3),
        check_in_close_at=departure_time - timedelta(minutes=45),
        boarding_starts_at=departure_time - timedelta(minutes=50),
        boarding_closes_at=departure_time - timedelta(minutes=20),
        seat_class=SeatClass.BUSINESS,
        price=Decimal("540.00"),
        capacity=4,
        booked_seats=0,
        window_seat_capacity=2,
        window_seat_booked=0,
        aisle_seat_capacity=2,
        aisle_seat_booked=0,
        extra_legroom_capacity=0,
        extra_legroom_booked=0,
        status=FlightStatus.SCHEDULED,
    )
    session.add(flight)
    session.flush()
    session.add_all(
        [
            SeatInventory(flight_id=flight.id, seat_number="1A", cabin="business", seat_type="window", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1B", cabin="business", seat_type="aisle", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1C", cabin="business", seat_type="aisle", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1D", cabin="business", seat_type="window", is_booked=False),
        ]
    )
    session.commit()
    return flight


def test_duplicate_same_flight_is_rejected(session):
    flight = _make_flight(session, flight_number="TM100")
    service = BookingService(session)

    first_booking = service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Test Contact",
            contact_email="test@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Eleni",
                    last_name="Pappas",
                    date_of_birth=datetime(1992, 4, 16, tzinfo=UTC).date(),
                )
            ],
        )
    )
    assert first_booking.flight_id == flight.id

    with pytest.raises(HTTPException) as excinfo:
        service.create_booking(
            BookingCreate(
                flight_id=flight.id,
                contact_name="Other Contact",
                contact_email="other@example.com",
                passengers=[
                    PassengerCreate(
                        first_name="Eleni",
                        last_name="Pappas",
                        date_of_birth=datetime(1992, 4, 16, tzinfo=UTC).date(),
                    )
                ],
            )
        )

    assert excinfo.value.status_code == 409


def test_refund_pending_blocks_same_flight_rebooking(session):
    flight = _make_flight(session, flight_number="TM101")
    service = BookingService(session)

    booking = service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Test Contact",
            contact_email="test@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Maya",
                    last_name="Patel",
                    date_of_birth=datetime(1990, 5, 14, tzinfo=UTC).date(),
                )
            ],
        )
    )

    service.cancel_booking(
        booking.booking_reference,
        BookingCancelRequest(reason="customer requested", refund_status=RefundStatus.PENDING),
    )

    with pytest.raises(HTTPException) as excinfo:
        service.create_booking(
            BookingCreate(
                flight_id=flight.id,
                contact_name="Another Contact",
                contact_email="another@example.com",
                passengers=[
                    PassengerCreate(
                        first_name="Maya",
                        last_name="Patel",
                        date_of_birth=datetime(1990, 5, 14, tzinfo=UTC).date(),
                    )
                ],
            )
        )

    assert excinfo.value.status_code == 409


def test_refund_pending_allows_different_flight(session):
    flight_one = _make_flight(session, flight_number="TM102")
    flight_two = _make_flight(session, flight_number="TM103", departure_offset_hours=24)
    service = BookingService(session)

    booking = service.create_booking(
        BookingCreate(
            flight_id=flight_one.id,
            contact_name="Test Contact",
            contact_email="test@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Omar",
                    last_name="Rossi",
                    date_of_birth=datetime(1985, 2, 3, tzinfo=UTC).date(),
                )
            ],
        )
    )
    service.cancel_booking(
        booking.booking_reference,
        BookingCancelRequest(reason="customer requested", refund_status=RefundStatus.PENDING),
    )

    booking_two = service.create_booking(
        BookingCreate(
            flight_id=flight_two.id,
            contact_name="Test Contact",
            contact_email="test2@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Omar",
                    last_name="Rossi",
                    date_of_birth=datetime(1985, 2, 3, tzinfo=UTC).date(),
                )
            ],
        )
    )

    assert booking_two.flight_id == flight_two.id


def test_two_different_passengers_can_book_same_flight(session):
    flight = _make_flight(session, flight_number="TM104")
    service = BookingService(session)

    booking_one = service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Contact One",
            contact_email="one@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Ava",
                    last_name="Johnson",
                    date_of_birth=datetime(1978, 8, 22, tzinfo=UTC).date(),
                )
            ],
        )
    )
    booking_two = service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Contact Two",
            contact_email="two@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Nikos",
                    last_name="Vardis",
                    date_of_birth=datetime(1984, 10, 2, tzinfo=UTC).date(),
                )
            ],
        )
    )

    assert booking_one.flight_id == flight.id
    assert booking_two.flight_id == flight.id


def test_request_duplicate_passengers_is_rejected(session):
    flight = _make_flight(session, flight_number="TM105")
    service = BookingService(session)

    with pytest.raises(HTTPException) as excinfo:
        service.create_booking(
            BookingCreate(
                flight_id=flight.id,
                contact_name="Contact",
                contact_email="dup@example.com",
                passengers=[
                    PassengerCreate(
                        first_name="Eleni",
                        last_name="Markou",
                        date_of_birth=datetime(1979, 5, 22, tzinfo=UTC).date(),
                    ),
                    PassengerCreate(
                        first_name="Eleni",
                        last_name="Markou",
                        date_of_birth=datetime(1979, 5, 22, tzinfo=UTC).date(),
                    ),
                ],
            )
        )

    assert excinfo.value.status_code == 409


def test_name_normalization_blocks_same_person(session):
    flight = _make_flight(session, flight_number="TM106")
    service = BookingService(session)

    service.create_booking(
        BookingCreate(
            flight_id=flight.id,
            contact_name="Contact",
            contact_email="normalize@example.com",
            passengers=[
                PassengerCreate(
                    first_name="  ELENI ",
                    last_name=" PAPPAS ",
                    date_of_birth=datetime(1992, 4, 16, tzinfo=UTC).date(),
                )
            ],
        )
    )

    with pytest.raises(HTTPException) as excinfo:
        service.create_booking(
            BookingCreate(
                flight_id=flight.id,
                contact_name="Contact Two",
                contact_email="normalize2@example.com",
                passengers=[
                    PassengerCreate(
                        first_name="eleni",
                        last_name="pappas",
                        date_of_birth=datetime(1992, 4, 16, tzinfo=UTC).date(),
                    )
                ],
            )
        )

    assert excinfo.value.status_code == 409


def test_reschedule_and_extras_still_work(session):
    flight_one = _make_flight(session, flight_number="TM107")
    flight_two = _make_flight(session, flight_number="TM108", departure_offset_hours=24)
    flight_three = _make_flight(session, flight_number="TM109", departure_offset_hours=48)
    service = BookingService(session)

    booking = service.create_booking(
        BookingCreate(
            flight_id=flight_one.id,
            contact_name="Contact",
            contact_email="smoke@example.com",
            passengers=[
                PassengerCreate(
                    first_name="Claire",
                    last_name="Dupont",
                    date_of_birth=datetime(1975, 12, 2, tzinfo=UTC).date(),
                )
            ],
        )
    )
    updated = service.add_extras(
        booking.booking_reference,
        BookingAddExtrasRequest(
            extras=[
                ExtraCreate(
                    extra_type=ExtraType.CHECKED_BAG,
                    quantity=1,
                    price=Decimal("35.00"),
                )
            ]
        ),
    )
    assert updated.total_price == Decimal("575.00")

    rescheduled = service.reschedule_booking(
        booking.booking_reference,
        BookingRescheduleRequest(new_flight_id=flight_three.id),
    )
    assert rescheduled.flight_id == flight_three.id
