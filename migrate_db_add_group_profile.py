"""
Database migration script - adds the contact and identification columns that
a truck's Telegram group bio carries.

Carriers keep one group per truck and write the driver's name and phone, a
co-driver, the trailer and sometimes the VIN into its description. The bot
reads that and proposes it (see db/models.py's GroupProfileProposal), but
until now there was nowhere on Driver to put a phone number and nowhere on
Truck to put a VIN, so most of what a bio says had to be thrown away.

The group_profile_proposals table itself needs no migration here - it is new,
and init_db()'s create_all adds missing tables on the next startup. This
script is for the columns on tables that already exist, which create_all does
not touch.
"""
import sqlite3

NEW_COLUMNS = {
    "drivers": [
        ("phone", "VARCHAR(30)"),
        ("email", "VARCHAR(150)"),
        ("co_driver_name", "VARCHAR(150)"),
        ("co_driver_phone", "VARCHAR(30)"),
    ],
    "trucks": [
        ("vin", "VARCHAR(20)"),
    ],
}


def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()
    added = 0

    for table, columns in NEW_COLUMNS.items():
        cursor.execute(f'PRAGMA table_info({table})')
        existing = [row[1] for row in cursor.fetchall()]
        if not existing:
            print(f"{table}: no such table yet - init_db() will create it with these columns.")
            continue

        for name, sql_type in columns:
            if name in existing:
                print(f"{table}.{name} already exists.")
                continue
            print(f"Adding {table}.{name} ...")
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}')
            conn.commit()
            added += 1

    conn.close()
    print(f"\nDatabase migration complete - {added} column(s) added.")


if __name__ == "__main__":
    migrate()
