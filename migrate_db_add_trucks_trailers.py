"""
Adds the trucks/trailers tables and moves the Samsara link onto the truck.

init_db()'s create_all() creates brand-new tables but never ALTERs an
existing one, so `drivers.truck_id` has to be added by hand here - same
reason every other migrate_db_add_*.py in this directory exists.

Safe to run more than once: every step checks first.

On the Samsara column: it moves from drivers to trucks because the
telematics device is bolted to the vehicle, not issued to a person. Any
driver that still has one is given a truck to carry it, so no GPS link is
lost. The old drivers.samsara_vehicle_id column is deliberately LEFT IN
PLACE rather than dropped - SQLite's DROP COLUMN is recent and unforgiving,
and a stray unused column costs nothing next to the risk of rewriting a
table that holds real dispatch history.
"""
import sqlite3
from pathlib import Path

from config import DATABASE_URL


def _db_path() -> Path:
    if not DATABASE_URL.startswith("sqlite:///"):
        raise SystemExit(f"This migration only handles SQLite; got {DATABASE_URL!r}")
    return Path(DATABASE_URL.replace("sqlite:///", ""))


def _columns(cur, table: str) -> set[str]:
    return {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}


def _tables(cur) -> set[str]:
    return {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def main() -> None:
    path = _db_path()
    if not path.exists():
        print(f"No database at {path} yet - nothing to migrate (init_db will create it fresh).")
        return

    con = sqlite3.connect(path)
    cur = con.cursor()
    existing = _tables(cur)

    if "trailers" not in existing:
        cur.execute(
            """
            CREATE TABLE trailers (
                id INTEGER NOT NULL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                unit_number VARCHAR(30) NOT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_trailer_unit_per_company UNIQUE (company_id, unit_number)
            )
            """
        )
        print("created table: trailers")
    else:
        print("trailers already exists - skipped")

    if "trucks" not in existing:
        cur.execute(
            """
            CREATE TABLE trucks (
                id INTEGER NOT NULL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                unit_number VARCHAR(30) NOT NULL,
                samsara_vehicle_id VARCHAR(50),
                trailer_id INTEGER REFERENCES trailers(id),
                active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_truck_unit_per_company UNIQUE (company_id, unit_number)
            )
            """
        )
        print("created table: trucks")
    else:
        print("trucks already exists - skipped")

    if "truck_id" not in _columns(cur, "drivers"):
        cur.execute("ALTER TABLE drivers ADD COLUMN truck_id INTEGER REFERENCES trucks(id)")
        print("added column: drivers.truck_id")
    else:
        print("drivers.truck_id already exists - skipped")

    # Carry any existing GPS link across, so a fleet that already had Samsara
    # working keeps working. Each such driver gets a truck to hang it on,
    # named after the driver's bot id since we have no real unit number for
    # them - the owner can rename it afterwards.
    if "samsara_vehicle_id" in _columns(cur, "drivers"):
        stranded = cur.execute(
            """
            SELECT id, company_id, driver_bot_id, samsara_vehicle_id
            FROM drivers
            WHERE samsara_vehicle_id IS NOT NULL AND truck_id IS NULL
            """
        ).fetchall()
        for driver_id, company_id, bot_id, vehicle_id in stranded:
            cur.execute(
                """
                INSERT INTO trucks (company_id, unit_number, samsara_vehicle_id, active, created_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                """,
                (company_id, f"UNIT-{bot_id}", vehicle_id),
            )
            cur.execute("UPDATE drivers SET truck_id = ? WHERE id = ?", (cur.lastrowid, driver_id))
        print(f"moved {len(stranded)} Samsara link(s) from drivers onto new trucks")

    con.commit()
    con.close()
    print("done.")


if __name__ == "__main__":
    main()
