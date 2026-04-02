from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingEventType(str, enum.Enum):
    CREATED = "created"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"
    REFUND_REQUESTED = "refund_requested"
    REFUND_PAID = "refund_paid"
    EXTRA_ADDED = "extra_added"


class BookingEvent(Base):
    __tablename__ = "booking_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    event_type: Mapped[BookingEventType] = mapped_column(Enum(BookingEventType), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)

    booking = relationship("Booking", back_populates="events")
