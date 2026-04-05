from __future__ import annotations

from app.db.flight_schema import ensure_flight_seat_columns
from app.db.seat_inventory import reconcile_seat_state, sync_seat_inventory
from app.db.session import SessionLocal, engine


def main() -> None:
    ensure_flight_seat_columns(engine)
    created_seats = sync_seat_inventory(engine)

    session = SessionLocal()
    try:
        summary = reconcile_seat_state(session)
        session.commit()
        print(
            "Seat state reconciled. "
            f"Inserted {created_seats} missing seat rows; "
            f"marked {summary['inventory_rows_marked_booked']} inventory rows booked; "
            f"reconciled {summary['flights_reconciled']} flights."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
