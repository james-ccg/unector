"""
Database migration script - adds loads.pinned_message_id, which remembers
the load card the bot pinned in a driver's group.

Without it the bot can pin the newest load but never take the last one
down, so a group accumulates a pin per load until the driver is looking at
a stack of finished jobs. The id is written when the pin succeeds and read
by the next dispatch, which unpins it before pinning its own.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(loads)')
    existing = [row[1] for row in cursor.fetchall()]

    if 'pinned_message_id' in existing:
        print("loads.pinned_message_id already exists.")
    else:
        print("Adding loads.pinned_message_id ...")
        cursor.execute('ALTER TABLE loads ADD COLUMN pinned_message_id INTEGER')
        conn.commit()
        print("Added.")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
