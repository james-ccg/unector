"""
Database migration script - adds telegram_group_title column to drivers table
"""
import sqlite3

def migrate():
    conn = sqlite3.connect('freight_pilot.db')
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute('PRAGMA table_info(drivers)')
    columns = [row[1] for row in cursor.fetchall()]
    
    print(f"📊 Current columns in drivers table: {len(columns)}")
    for col in columns:
        print(f"  - {col}")
    
    if 'telegram_group_title' in columns:
        print("\n✅ telegram_group_title column already exists!")
    else:
        print("\n➕ Adding telegram_group_title column...")
        cursor.execute('ALTER TABLE drivers ADD COLUMN telegram_group_title VARCHAR(200)')
        conn.commit()
        print("✅ telegram_group_title column added successfully!")
    
    conn.close()
    print("\n🎉 Database migration complete!")

if __name__ == "__main__":
    migrate()
