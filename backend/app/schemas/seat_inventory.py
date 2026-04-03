from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SeatInventoryRead(BaseModel):
    id: int
    flight_id: int
    seat_number: str
    cabin: str
    seat_type: str
    is_booked: bool
    created_at: datetime

    model_config = {"from_attributes": True}
