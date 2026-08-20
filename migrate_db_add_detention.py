"""
Database migration script - adds the detention_requested_at column to the
loads table, used by the /detention bot command to avoid emailing the
broker twice for the same load.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('freight_pilot.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(loads)')
    columns = [row[1] for row in cursor.fetchall()]

    if "detention_requested_at" in columns:
        print("detention_requested_at column already exists!")
    else:
        print("Adding detention_requested_at column...")
        cursor.execute('ALTER TABLE loads ADD COLUMN detention_requested_at DATETIME')
        conn.commit()
        print("detention_requested_at column added successfully!")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
