from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.flight_schema import ensure_flight_seat_columns
from app.db.seat_inventory import sync_seat_inventory
from app.db.session import SessionLocal, engine
from app.models.flight import Flight, FlightStatus, SeatClass


BASE_DATE = date(2026, 4, 6)

ROUTES = [
    {
        "flight_number": "TM101",
        "origin_airport": "ATH",
        "destination_airport": "LHR",
        "departure_time": time(8, 15),
        "duration_hours": 4,
        "base_price": Decimal("120.00"),
    },
    {
        "flight_number": "TM102",
        "origin_airport": "LHR",
        "destination_airport": "ATH",
        "departure_time": time(13, 5),
        "duration_hours": 4,
        "base_price": Decimal("125.00"),
    },
    {
        "flight_number": "TM205",
        "origin_airport": "ATH",
        "destination_airport": "FCO",
        "departure_time": time(12, 30),
        "duration_hours": 2,
        "base_price": Decimal("85.00"),
    },
    {
        "flight_number": "TM206",
        "origin_airport": "FCO",
        "destination_airport": "ATH",
        "departure_time": time(15, 20),
        "duration_hours": 2,
        "base_price": Decimal("90.00"),
    },
    {
        "flight_number": "TM310",
        "origin_airport": "ATH",
        "destination_airport": "CDG",
        "departure_time": time(16, 45),
        "duration_hours": 3,
        "base_price": Decimal("110.00"),
    },
    {
        "flight_number": "TM311",
        "origin_airport": "CDG",
        "destination_airport": "ATH",
        "departure_time": time(9, 10),
        "duration_hours": 3,
        "base_price": Decimal("115.00"),
    },
    {
        "flight_number": "TM411",
        "origin_airport": "ATH",
        "destination_airport": "JFK",
        "departure_time": time(10, 0),
        "duration_hours": 10,
        "base_price": Decimal("540.00"),
    },
    {
        "flight_number": "TM412",
        "origin_airport": "JFK",
        "destination_airport": "ATH",
        "departure_time": time(18, 40),
        "duration_hours": 9,
        "base_price": Decimal("560.00"),
    },
    {
        "flight_number": "TM520",
        "origin_airport": "MAD",
        "destination_airport": "AMS",
        "departure_time": time(7, 30),
        "duration_hours": 3,
        "base_price": Decimal("105.00"),
    },
    {
        "flight_number": "TM521",
        "origin_airport": "AMS",
        "destination_airport": "MAD",
        "departure_time": time(11, 15),
        "duration_hours": 3,
        "base_price": Decimal("110.00"),
    },
    {
        "flight_number": "TM630",
        "origin_airport": "FRA",
        "destination_airport": "DXB",
        "departure_time": time(14, 0),
        "duration_hours": 6,
        "base_price": Decimal("280.00"),
    },
    {
        "flight_number": "TM631",
        "origin_airport": "DXB",
        "destination_airport": "FRA",
        "departure_time": time(6, 50),
        "duration_hours": 6,
        "base_price": Decimal("295.00"),
    },
]

CLASS_CONFIG = {
    SeatClass.ECONOMY: {
        "capacity": 120,
        "price_multiplier": Decimal("1.00"),
        "window_seat_capacity": 40,
        "aisle_seat_capacity": 40,
        "extra_legroom_capacity": 18,
    },
    SeatClass.PREMIUM_ECONOMY: {
        "capacity": 36,
        "price_multiplier": Decimal("1.55"),
        "window_seat_capacity": 12,
        "aisle_seat_capacity": 12,
        "extra_legroom_capacity": 0,
    },
    SeatClass.BUSINESS: {
        "capacity": 16,
        "price_multiplier": Decimal("2.40"),
        "window_seat_capacity": 8,
        "aisle_seat_capacity": 8,
        "extra_legroom_capacity": 0,
    },
}


def normalize_sqlite_datetime(value: datetime) -> datetime:
    """Normalize datetimes to naive UTC so duplicate checks match SQLite storage."""

    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def build_seed_flights() -> Iterable[Flight]:
    for day_offset in range(7):
        flight_date = BASE_DATE + timedelta(days=day_offset)
        for route in ROUTES:
            departure = normalize_sqlite_datetime(
                datetime.combine(flight_date, route["departure_time"], tzinfo=UTC)
            )
            arrival = departure + timedelta(hours=route["duration_hours"])
            check_in_open_at = departure - timedelta(hours=3)
            check_in_close_at = departure - timedelta(minutes=45)
            boarding_starts_at = departure - timedelta(minutes=50)
            boarding_closes_at = departure - timedelta(minutes=20)

            for seat_class, config in CLASS_CONFIG.items():
                yield Flight(
                    flight_number=route["flight_number"],
                    origin_airport=route["origin_airport"],
                    destination_airport=route["destination_airport"],
                    departure_time=departure,
                    arrival_time=arrival,
                    terminal=f"T{(day_offset % 3) + 1}",
                    departure_gate=f"{chr(65 + (day_offset % 5))}{10 + (day_offset % 9)}",
                    check_in_open_at=check_in_open_at,
                    check_in_close_at=check_in_close_at,
                    boarding_starts_at=boarding_starts_at,
                    boarding_closes_at=boarding_closes_at,
                    seat_class=seat_class,
                    price=(route["base_price"] * config["price_multiplier"]).quantize(Decimal("0.01")),
                    capacity=config["capacity"],
                    booked_seats=0,
                    window_seat_capacity=config["window_seat_capacity"],
                    window_seat_booked=0,
                    aisle_seat_capacity=config["aisle_seat_capacity"],
                    aisle_seat_booked=0,
                    extra_legroom_capacity=config["extra_legroom_capacity"],
                    extra_legroom_booked=0,
                    status=FlightStatus.SCHEDULED,
                )


def main() -> None:
    ensure_flight_seat_columns(engine)
    session = SessionLocal()
    try:
        existing_keys = {
            (
                flight.flight_number,
                normalize_sqlite_datetime(flight.departure_time),
                flight.seat_class,
            )
            for flight in session.scalars(select(Flight))
        }

        created = 0
        for flight in build_seed_flights():
            key = (flight.flight_number, flight.departure_time, flight.seat_class)
            if key in existing_keys:
                continue
            session.add(flight)
            existing_keys.add(key)
            created += 1

        session.commit()
        print(f"Seed complete. Inserted {created} flights.")
    finally:
        session.close()
    created_seats = sync_seat_inventory(engine)
    print(f"Seat inventory sync complete. Inserted {created_seats} seats.")


if __name__ == "__main__":
    main()
