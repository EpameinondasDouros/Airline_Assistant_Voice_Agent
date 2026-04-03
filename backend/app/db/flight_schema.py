from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


FLIGHT_SEAT_COLUMNS = (
    "window_seat_capacity",
    "window_seat_booked",
    "aisle_seat_capacity",
    "aisle_seat_booked",
    "extra_legroom_capacity",
    "extra_legroom_booked",
)


def ensure_flight_seat_columns(engine: Engine) -> None:
    """Backfill seat-capacity columns on older SQLite databases.

    Railway volumes may contain a pre-migration database that already has the
    flights table but not the newer seat breakdown columns. SQLite supports
    additive ALTER TABLE statements, so we add only the missing columns.
    """

    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "flights" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("flights")}
    missing_columns = [column for column in FLIGHT_SEAT_COLUMNS if column not in existing_columns]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column_name in missing_columns:
            connection.execute(
                text(
                    f"ALTER TABLE flights ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT 0"
                )
            )
