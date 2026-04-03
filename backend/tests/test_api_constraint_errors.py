from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import app.api.routes.bookings as booking_routes
import app.main as main_module
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main_module, "ensure_flight_seat_columns", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "sync_seat_inventory", lambda *_args, **_kwargs: None)
    with TestClient(app) as test_client:
        yield test_client


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
