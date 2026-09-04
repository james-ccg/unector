"""
Database migration script - adds the alerted_rule_ids column to the loads
table, used by the customizable location-alert rules to track which rule
(by id) has already fired for a load so it never repeats.

The location_alert_rules table itself is new and doesn't need a migration -
init_db() (SQLAlchemy's Base.metadata.create_all) creates any missing table
automatically on startup. Only new *columns* on an already-existing table
need this kind of explicit ALTER TABLE script.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(loads)')
    columns = [row[1] for row in cursor.fetchall()]

    if "alerted_rule_ids" in columns:
        print("alerted_rule_ids column already exists!")
    else:
        print("Adding alerted_rule_ids column...")
        cursor.execute('ALTER TABLE loads ADD COLUMN alerted_rule_ids TEXT')
        conn.commit()
        print("alerted_rule_ids column added successfully!")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
