"""Add seat inventory table.

Revision ID: 20260403_0002
Revises: 20260402_0001
Create Date: 2026-04-03 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0002"
down_revision = "20260402_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seat_inventory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("flight_id", sa.Integer(), nullable=False),
        sa.Column("seat_number", sa.String(length=8), nullable=False),
        sa.Column("cabin", sa.String(length=32), nullable=False),
        sa.Column("seat_type", sa.String(length=32), nullable=False),
        sa.Column("is_booked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["flight_id"], ["flights.id"]),
        sa.UniqueConstraint("flight_id", "seat_number", name="uq_seat_inventory_flight_seat"),
    )
    op.create_index("ix_seat_inventory_cabin", "seat_inventory", ["cabin"])
    op.create_index("ix_seat_inventory_flight_id", "seat_inventory", ["flight_id"])
    op.create_index("ix_seat_inventory_is_booked", "seat_inventory", ["is_booked"])
    op.create_index("ix_seat_inventory_seat_type", "seat_inventory", ["seat_type"])


def downgrade() -> None:
    op.drop_index("ix_seat_inventory_seat_type", table_name="seat_inventory")
    op.drop_index("ix_seat_inventory_is_booked", table_name="seat_inventory")
    op.drop_index("ix_seat_inventory_flight_id", table_name="seat_inventory")
    op.drop_index("ix_seat_inventory_cabin", table_name="seat_inventory")
    op.drop_table("seat_inventory")
