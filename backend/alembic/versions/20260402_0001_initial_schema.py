"""Initial flight, booking, and knowledge schema.

Revision ID: 20260402_0001
Revises:
Create Date: 2026-04-02 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260402_0001"
down_revision = None
branch_labels = None
depends_on = None


flight_status_enum = sa.Enum("scheduled", "cancelled", name="flightstatus")
seat_class_enum = sa.Enum("economy", "premium_economy", "business", name="seatclass")
booking_status_enum = sa.Enum("confirmed", "cancelled", "rescheduled", name="bookingstatus")
refund_status_enum = sa.Enum(
    "not_requested",
    "pending",
    "approved",
    "rejected",
    "paid",
    name="refundstatus",
)
extra_type_enum = sa.Enum(
    "checked_bag",
    "cabin_bag",
    "sports_equipment",
    "pram",
    "pet",
    "special_item",
    name="extratype",
)
booking_event_type_enum = sa.Enum(
    "created",
    "cancelled",
    "rescheduled",
    "refund_requested",
    "refund_paid",
    "extra_added",
    name="bookingeventtype",
)


def upgrade() -> None:
    bind = op.get_bind()
    flight_status_enum.create(bind, checkfirst=True)
    seat_class_enum.create(bind, checkfirst=True)
    booking_status_enum.create(bind, checkfirst=True)
    refund_status_enum.create(bind, checkfirst=True)
    extra_type_enum.create(bind, checkfirst=True)
    booking_event_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "flights",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("flight_number", sa.String(length=12), nullable=False),
        sa.Column("origin_airport", sa.String(length=3), nullable=False),
        sa.Column("destination_airport", sa.String(length=3), nullable=False),
        sa.Column("departure_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal", sa.String(length=16), nullable=True),
        sa.Column("departure_gate", sa.String(length=16), nullable=True),
        sa.Column("check_in_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_in_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("boarding_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("boarding_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seat_class", seat_class_enum, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("booked_seats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_seat_capacity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_seat_booked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aisle_seat_capacity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aisle_seat_booked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra_legroom_capacity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra_legroom_booked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", flight_status_enum, nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("flight_number", "departure_time", "seat_class", name="uq_flights_number_departure_class"),
    )
    op.create_index("ix_flights_departure_time", "flights", ["departure_time"])
    op.create_index("ix_flights_destination_airport", "flights", ["destination_airport"])
    op.create_index("ix_flights_flight_number", "flights", ["flight_number"])
    op.create_index("ix_flights_origin_airport", "flights", ["origin_airport"])
    op.create_index("ix_flights_seat_class", "flights", ["seat_class"])

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("booking_reference", sa.String(length=12), nullable=False),
        sa.Column("flight_id", sa.Integer(), nullable=False),
        sa.Column("rescheduled_from_booking_id", sa.Integer(), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=False),
        sa.Column("contact_email", sa.String(length=255), nullable=False),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", booking_status_enum, nullable=False, server_default="confirmed"),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("refund_status", refund_status_enum, nullable=False, server_default="not_requested"),
        sa.Column("refund_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["flight_id"], ["flights.id"]),
        sa.ForeignKeyConstraint(["rescheduled_from_booking_id"], ["bookings.id"]),
        sa.UniqueConstraint("booking_reference"),
    )
    op.create_index("ix_bookings_booking_reference", "bookings", ["booking_reference"])
    op.create_index("ix_bookings_contact_email", "bookings", ["contact_email"])
    op.create_index("ix_bookings_flight_id", "bookings", ["flight_id"])
    op.create_index("ix_bookings_rescheduled_from_booking_id", "bookings", ["rescheduled_from_booking_id"])

    op.create_table(
        "booking_passengers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("passenger_type", sa.String(length=32), nullable=False, server_default="adult"),
        sa.Column("seat_preference", sa.String(length=32), nullable=True),
        sa.Column("seat_number", sa.String(length=8), nullable=True),
        sa.Column("assistance_type", sa.String(length=64), nullable=True),
        sa.Column("assistance_notes", sa.Text(), nullable=True),
        sa.Column("mobility_assistance_required", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
    )
    op.create_index("ix_booking_passengers_booking_id", "booking_passengers", ["booking_id"])

    op.create_table(
        "booking_extras",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("extra_type", extra_type_enum, nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
    )
    op.create_index("ix_booking_extras_booking_id", "booking_extras", ["booking_id"])
    op.create_index("ix_booking_extras_extra_type", "booking_extras", ["extra_type"])

    op.create_table(
        "booking_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("event_type", booking_event_type_enum, nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
    )
    op.create_index("ix_booking_events_booking_id", "booking_events", ["booking_id"])
    op.create_index("ix_booking_events_event_type", "booking_events", ["event_type"])

    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_articles_topic", "knowledge_articles", ["topic"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_knowledge_articles_topic", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")

    op.drop_index("ix_booking_events_event_type", table_name="booking_events")
    op.drop_index("ix_booking_events_booking_id", table_name="booking_events")
    op.drop_table("booking_events")

    op.drop_index("ix_booking_extras_extra_type", table_name="booking_extras")
    op.drop_index("ix_booking_extras_booking_id", table_name="booking_extras")
    op.drop_table("booking_extras")

    op.drop_index("ix_booking_passengers_booking_id", table_name="booking_passengers")
    op.drop_table("booking_passengers")

    op.drop_index("ix_bookings_rescheduled_from_booking_id", table_name="bookings")
    op.drop_index("ix_bookings_flight_id", table_name="bookings")
    op.drop_index("ix_bookings_contact_email", table_name="bookings")
    op.drop_index("ix_bookings_booking_reference", table_name="bookings")
    op.drop_table("bookings")

    op.drop_index("ix_flights_seat_class", table_name="flights")
    op.drop_index("ix_flights_origin_airport", table_name="flights")
    op.drop_index("ix_flights_flight_number", table_name="flights")
    op.drop_index("ix_flights_destination_airport", table_name="flights")
    op.drop_index("ix_flights_departure_time", table_name="flights")
    op.drop_table("flights")

    booking_event_type_enum.drop(bind, checkfirst=True)
    extra_type_enum.drop(bind, checkfirst=True)
    refund_status_enum.drop(bind, checkfirst=True)
    booking_status_enum.drop(bind, checkfirst=True)
    seat_class_enum.drop(bind, checkfirst=True)
    flight_status_enum.drop(bind, checkfirst=True)
