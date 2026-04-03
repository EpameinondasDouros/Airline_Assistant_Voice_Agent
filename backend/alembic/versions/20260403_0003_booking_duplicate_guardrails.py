"""Add booking duplicate guardrail indexes.

Revision ID: 20260403_0003
Revises: 20260403_0002
Create Date: 2026-04-03 00:03:00
"""

from __future__ import annotations

from alembic import op


revision = "20260403_0003"
down_revision = "20260403_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_bookings_flight_status_refund_status",
        "bookings",
        ["flight_id", "status", "refund_status"],
    )
    op.create_index(
        "ix_booking_passengers_identity",
        "booking_passengers",
        ["first_name", "last_name", "date_of_birth"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_passengers_identity", table_name="booking_passengers")
    op.drop_index("ix_bookings_flight_status_refund_status", table_name="bookings")
