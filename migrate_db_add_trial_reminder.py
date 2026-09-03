"""
Database migration script - adds companies.trial_reminder_sent_at, the stamp
that keeps the trial-ending reminder from going out more than once.

The reminder job runs on a timer and asks which companies are inside the
notice window, so without somewhere to record that a company has already
been told, every pass would send another email.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('freight_pilot.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(companies)')
    existing = [row[1] for row in cursor.fetchall()]

    if 'trial_reminder_sent_at' in existing:
        print("companies.trial_reminder_sent_at already exists.")
    else:
        print("Adding companies.trial_reminder_sent_at ...")
        cursor.execute('ALTER TABLE companies ADD COLUMN trial_reminder_sent_at DATETIME')
        conn.commit()
        print("Added.")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
