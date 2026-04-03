from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


_SQLITE_CHECK_RE = re.compile(r"CHECK constraint failed: (?P<constraint>[\w_]+)")
_SQLITE_NOT_NULL_RE = re.compile(r"NOT NULL constraint failed: (?P<table>[\w_]+)\.(?P<column>[\w_]+)")
_SQLITE_UNIQUE_RE = re.compile(r"UNIQUE constraint failed: (?P<columns>[\w_. ,]+)")


@dataclass(frozen=True)
class ConstraintErrorSpec:
    error_code: str
    message: str
    status_code: int
    constraint: str | None = None
    table: str | None = None
    columns: tuple[str, ...] | None = None


_CHECK_CONSTRAINT_MESSAGES: dict[str, ConstraintErrorSpec] = {
    "ck_flights_departure_before_arrival": ConstraintErrorSpec(
        error_code="invalid_flight_times",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Flight departure time must be earlier than arrival time.",
    ),
    "ck_flights_check_in_open_before_close": ConstraintErrorSpec(
        error_code="invalid_check_in_window",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Check-in open time must be earlier than check-in close time.",
    ),
    "ck_flights_boarding_start_before_close": ConstraintErrorSpec(
        error_code="invalid_boarding_window",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Boarding start time must be earlier than boarding close time.",
    ),
    "ck_flights_boarding_close_before_departure": ConstraintErrorSpec(
        error_code="invalid_boarding_cutoff",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Boarding must close before departure.",
    ),
    "ck_flights_capacity_positive": ConstraintErrorSpec(
        error_code="invalid_flight_capacity",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Flight capacity must be greater than zero.",
    ),
    "ck_flights_price_positive": ConstraintErrorSpec(
        error_code="invalid_flight_price",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Flight price must be greater than zero.",
    ),
    "ck_flights_booked_seats_nonnegative": ConstraintErrorSpec(
        error_code="invalid_booked_seats",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Booked seats cannot be negative.",
    ),
    "ck_flights_booked_seats_within_capacity": ConstraintErrorSpec(
        error_code="booked_seats_exceeds_capacity",
        status_code=status.HTTP_409_CONFLICT,
        message="Booked seats cannot exceed flight capacity.",
    ),
    "ck_flights_preference_capacity_within_total_capacity": ConstraintErrorSpec(
        error_code="preference_capacity_exceeds_capacity",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Seat preference capacity cannot exceed total flight capacity.",
    ),
    "ck_flights_preference_booked_within_total_booked": ConstraintErrorSpec(
        error_code="preference_booked_exceeds_booked_seats",
        status_code=status.HTTP_409_CONFLICT,
        message="Seat preference bookings cannot exceed the total booked seats.",
    ),
    "ck_seat_inventory_cabin_allowed": ConstraintErrorSpec(
        error_code="invalid_seat_cabin",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Seat cabin must be economy, premium_economy, or business.",
    ),
    "ck_seat_inventory_seat_type_allowed": ConstraintErrorSpec(
        error_code="invalid_seat_type",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Seat type must be standard, window, aisle, or extra_legroom.",
    ),
    "ck_seat_inventory_extra_legroom_only_economy": ConstraintErrorSpec(
        error_code="invalid_extra_legroom_cabin",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Extra legroom seats are only allowed in economy cabin.",
    ),
    "ck_bookings_total_price_nonnegative": ConstraintErrorSpec(
        error_code="invalid_booking_total",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Booking total price cannot be negative.",
    ),
    "ck_bookings_refund_amount_nonnegative": ConstraintErrorSpec(
        error_code="invalid_refund_amount",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Refund amount cannot be negative.",
    ),
    "ck_bookings_cancelled_requires_cancelled_at": ConstraintErrorSpec(
        error_code="missing_cancelled_at",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Cancelled bookings must include a cancelled_at timestamp.",
    ),
    "ck_bookings_cancelled_requires_reason": ConstraintErrorSpec(
        error_code="missing_cancellation_reason",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Cancelled bookings must include a cancellation reason.",
    ),
    "ck_bookings_refund_requires_cancelled_status": ConstraintErrorSpec(
        error_code="invalid_refund_state",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="A refund can only exist for a cancelled booking.",
    ),
    "ck_bookings_paid_refund_requires_amount": ConstraintErrorSpec(
        error_code="missing_refund_amount",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Approved or paid refunds must include a refund amount.",
    ),
    "ck_bookings_reschedule_reference_requires_confirmed_status": ConstraintErrorSpec(
        error_code="invalid_reschedule_state",
        status_code=status.HTTP_409_CONFLICT,
        message="A booking with a rescheduled reference must remain confirmed.",
    ),
    "ck_booking_extras_quantity_positive": ConstraintErrorSpec(
        error_code="invalid_extra_quantity",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Extra quantity must be greater than zero.",
    ),
    "ck_booking_extras_price_nonnegative": ConstraintErrorSpec(
        error_code="invalid_extra_price",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Extra price cannot be negative.",
    ),
    "uq_seat_inventory_flight_seat": ConstraintErrorSpec(
        error_code="duplicate_seat_number",
        status_code=status.HTTP_409_CONFLICT,
        message="The same seat number already exists for this flight.",
    ),
    "uq_flights_number_departure_class": ConstraintErrorSpec(
        error_code="duplicate_flight_definition",
        status_code=status.HTTP_409_CONFLICT,
        message="A flight with the same flight number, departure time, and seat class already exists.",
    ),
    "uq_knowledge_articles_topic_title": ConstraintErrorSpec(
        error_code="duplicate_policy_article",
        status_code=status.HTTP_409_CONFLICT,
        message="A policy article with this topic and title already exists.",
    ),
}

