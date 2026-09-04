"""
Database migration script - adds email column to companies table
"""
import sqlite3

def migrate():
    conn = sqlite3.connect('unector.db')
    cursor = conn.cursor()

    cursor.execute('PRAGMA table_info(companies)')
    columns = [row[1] for row in cursor.fetchall()]

    print(f"Current columns in companies table: {len(columns)}")
    for col in columns:
        print(f"  - {col}")

    if 'email' in columns:
        print("\nemail column already exists!")
    else:
        print("\nAdding email column...")
        cursor.execute('ALTER TABLE companies ADD COLUMN email VARCHAR(200)')
        conn.commit()
        print("email column added successfully!")

    conn.close()
    print("\nDatabase migration complete!")

if __name__ == "__main__":
    migrate()
