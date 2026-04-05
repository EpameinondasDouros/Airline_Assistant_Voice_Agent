from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import inspect, select, func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.booking import Booking, BookingStatus
from app.models.flight import Flight, SeatClass, SeatPreference
from app.models.seat_inventory import SeatInventory


SEAT_LAYOUTS: dict[str, dict[str, object]] = {
    "business": {
        "rows": range(1, 5),
        "columns": ("A", "B", "C", "D"),
    },
    "premium_economy": {
        "rows": range(5, 10),
        "columns": ("A", "B", "C", "D", "E", "F"),
    },
    "economy": {
        "rows": range(10, 30),
        "columns": ("A", "B", "C", "D", "E", "F"),
    },
}


def _seat_type_for(seat_class: str, row: int, column: str) -> str:
    if seat_class == SeatClass.BUSINESS.value:
        if column in {"A", "D"}:
            return SeatPreference.WINDOW.value
        if column in {"B", "C"}:
            return SeatPreference.AISLE.value
        return "standard"
    if column in {"A", "F"}:
        return SeatPreference.WINDOW.value
    if column in {"C", "D"}:
        return SeatPreference.AISLE.value
    if seat_class == SeatClass.ECONOMY.value and row in {18, 19, 20}:
        return SeatPreference.EXTRA_LEGROOM.value
    return "standard"


def iter_seat_inventory(flight: Flight) -> Iterable[SeatInventory]:
    seat_class = flight.seat_class.value
    layout = SEAT_LAYOUTS[seat_class]
    for row in layout["rows"]:
        for column in layout["columns"]:
            seat_number = f"{row}{column}"
            yield SeatInventory(
                flight_id=flight.id,
                seat_number=seat_number,
                cabin=seat_class,
                seat_type=_seat_type_for(seat_class, row, column),
                is_booked=False,
            )


def ensure_seat_inventory_table(engine: Engine) -> None:
    """Create the seat inventory table if it is missing."""

    inspector = inspect(engine)
    if "seat_inventory" in inspector.get_table_names():
        return
    SeatInventory.__table__.create(bind=engine, checkfirst=True)


def sync_seat_inventory(engine: Engine) -> int:
    """Populate missing seat inventory rows for existing flights."""

    ensure_seat_inventory_table(engine)
    session = SessionLocal()
    try:
        existing_pairs = {(row.flight_id, row.seat_number) for row in session.scalars(select(SeatInventory))}
        created = 0
        for flight in session.scalars(select(Flight)):
            for seat in iter_seat_inventory(flight):
                key = (seat.flight_id, seat.seat_number)
                if key in existing_pairs:
                    continue
                session.add(seat)
                existing_pairs.add(key)
                created += 1
        session.commit()
        return created
    finally:
        session.close()


def seat_inventory_counts(session, flight_id: int) -> dict[str, int]:
    """Return aggregate seat counts for a flight from seat inventory rows."""

    total = session.scalar(select(func.count()).select_from(SeatInventory).where(SeatInventory.flight_id == flight_id)) or 0
    booked = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(True),
        )
    ) or 0
    window_capacity = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.seat_type == "window",
        )
    ) or 0
    aisle_capacity = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.seat_type == "aisle",
        )
    ) or 0
    extra_capacity = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.seat_type == "extra_legroom",
        )
    ) or 0
    window_booked = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(True),
            SeatInventory.seat_type == "window",
        )
    ) or 0
    aisle_booked = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(True),
            SeatInventory.seat_type == "aisle",
        )
    ) or 0
    extra_booked = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(True),
            SeatInventory.seat_type == "extra_legroom",
        )
    ) or 0
    window_available = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(False),
            SeatInventory.seat_type == "window",
        )
    ) or 0
    aisle_available = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(False),
            SeatInventory.seat_type == "aisle",
        )
    ) or 0
    extra_available = session.scalar(
        select(func.count()).select_from(SeatInventory).where(
            SeatInventory.flight_id == flight_id,
            SeatInventory.is_booked.is_(False),
            SeatInventory.seat_type == "extra_legroom",
        )
    ) or 0
    return {
        "available_seats": total - booked,
        "booked_seats": booked,
        "window_seat_capacity": window_capacity,
        "window_seat_booked": window_booked,
        "window_seat_available": window_available,
        "aisle_seat_capacity": aisle_capacity,
        "aisle_seat_booked": aisle_booked,
        "aisle_seat_available": aisle_available,
        "extra_legroom_capacity": extra_capacity,
        "extra_legroom_booked": extra_booked,
        "extra_legroom_available": extra_available,
    }


def refresh_flight_seat_state(session: Session, flight: Flight) -> dict[str, int]:
    """Synchronize denormalized flight seat counters from inventory rows."""

    session.flush()
    counts = seat_inventory_counts(session, flight.id)
    flight.booked_seats = counts["booked_seats"]
    flight.window_seat_capacity = counts["window_seat_capacity"]
    flight.window_seat_booked = counts["window_seat_booked"]
    flight.aisle_seat_capacity = counts["aisle_seat_capacity"]
    flight.aisle_seat_booked = counts["aisle_seat_booked"]
    flight.extra_legroom_capacity = counts["extra_legroom_capacity"]
    flight.extra_legroom_booked = counts["extra_legroom_booked"]
    return counts


def reconcile_seat_state(session: Session) -> dict[str, int]:
    """Rebuild booked seat flags and flight counters from confirmed bookings."""

    flights = list(session.scalars(select(Flight)))
    for inventory in session.scalars(select(SeatInventory)):
        inventory.is_booked = False

    marked_inventory = 0
    confirmed_bookings = session.scalars(
        select(Booking)
        .where(Booking.status == BookingStatus.CONFIRMED)
        .options(selectinload(Booking.passengers))
    )
    for booking in confirmed_bookings:
        for passenger in booking.passengers:
            if passenger.seat_number is None:
                continue
            inventory = session.scalar(
                select(SeatInventory).where(
                    SeatInventory.flight_id == booking.flight_id,
                    SeatInventory.seat_number == passenger.seat_number.upper().strip(),
                )
            )
            if inventory is None:
                continue
            inventory.is_booked = True
            marked_inventory += 1

    reconciled_flights = 0
    for flight in flights:
        refresh_flight_seat_state(session, flight)
        reconciled_flights += 1

    session.flush()
    return {
        "inventory_rows_marked_booked": marked_inventory,
        "flights_reconciled": reconciled_flights,
    }
