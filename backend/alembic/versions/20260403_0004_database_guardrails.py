"""Add database guardrails for flights, bookings, seats, extras, and knowledge.

Revision ID: 20260403_0004
Revises: 20260403_0003
Create Date: 2026-04-03 00:04:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0004"
down_revision = "20260403_0003"
branch_labels = None
depends_on = None


def _count(conn, sql: str) -> int:
    return int(conn.execute(sa.text(sql)).scalar_one())


def _validate_existing_rows(conn) -> None:
    violations: list[str] = []

    flight_checks = [
        ("flights with departure >= arrival", "SELECT COUNT(*) FROM flights WHERE departure_time >= arrival_time"),
        ("flights with non-positive capacity", "SELECT COUNT(*) FROM flights WHERE capacity <= 0"),
        ("flights with negative price", "SELECT COUNT(*) FROM flights WHERE price <= 0"),
        (
            "flights with booked seats outside capacity bounds",
            "SELECT COUNT(*) FROM flights WHERE booked_seats < 0 OR booked_seats > capacity",
        ),
        (
            "flights with negative preference capacities",
            """
            SELECT COUNT(*) FROM flights
            WHERE window_seat_capacity < 0
               OR aisle_seat_capacity < 0
               OR extra_legroom_capacity < 0
               OR window_seat_booked < 0
               OR aisle_seat_booked < 0
               OR extra_legroom_booked < 0
            """,
        ),
        (
            "flights with preference bookings exceeding their category capacity",
            """
            SELECT COUNT(*) FROM flights
            WHERE window_seat_booked > window_seat_capacity
               OR aisle_seat_booked > aisle_seat_capacity
               OR extra_legroom_booked > extra_legroom_capacity
            """,
        ),
        (
            "flights with preference capacities exceeding total capacity",
            """
            SELECT COUNT(*) FROM flights
            WHERE window_seat_capacity + aisle_seat_capacity + extra_legroom_capacity > capacity
            """,
        ),
        (
            "flights with preference bookings exceeding booked seat total",
            """
            SELECT COUNT(*) FROM flights
            WHERE window_seat_booked + aisle_seat_booked + extra_legroom_booked > booked_seats
            """,
        ),
    ]

    booking_checks = [
        (
            "bookings with negative total price",
            "SELECT COUNT(*) FROM bookings WHERE total_price < 0",
        ),
        (
            "bookings with negative refund amount",
            "SELECT COUNT(*) FROM bookings WHERE refund_amount < 0",
        ),
        (
            "cancelled bookings missing cancelled_at",
            "SELECT COUNT(*) FROM bookings WHERE status = 'CANCELLED' AND cancelled_at IS NULL",
        ),
        (
            "cancelled bookings missing cancellation_reason",
            "SELECT COUNT(*) FROM bookings WHERE status = 'CANCELLED' AND cancellation_reason IS NULL",
        ),
        (
            "non-cancelled bookings with a refund status other than not_requested",
            "SELECT COUNT(*) FROM bookings WHERE status != 'CANCELLED' AND refund_status != 'NOT_REQUESTED'",
        ),
        (
            "approved or paid refunds missing refund_amount",
            "SELECT COUNT(*) FROM bookings WHERE refund_status IN ('APPROVED', 'PAID') AND refund_amount IS NULL",
        ),
        (
            "rescheduled references on non-confirmed bookings",
            "SELECT COUNT(*) FROM bookings WHERE rescheduled_from_booking_id IS NOT NULL AND status != 'CONFIRMED'",
        ),
    ]

    seat_checks = [
        (
            "seat inventory rows with invalid cabin values",
            """
            SELECT COUNT(*) FROM seat_inventory
            WHERE cabin NOT IN ('economy', 'premium_economy', 'business')
            """,
        ),
        (
            "seat inventory rows with invalid seat_type values",
            """
            SELECT COUNT(*) FROM seat_inventory
            WHERE seat_type NOT IN ('standard', 'window', 'aisle', 'extra_legroom')
            """,
        ),
        (
            "extra-legroom seats outside economy",
            """
            SELECT COUNT(*) FROM seat_inventory
            WHERE seat_type = 'extra_legroom' AND cabin != 'economy'
            """,
        ),
    ]

    passenger_checks = [
        (
            "booking passengers with missing date_of_birth",
            "SELECT COUNT(*) FROM booking_passengers WHERE date_of_birth IS NULL",
        ),
        (
            "booking passengers with invalid seat preference values",
            """
            SELECT COUNT(*) FROM booking_passengers
            WHERE seat_preference IS NOT NULL
              AND seat_preference NOT IN ('window', 'aisle', 'extra_legroom')
            """,
        ),
    ]

    extra_checks = [
        ("booking extras with non-positive quantity", "SELECT COUNT(*) FROM booking_extras WHERE quantity <= 0"),
        ("booking extras with negative price", "SELECT COUNT(*) FROM booking_extras WHERE price < 0"),
    ]

    knowledge_checks = [
        (
            "duplicate knowledge articles by topic/title",
            """
            SELECT COUNT(*) FROM (
                SELECT topic, title
                FROM knowledge_articles
                GROUP BY topic, title
                HAVING COUNT(*) > 1
            )
            """,
        ),
        (
            "knowledge articles with invalid version numbers",
            "SELECT COUNT(*) FROM knowledge_articles WHERE version < 1",
        ),
    ]

    for label, sql in (
        flight_checks + booking_checks + seat_checks + passenger_checks + extra_checks + knowledge_checks
    ):
        count = _count(conn, sql)
        if count:
            violations.append(f"{label}: {count}")

    if violations:
        raise RuntimeError(
            "Database integrity violations detected before applying guardrail constraints: "
            + "; ".join(violations)
        )


def upgrade() -> None:
    conn = op.get_bind()
    _validate_existing_rows(conn)

    with op.batch_alter_table("flights", recreate="always") as batch:
        batch.create_check_constraint("ck_flights_departure_before_arrival", "departure_time < arrival_time")
        batch.create_check_constraint(
            "ck_flights_check_in_open_before_close",
            "check_in_open_at IS NULL OR check_in_close_at IS NULL OR check_in_open_at <= check_in_close_at",
        )
        batch.create_check_constraint(
            "ck_flights_boarding_start_before_close",
            "boarding_starts_at IS NULL OR boarding_closes_at IS NULL OR boarding_starts_at <= boarding_closes_at",
        )
        batch.create_check_constraint(
            "ck_flights_boarding_close_before_departure",
            "boarding_closes_at IS NULL OR boarding_closes_at <= departure_time",
        )
        batch.create_check_constraint("ck_flights_capacity_positive", "capacity > 0")
        batch.create_check_constraint("ck_flights_price_positive", "price > 0")
        batch.create_check_constraint("ck_flights_booked_seats_nonnegative", "booked_seats >= 0")
        batch.create_check_constraint("ck_flights_booked_seats_within_capacity", "booked_seats <= capacity")
        batch.create_check_constraint("ck_flights_window_capacity_nonnegative", "window_seat_capacity >= 0")
        batch.create_check_constraint("ck_flights_window_booked_nonnegative", "window_seat_booked >= 0")
        batch.create_check_constraint(
            "ck_flights_window_booked_within_capacity",
            "window_seat_booked <= window_seat_capacity",
        )
        batch.create_check_constraint("ck_flights_aisle_capacity_nonnegative", "aisle_seat_capacity >= 0")
        batch.create_check_constraint("ck_flights_aisle_booked_nonnegative", "aisle_seat_booked >= 0")
        batch.create_check_constraint(
            "ck_flights_aisle_booked_within_capacity",
            "aisle_seat_booked <= aisle_seat_capacity",
        )
        batch.create_check_constraint("ck_flights_extra_legroom_capacity_nonnegative", "extra_legroom_capacity >= 0")
        batch.create_check_constraint("ck_flights_extra_legroom_booked_nonnegative", "extra_legroom_booked >= 0")
        batch.create_check_constraint(
            "ck_flights_extra_legroom_booked_within_capacity",
            "extra_legroom_booked <= extra_legroom_capacity",
        )
        batch.create_check_constraint(
            "ck_flights_preference_capacity_within_total_capacity",
            "window_seat_capacity + aisle_seat_capacity + extra_legroom_capacity <= capacity",
        )
        batch.create_check_constraint(
            "ck_flights_preference_booked_within_total_booked",
            "window_seat_booked + aisle_seat_booked + extra_legroom_booked <= booked_seats",
        )

    with op.batch_alter_table("seat_inventory", recreate="always") as batch:
        batch.create_check_constraint(
            "ck_seat_inventory_cabin_allowed",
            "cabin IN ('economy', 'premium_economy', 'business')",
        )
        batch.create_check_constraint(
            "ck_seat_inventory_seat_type_allowed",
            "seat_type IN ('standard', 'window', 'aisle', 'extra_legroom')",
        )
        batch.create_check_constraint(
            "ck_seat_inventory_extra_legroom_only_economy",
            "seat_type != 'extra_legroom' OR cabin = 'economy'",
        )

    with op.batch_alter_table("bookings", recreate="always") as batch:
        batch.create_check_constraint("ck_bookings_total_price_nonnegative", "total_price >= 0")
        batch.create_check_constraint(
            "ck_bookings_refund_amount_nonnegative",
            "refund_amount IS NULL OR refund_amount >= 0",
        )
        batch.create_check_constraint(
            "ck_bookings_cancelled_requires_cancelled_at",
            "status != 'CANCELLED' OR cancelled_at IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_bookings_cancelled_requires_reason",
            "status != 'CANCELLED' OR cancellation_reason IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_bookings_refund_requires_cancelled_status",
            "refund_status = 'NOT_REQUESTED' OR status = 'CANCELLED'",
        )
        batch.create_check_constraint(
            "ck_bookings_paid_refund_requires_amount",
            "refund_status NOT IN ('APPROVED', 'PAID') OR refund_amount IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_bookings_reschedule_reference_requires_confirmed_status",
            "rescheduled_from_booking_id IS NULL OR status = 'CONFIRMED'",
        )

    with op.batch_alter_table("booking_passengers", recreate="always") as batch:
        batch.alter_column("date_of_birth", existing_type=sa.Date(), nullable=False)
        batch.create_check_constraint(
            "ck_booking_passengers_seat_preference_allowed",
            "seat_preference IS NULL OR seat_preference IN ('window', 'aisle', 'extra_legroom')",
        )

    with op.batch_alter_table("booking_extras", recreate="always") as batch:
        batch.create_check_constraint("ck_booking_extras_quantity_positive", "quantity > 0")
        batch.create_check_constraint("ck_booking_extras_price_nonnegative", "price >= 0")

    with op.batch_alter_table("knowledge_articles", recreate="always") as batch:
        batch.create_unique_constraint("uq_knowledge_articles_topic_title", ["topic", "title"])
        batch.create_check_constraint("ck_knowledge_articles_version_positive", "version >= 1")


def downgrade() -> None:
    with op.batch_alter_table("knowledge_articles", recreate="always") as batch:
        batch.drop_constraint("uq_knowledge_articles_topic_title", type_="unique")
        batch.drop_constraint("ck_knowledge_articles_version_positive", type_="check")

    with op.batch_alter_table("booking_extras", recreate="always") as batch:
        batch.drop_constraint("ck_booking_extras_price_nonnegative", type_="check")
        batch.drop_constraint("ck_booking_extras_quantity_positive", type_="check")

    with op.batch_alter_table("booking_passengers", recreate="always") as batch:
        batch.drop_constraint("ck_booking_passengers_seat_preference_allowed", type_="check")
        batch.alter_column("date_of_birth", existing_type=sa.Date(), nullable=True)

    with op.batch_alter_table("bookings", recreate="always") as batch:
        batch.drop_constraint("ck_bookings_reschedule_reference_requires_confirmed_status", type_="check")
        batch.drop_constraint("ck_bookings_paid_refund_requires_amount", type_="check")
        batch.drop_constraint("ck_bookings_refund_requires_cancelled_status", type_="check")
        batch.drop_constraint("ck_bookings_cancelled_requires_reason", type_="check")
        batch.drop_constraint("ck_bookings_cancelled_requires_cancelled_at", type_="check")
        batch.drop_constraint("ck_bookings_refund_amount_nonnegative", type_="check")
        batch.drop_constraint("ck_bookings_total_price_nonnegative", type_="check")

    with op.batch_alter_table("seat_inventory", recreate="always") as batch:
        batch.drop_constraint("ck_seat_inventory_extra_legroom_only_economy", type_="check")
        batch.drop_constraint("ck_seat_inventory_seat_type_allowed", type_="check")
        batch.drop_constraint("ck_seat_inventory_cabin_allowed", type_="check")

    with op.batch_alter_table("flights", recreate="always") as batch:
        batch.drop_constraint("ck_flights_preference_booked_within_total_booked", type_="check")
        batch.drop_constraint("ck_flights_preference_capacity_within_total_capacity", type_="check")
        batch.drop_constraint("ck_flights_extra_legroom_booked_within_capacity", type_="check")
        batch.drop_constraint("ck_flights_extra_legroom_booked_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_extra_legroom_capacity_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_aisle_booked_within_capacity", type_="check")
        batch.drop_constraint("ck_flights_aisle_booked_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_aisle_capacity_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_window_booked_within_capacity", type_="check")
        batch.drop_constraint("ck_flights_window_booked_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_window_capacity_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_booked_seats_within_capacity", type_="check")
        batch.drop_constraint("ck_flights_booked_seats_nonnegative", type_="check")
        batch.drop_constraint("ck_flights_capacity_positive", type_="check")
        batch.drop_constraint("ck_flights_price_positive", type_="check")
        batch.drop_constraint("ck_flights_boarding_close_before_departure", type_="check")
        batch.drop_constraint("ck_flights_boarding_start_before_close", type_="check")
        batch.drop_constraint("ck_flights_check_in_open_before_close", type_="check")
        batch.drop_constraint("ck_flights_departure_before_arrival", type_="check")
