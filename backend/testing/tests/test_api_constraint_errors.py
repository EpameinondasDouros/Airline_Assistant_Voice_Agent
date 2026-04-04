from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # ensure ORM models are registered
from app.db.base import Base
from app.db.session import get_db_session
import app.api.routes.bookings as booking_routes
import app.main as main_module
from app.models.flight import Flight, FlightStatus, SeatClass
from app.models.seat_inventory import SeatInventory
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main_module, "ensure_flight_seat_columns", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "sync_seat_inventory", lambda *_args, **_kwargs: None)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def booking_api_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = SessionLocal()

    departure_time = datetime(2026, 4, 6, 10, 0, tzinfo=UTC)
    flight = Flight(
        flight_number="TM123",
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
        capacity=2,
        booked_seats=0,
        window_seat_capacity=1,
        window_seat_booked=0,
        aisle_seat_capacity=1,
        aisle_seat_booked=0,
        extra_legroom_capacity=0,
        extra_legroom_booked=0,
        status=FlightStatus.SCHEDULED,
    )
    db.add(flight)
    db.flush()
    db.add_all(
        [
            SeatInventory(flight_id=flight.id, seat_number="1A", cabin="business", seat_type="window", is_booked=False),
            SeatInventory(flight_id=flight.id, seat_number="1B", cabin="business", seat_type="aisle", is_booked=False),
        ]
    )
    db.commit()

    def override_db_session():
        try:
            yield db
        finally:
            pass

    monkeypatch.setattr(main_module, "ensure_flight_seat_columns", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "sync_seat_inventory", lambda *_args, **_kwargs: None)
    app.dependency_overrides[get_db_session] = override_db_session

    try:
        yield db, flight.id
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_duplicate_booking_http_error_is_returned_verbatim(client, monkeypatch):
    def raise_conflict(self, payload):  # noqa: ANN001
        raise HTTPException(
            status_code=409,
            detail="Passenger Eleni Pappas (1992-04-16) already has a booking on this flight.",
        )

    monkeypatch.setattr(booking_routes.BookingService, "create_booking", raise_conflict)

    response = client.post(
        "/api/bookings",
        json={
            "flight_id": 179,
            "contact_name": "Test Contact",
            "contact_email": "test@example.com",
            "passengers": [
                {
                    "first_name": "Eleni",
                    "last_name": "Pappas",
                    "date_of_birth": "1992-04-16",
                }
            ],
            "extras": [],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Passenger Eleni Pappas (1992-04-16) already has a booking on this flight."
    }


def test_integrity_error_returns_constraint_details(client, monkeypatch):
    def raise_integrity_error(self, payload):  # noqa: ANN001
        raise IntegrityError(
            statement="INSERT INTO bookings ...",
            params={},
            orig=sqlite3.IntegrityError(
                "CHECK constraint failed: ck_bookings_reschedule_reference_requires_confirmed_status"
            ),
        )

    monkeypatch.setattr(booking_routes.BookingService, "create_booking", raise_integrity_error)

    response = client.post(
        "/api/bookings",
        json={
            "flight_id": 179,
            "contact_name": "Test Contact",
            "contact_email": "test@example.com",
            "passengers": [
                {
                    "first_name": "Eleni",
                    "last_name": "Pappas",
                    "date_of_birth": "1992-04-16",
                }
            ],
            "extras": [],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": "constraint_violation",
        "error_code": "invalid_reschedule_state",
        "message": "A booking with a rescheduled reference must remain confirmed.",
        "constraint": "ck_bookings_reschedule_reference_requires_confirmed_status",
        "database_error": "CHECK constraint failed: ck_bookings_reschedule_reference_requires_confirmed_status",
    }


def test_request_validation_error_returns_details(client):
    response = client.post(
        "/api/bookings",
        json={
            "flight_id": 179,
            "contact_name": "Test Contact",
            "contact_email": "test@example.com",
            "passengers": [
                {
                    "first_name": "Eleni",
                    "last_name": "Pappas",
                }
            ],
            "extras": [],
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert body["error_code"] == "request_validation_error"
    assert body["message"] == "The request body failed validation."
    assert any(
        error["loc"] == ["body", "passengers", 0, "date_of_birth"]
        for error in body["details"]
    )


def test_double_booking_via_api_returns_clear_conflict(booking_api_db):
    _db, flight_id = booking_api_db

    with TestClient(app) as client:
        payload = {
            "flight_id": flight_id,
            "contact_name": "Test Contact",
            "contact_email": "test@example.com",
            "passengers": [
                {
                    "first_name": "Eleni",
                    "last_name": "Pappas",
                    "date_of_birth": "1992-04-16",
                    "seat_preference": "window",
                }
            ],
            "extras": [],
        }

        first_response = client.post("/api/bookings", json=payload)
        assert first_response.status_code == 201, first_response.text

        second_response = client.post("/api/bookings", json=payload)
        assert second_response.status_code == 409
        assert second_response.json() == {
            "detail": "Passenger Eleni Pappas (1992-04-16) already has a booking on this flight."
        }


def test_all_trips_booked_returns_confirmed_bookings_with_flight_and_passenger_details(booking_api_db):
    _db, flight_id = booking_api_db

    with TestClient(app) as client:
        confirmed_response = client.post(
            "/api/bookings",
            json={
                "flight_id": flight_id,
                "contact_name": "Julian Vane",
                "contact_email": "julian@example.com",
                "passengers": [
                    {
                        "first_name": "Julian",
                        "last_name": "Vane",
                        "date_of_birth": "1990-02-14",
                        "seat_preference": "window",
                    }
                ],
                "extras": [],
            },
        )
        assert confirmed_response.status_code == 201, confirmed_response.text

        cancelled_response = client.post(
            "/api/bookings",
            json={
                "flight_id": flight_id,
                "contact_name": "Mina Vane",
                "contact_email": "mina@example.com",
                "passengers": [
                    {
                        "first_name": "Mina",
                        "last_name": "Vane",
                        "date_of_birth": "1994-11-09",
                        "seat_preference": "aisle",
                    }
                ],
                "extras": [],
            },
        )
        assert cancelled_response.status_code == 201, cancelled_response.text

        cancelled_reference = cancelled_response.json()["booking_reference"]
        cancellation = client.post(
            f"/api/bookings/{cancelled_reference}/cancel",
            json={
                "reason": "Passenger changed plans",
                "refund_status": "pending",
                "refund_amount": "540.00",
            },
        )
        assert cancellation.status_code == 200, cancellation.text

        response = client.get("/api/bookings/all-trips-booked")
        assert response.status_code == 200, response.text

        body = response.json()
        assert len(body) == 1
        assert body[0]["booking_reference"] == confirmed_response.json()["booking_reference"]
        assert body[0]["flight"]["flight_number"] == "TM123"
        assert body[0]["flight"]["origin_airport"] == "ATH"
        assert body[0]["passengers"][0]["first_name"] == "Julian"
        assert body[0]["passengers"][0]["seat_number"] == "1A"
