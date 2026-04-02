from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingPassenger(Base):
    __tablename__ = "booking_passengers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
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
