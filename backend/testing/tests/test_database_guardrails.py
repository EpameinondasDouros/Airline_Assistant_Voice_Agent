from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # ensure ORM models are registered
from app.db.base import Base
from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_extra import BookingExtra, ExtraType
from app.models.booking_passenger import BookingPassenger
from app.models.flight import Flight, FlightStatus, SeatClass
from app.models.knowledge_article import KnowledgeArticle
from app.models.seat_inventory import SeatInventory


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


def _make_flight(session, *, flight_number: str = "TM900") -> Flight:
    departure_time = datetime(2026, 4, 6, 10, 0, tzinfo=UTC)
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
    return flight


def test_flight_constraints_reject_invalid_timing(session):
    departure_time = datetime(2026, 4, 6, 10, 0, tzinfo=UTC)
    session.add(
        Flight(
            flight_number="TMBAD1",
            origin_airport="ATH",
            destination_airport="JFK",
            departure_time=departure_time,
            arrival_time=departure_time - timedelta(hours=1),
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
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_flight_constraints_reject_invalid_counts(session):
    departure_time = datetime(2026, 4, 6, 10, 0, tzinfo=UTC)
    session.add(
        Flight(
            flight_number="TMBAD2",
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
            price=Decimal("0.00"),
            capacity=0,
            booked_seats=1,
            window_seat_capacity=2,
            window_seat_booked=0,
            aisle_seat_capacity=2,
            aisle_seat_booked=0,
            extra_legroom_capacity=0,
            extra_legroom_booked=0,
            status=FlightStatus.SCHEDULED,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_seat_inventory_constraints_reject_invalid_rows(session):
    flight = _make_flight(session)
    session.commit()

    session.add(
        SeatInventory(
            flight_id=flight.id,
            seat_number="2A",
            cabin="business",
            seat_type="extra_legroom",
            is_booked=False,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_booking_constraints_reject_missing_dob_and_bad_refund_state(session):
    flight = _make_flight(session)
    session.commit()

    booking = Booking(
        booking_reference="TMTEST01",
        flight_id=flight.id,
        contact_name="Test Contact",
        contact_email="test@example.com",
        total_price=Decimal("540.00"),
        status=BookingStatus.CONFIRMED,
        refund_status=RefundStatus.NOT_REQUESTED,
    )
    session.add(booking)
    session.flush()
    session.add(
        BookingPassenger(
            booking_id=booking.id,
            first_name="Eleni",
            last_name="Pappas",
            date_of_birth=None,  # type: ignore[arg-type]
            passenger_type="adult",
            seat_preference="window",
            seat_number="1A",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
    session.add(
        Booking(
            booking_reference="TMTEST02",
            flight_id=flight.id,
            contact_name="Test Contact",
            contact_email="test2@example.com",
            total_price=Decimal("540.00"),
            status=BookingStatus.CONFIRMED,
            refund_status=RefundStatus.PENDING,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_booking_extras_constraints_reject_bad_values(session):
    flight = _make_flight(session)
    session.commit()

    booking = Booking(
        booking_reference="TMTEST03",
        flight_id=flight.id,
        contact_name="Test Contact",
        contact_email="test3@example.com",
        total_price=Decimal("540.00"),
        status=BookingStatus.CONFIRMED,
        refund_status=RefundStatus.NOT_REQUESTED,
    )
    session.add(booking)
    session.flush()
    session.add(
        BookingExtra(
            booking_id=booking.id,
            extra_type=ExtraType.CHECKED_BAG,
            quantity=0,
            price=Decimal("-1.00"),
            description="invalid",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_knowledge_articles_must_be_unique_per_topic_and_title(session):
    session.add(
        KnowledgeArticle(
            topic="baggage",
            title="Cabin and Hold Baggage Allowance",
            content="One",
            version=1,
            is_active=True,
        )
    )
    session.add(
        KnowledgeArticle(
            topic="baggage",
            title="Cabin and Hold Baggage Allowance",
            content="Two",
            version=1,
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
