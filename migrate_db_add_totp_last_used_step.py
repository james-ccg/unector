"""
Database migration script - adds the totp_last_used_step column to the
two_factor_secrets table, used to stop a TOTP code from being replayed
within its ~90s validity window (see services/twofactor_service.py's
verify_totp_code). Any database created before that feature existed is
missing this column - since it's on an EXISTING table, init_db()'s
create_all() never adds it on its own (only brand-new tables get created
automatically), so any login that reaches the 2FA-status check crashes
with a 500 until this migration runs.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(two_factor_secrets)')
    columns = [row[1] for row in cursor.fetchall()]

    if "totp_last_used_step" in columns:
        print("totp_last_used_step column already exists!")
    else:
        print("Adding totp_last_used_step column...")
        cursor.execute('ALTER TABLE two_factor_secrets ADD COLUMN totp_last_used_step INTEGER')
        conn.commit()
        print("totp_last_used_step column added successfully!")

    conn.close()
    print("\nDatabase migration complete!")


if __name__ == "__main__":
    migrate()
