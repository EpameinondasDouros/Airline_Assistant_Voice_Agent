from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.booking import BookingStatus, RefundStatus
from app.models.booking_event import BookingEventType
from app.models.booking_extra import ExtraType
from app.models.flight import FlightStatus, SeatClass, SeatPreference


class PassengerCreate(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: date
    passenger_type: str = "adult"
    seat_preference: SeatPreference | None = None
    seat_number: str | None = None
    assistance_type: str | None = None
    assistance_notes: str | None = None
    mobility_assistance_required: bool = False


class ExtraCreate(BaseModel):
    extra_type: ExtraType
    quantity: int = Field(default=1, ge=1)
    price: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    description: str | None = None

    @field_validator("extra_type", mode="before")
    @classmethod
    def normalize_extra_type(cls, value: object) -> object:
        if isinstance(value, ExtraType):
            return value
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "checkedbag": "checked_bag",
            "bag": "checked_bag",
            "bags": "checked_bag",
            "checked_luggage": "checked_bag",
            "cabinbag": "cabin_bag",
            "carry_on": "cabin_bag",
            "carryon": "cabin_bag",
            "sports": "sports_equipment",
            "stroller": "pram",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized


class BookingCreate(BaseModel):
    flight_id: int
    contact_name: str
    contact_email: EmailStr
    contact_phone: str | None = None
    passengers: list[PassengerCreate] = Field(min_length=1)
    extras: list[ExtraCreate] = Field(default_factory=list)


class BookingCancelRequest(BaseModel):
    reason: str
    refund_status: RefundStatus = RefundStatus.PENDING
    refund_amount: Decimal | None = Field(default=None, ge=Decimal("0.00"))


class BookingRescheduleRequest(BaseModel):
    new_flight_id: int


class BookingAddExtrasRequest(BaseModel):
    extras: list[ExtraCreate] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_flat_extra_payload(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("extras") is not None:
            return data
        if data.get("extra_type") is None:
            return data
        return {
            "extras": [
                {
                    "extra_type": data.get("extra_type"),
                    "quantity": data.get("quantity", 1),
                    "price": data.get("price", Decimal("0.00")),
                    "description": data.get("description"),
                }
            ]
        }


class BookingPassengerRead(BaseModel):
    id: int
    first_name: str
    last_name: str
    date_of_birth: date
    passenger_type: str
    seat_preference: SeatPreference | None
    seat_number: str | None
    assistance_type: str | None
    assistance_notes: str | None
    mobility_assistance_required: bool

    model_config = {"from_attributes": True}


class BookingExtraRead(BaseModel):
    id: int
    extra_type: ExtraType
    quantity: int
    price: Decimal
    description: str | None

    model_config = {"from_attributes": True}


class BookingEventRead(BaseModel):
    id: int
    event_type: BookingEventType
    event_time: datetime
    summary: str
    details: str | None

    model_config = {"from_attributes": True}


class BookingRead(BaseModel):
    id: int
    booking_reference: str
    flight_id: int
    rescheduled_from_booking_id: int | None
    contact_name: str
    contact_email: EmailStr
    contact_phone: str | None
    total_price: Decimal
    status: BookingStatus
    cancelled_at: datetime | None
    cancellation_reason: str | None
    refund_status: RefundStatus
    refund_amount: Decimal | None
    created_at: datetime
    updated_at: datetime
    passengers: list[BookingPassengerRead]
    extras: list[BookingExtraRead]
    events: list[BookingEventRead]

    model_config = {"from_attributes": True}


class BookedTripFlightRead(BaseModel):
    id: int
    flight_number: str
    origin_airport: str
    destination_airport: str
    departure_time: datetime
    arrival_time: datetime
    terminal: str | None
    departure_gate: str | None
    seat_class: SeatClass
    price: Decimal
    status: FlightStatus

    model_config = {"from_attributes": True}


class BookedTripRead(BaseModel):
    id: int
    booking_reference: str
    contact_name: str
    contact_email: EmailStr
    contact_phone: str | None
    total_price: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime
    passengers: list[BookingPassengerRead]
    extras: list[BookingExtraRead]
    flight: BookedTripFlightRead

    model_config = {"from_attributes": True}


class BookingSummaryRead(BaseModel):
    id: int
    booking_reference: str
    flight_id: int
    contact_name: str
    contact_email: EmailStr
    total_price: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RescheduleResponse(BaseModel):
    previous_booking_reference: str
    new_booking: BookingRead


class BookingCreateResponse(BaseModel):
    booking: BookingRead


class FlightSelectionRead(BaseModel):
    flight_id: int
    flight_number: str
    departure_time: datetime
    arrival_time: datetime
    seat_class: SeatClass
    price: Decimal
