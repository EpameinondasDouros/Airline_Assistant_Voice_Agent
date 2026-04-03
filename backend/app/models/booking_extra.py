from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExtraType(str, enum.Enum):
    CHECKED_BAG = "checked_bag"
    CABIN_BAG = "cabin_bag"
    SPORTS_EQUIPMENT = "sports_equipment"
    PRAM = "pram"
    PET = "pet"
    SPECIAL_ITEM = "special_item"


class BookingExtra(Base):
    __tablename__ = "booking_extras"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_booking_extras_quantity_positive"),
        CheckConstraint("price >= 0", name="ck_booking_extras_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    extra_type: Mapped[ExtraType] = mapped_column(Enum(ExtraType), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    booking = relationship("Booking", back_populates="extras")
