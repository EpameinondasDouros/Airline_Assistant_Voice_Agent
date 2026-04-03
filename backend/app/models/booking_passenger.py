from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingPassenger(Base):
    __tablename__ = "booking_passengers"
    __table_args__ = (
        Index("ix_booking_passengers_identity", "first_name", "last_name", "date_of_birth"),
        CheckConstraint(
            "seat_preference IS NULL OR seat_preference IN ('window', 'aisle', 'extra_legroom')",
            name="ck_booking_passengers_seat_preference_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    passenger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="adult", server_default="adult")
    seat_preference: Mapped[str | None] = mapped_column(String(32))
    seat_number: Mapped[str | None] = mapped_column(String(8))
    assistance_type: Mapped[str | None] = mapped_column(String(64))
    assistance_notes: Mapped[str | None] = mapped_column(Text)
    mobility_assistance_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    booking = relationship("Booking", back_populates="passengers")
