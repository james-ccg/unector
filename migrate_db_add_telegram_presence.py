"""
Database migration script - adds two columns to two_factor_secrets:
telegram_username and telegram_blocked_at.

The first is which Telegram account is connected, so the settings screen can
say more than "connected". The second is whether the person has blocked the
bot, which Telegram reports through my_chat_member.

Blocking deliberately does not remove the connection. Unblocking should just
resume, and making somebody re-link after every block is a chore they would
not do - so the state is recorded and shown rather than acted on.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(two_factor_secrets)')
    existing = [row[1] for row in cursor.fetchall()]

    for column, ddl in (
        ("telegram_username", "VARCHAR(64)"),
        ("telegram_blocked_at", "DATETIME"),
    ):
        if column in existing:
            print(f"two_factor_secrets.{column} already exists.")
            continue
        print(f"Adding two_factor_secrets.{column} ...")
        cursor.execute(f"ALTER TABLE two_factor_secrets ADD COLUMN {column} {ddl}")
        conn.commit()
        print("Added.")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
