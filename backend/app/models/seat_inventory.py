from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SeatInventory(Base):
    __tablename__ = "seat_inventory"
    __table_args__ = (
        UniqueConstraint("flight_id", "seat_number", name="uq_seat_inventory_flight_seat"),
        CheckConstraint(
            "cabin IN ('economy', 'premium_economy', 'business')",
            name="ck_seat_inventory_cabin_allowed",
        ),
        CheckConstraint(
            "seat_type IN ('standard', 'window', 'aisle', 'extra_legroom')",
            name="ck_seat_inventory_seat_type_allowed",
        ),
        CheckConstraint(
            "seat_type != 'extra_legroom' OR cabin = 'economy'",
            name="ck_seat_inventory_extra_legroom_only_economy",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flight_id: Mapped[int] = mapped_column(ForeignKey("flights.id"), nullable=False, index=True)
    seat_number: Mapped[str] = mapped_column(String(8), nullable=False)
    cabin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    seat_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_booked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    flight = relationship("Flight")
