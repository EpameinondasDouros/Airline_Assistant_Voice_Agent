from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class RefundStatus(str, enum.Enum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_reference: Mapped[str] = mapped_column(String(12), nullable=False, unique=True, index=True)
    flight_id: Mapped[int] = mapped_column(ForeignKey("flights.id"), nullable=False, index=True)
    rescheduled_from_booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus),
        nullable=False,
        default=BookingStatus.CONFIRMED,
        server_default=BookingStatus.CONFIRMED.value,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    refund_status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus),
        nullable=False,
        default=RefundStatus.NOT_REQUESTED,
        server_default=RefundStatus.NOT_REQUESTED.value,
    )
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    flight = relationship("Flight", back_populates="bookings")
    rescheduled_from = relationship("Booking", remote_side=[id], back_populates="rescheduled_to")
    rescheduled_to = relationship("Booking", back_populates="rescheduled_from")
    passengers = relationship(
        "BookingPassenger",
        back_populates="booking",
        cascade="all, delete-orphan",
    )
    extras = relationship(
        "BookingExtra",
        back_populates="booking",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "BookingEvent",
        back_populates="booking",
        cascade="all, delete-orphan",
    )
