"""
Database migration script - adds Stripe billing columns to the companies
table (subscription_tier already existed; this adds everything needed to
actually track a Stripe subscription against it). The new trial_redemptions
table needs no migration here - it's created automatically on next app
startup by db/database.py's init_db() (Base.metadata.create_all only adds
missing tables, it doesn't touch existing ones - that's what this script is
for).
"""
import sqlite3

NEW_COLUMNS = [
    ("subscription_status", "VARCHAR(20)"),
    ("stripe_customer_id", "VARCHAR(100)"),
    ("stripe_subscription_id", "VARCHAR(100)"),
    ("trial_ends_at", "DATETIME"),
    ("billing_interval", "VARCHAR(10)"),
]

def migrate():
    conn = sqlite3.connect('freight_pilot.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(companies)')
    columns = [row[1] for row in cursor.fetchall()]

    print(f"Current columns in companies table: {len(columns)}")
    for col in columns:
        print(f"  - {col}")

    print()
    for name, sql_type in NEW_COLUMNS:
        if name in columns:
            print(f"{name} column already exists!")
            continue
        print(f"Adding {name} column...")
        cursor.execute(f'ALTER TABLE companies ADD COLUMN {name} {sql_type}')
        conn.commit()
        print(f"{name} column added successfully!")

    # subscription_tier already exists from an earlier migration/create_all,
    # but its meaning changes here: it used to default to "trial" and was
    # never enforced; existing rows get backfilled to "free" (the new,
    # equivalent starting tier) unless they were already set to something
    # else in normal use.
    cursor.execute("UPDATE companies SET subscription_tier = 'free' WHERE subscription_tier = 'trial'")
    if cursor.rowcount:
        print(f"\nBackfilled subscription_tier: 'trial' -> 'free' on {cursor.rowcount} row(s)")
    cursor.execute("UPDATE companies SET subscription_status = 'none' WHERE subscription_status IS NULL")
    conn.commit()

    conn.close()
    print("\nDatabase migration complete!")

if __name__ == "__main__":
    migrate()
