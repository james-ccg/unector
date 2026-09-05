"""
Database migration script - adds the billing_events table, a company's
billing history and the record of who caused each line of it.

create_all() makes tables that do not exist yet, so a fresh database needs
nothing from this. An existing one does: it already has every other table,
so create_all sees nothing missing at the database level and never looks
inside for a new one.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()

    existing = [
        row[0] for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='billing_events'"
        )
    ]
    if existing:
        print("billing_events already exists.")
    else:
        print("Creating billing_events ...")
        cursor.execute("""
            CREATE TABLE billing_events (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                kind VARCHAR(30) NOT NULL,
                tier VARCHAR(50),
                billing_interval VARCHAR(10),
                amount_cents INTEGER,
                currency VARCHAR(10),
                actor_type VARCHAR(20),
                actor_id INTEGER,
                actor_label VARCHAR(200),
                stripe_event_id VARCHAR(100),
                note TEXT,
                created_at DATETIME,
                CONSTRAINT uq_billing_event_stripe_id UNIQUE (stripe_event_id)
            )
        """)
        cursor.execute("CREATE INDEX ix_billing_events_company_id ON billing_events (company_id)")
        cursor.execute("CREATE INDEX ix_billing_events_created_at ON billing_events (created_at)")
        conn.commit()
        print("Created.")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
