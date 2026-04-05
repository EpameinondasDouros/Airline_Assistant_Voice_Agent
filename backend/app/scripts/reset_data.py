from __future__ import annotations

from sqlalchemy import text

from app.db.session import SessionLocal


TABLES = [
    "booking_events",
    "booking_extras",
    "booking_passengers",
    "bookings",
    "seat_inventory",
    "knowledge_articles",
    "flights",
]


def main() -> None:
    session = SessionLocal()
    try:
        for table in TABLES:
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
        print("Existing data cleared before reseeding.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
