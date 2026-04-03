"""ORM models exposed for metadata discovery."""

from app.models.booking import Booking, BookingStatus, RefundStatus
from app.models.booking_event import BookingEvent, BookingEventType
from app.models.booking_extra import BookingExtra, ExtraType
from app.models.booking_passenger import BookingPassenger
from app.models.flight import Flight, FlightStatus, SeatClass, SeatPreference
from app.models.knowledge_article import KnowledgeArticle
from app.models.seat_inventory import SeatInventory

__all__ = [
    "Booking",
    "BookingEvent",
    "BookingExtra",
    "BookingPassenger",
    "BookingEventType",
    "BookingStatus",
    "ExtraType",
    "Flight",
    "FlightStatus",
    "KnowledgeArticle",
    "RefundStatus",
    "SeatClass",
    "SeatPreference",
    "SeatInventory",
]