_UNIQUE_COLUMN_MESSAGES: dict[tuple[str, ...], ConstraintErrorSpec] = {
    ("bookings", "booking_reference"): ConstraintErrorSpec(
        error_code="duplicate_booking_reference",
        status_code=status.HTTP_409_CONFLICT,
        message="Booking reference already exists.",
    ),
    ("seat_inventory", "flight_id", "seat_number"): ConstraintErrorSpec(
        error_code="duplicate_seat_number",
        status_code=status.HTTP_409_CONFLICT,
        message="The same seat number already exists for this flight.",
    ),
    ("knowledge_articles", "topic", "title"): ConstraintErrorSpec(
        error_code="duplicate_policy_article",
        status_code=status.HTTP_409_CONFLICT,
        message="A policy article with this topic and title already exists.",
    ),
}

_NOT_NULL_COLUMN_MESSAGES: dict[tuple[str, str], ConstraintErrorSpec] = {
    ("booking_passengers", "date_of_birth"): ConstraintErrorSpec(
        error_code="missing_passenger_date_of_birth",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Passenger date of birth is required.",
    ),
    ("bookings", "cancelled_at"): ConstraintErrorSpec(
        error_code="missing_cancelled_at",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="Cancelled bookings must include a cancelled_at timestamp.",
    ),
}


def integrity_error_response(exc: IntegrityError) -> JSONResponse:
    spec = _resolve_integrity_error(exc)
    payload = {
        "error": "constraint_violation",
        "error_code": spec.error_code,
        "message": spec.message,
    }
    if spec.constraint is not None:
        payload["constraint"] = spec.constraint
    if spec.table is not None:
        payload["table"] = spec.table
    if spec.columns is not None:
        payload["columns"] = list(spec.columns)
    if isinstance(exc.orig, Exception):
        payload["database_error"] = str(exc.orig)
    return JSONResponse(status_code=spec.status_code, content=payload)


def _resolve_integrity_error(exc: IntegrityError) -> ConstraintErrorSpec:
    message = str(exc.orig)

    check_match = _SQLITE_CHECK_RE.search(message)
    if check_match:
        constraint = check_match.group("constraint")
        if constraint in _CHECK_CONSTRAINT_MESSAGES:
            base = _CHECK_CONSTRAINT_MESSAGES[constraint]
            return ConstraintErrorSpec(
                error_code=base.error_code,
                message=base.message,
                status_code=base.status_code,
                constraint=constraint,
            )
        return ConstraintErrorSpec(
            error_code="constraint_violation",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"Database check constraint failed: {constraint}.",
            constraint=constraint,
        )

    not_null_match = _SQLITE_NOT_NULL_RE.search(message)
    if not_null_match:
        table = not_null_match.group("table")
        column = not_null_match.group("column")
        spec = _NOT_NULL_COLUMN_MESSAGES.get((table, column))
        if spec is not None:
            return ConstraintErrorSpec(
                error_code=spec.error_code,
                message=spec.message,
                status_code=spec.status_code,
                table=table,
                columns=(column,),
            )
        return ConstraintErrorSpec(
            error_code="missing_required_field",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"Column {table}.{column} is required.",
            table=table,
            columns=(column,),
        )

    unique_match = _SQLITE_UNIQUE_RE.search(message)
    if unique_match:
        columns = tuple(
            part.strip()
            for part in unique_match.group("columns").split(",")
            if part.strip()
        )
        table_names = {column.split(".", 1)[0] for column in columns if "." in column}
        column_names = tuple(column.split(".", 1)[1] for column in columns if "." in column)
        for table_name in table_names:
            spec = _UNIQUE_COLUMN_MESSAGES.get((table_name, *column_names))
            if spec is not None:
                return ConstraintErrorSpec(
                    error_code=spec.error_code,
                    message=spec.message,
                    status_code=spec.status_code,
                    table=table_name,
                    columns=column_names,
                )
        return ConstraintErrorSpec(
            error_code="duplicate_record",
            status_code=status.HTTP_409_CONFLICT,
            message="A record with the same unique values already exists.",
            columns=column_names,
        )

    if "FOREIGN KEY constraint failed" in message:
        return ConstraintErrorSpec(
            error_code="foreign_key_violation",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="The request references a related record that does not exist.",
        )

    return ConstraintErrorSpec(
        error_code="constraint_violation",
        status_code=status.HTTP_400_BAD_REQUEST,
        message="A database constraint was violated.",
    )
