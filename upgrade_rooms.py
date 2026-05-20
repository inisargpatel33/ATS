import psycopg2

DATABASE_URL = "postgresql://postgres:Nsrg%4033patel@db.rxseblfkhgyzuimejnmu.supabase.co:5432/postgres"

def upgrade_rooms_table():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        print("Dropping old rooms table...")
        cursor.execute("DROP TABLE IF EXISTS rooms CASCADE;")
        
        print("Creating new Enterprise Rooms table...")
        cursor.execute("""
            CREATE TABLE rooms (
                id SERIAL PRIMARY KEY,
                department_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                capacity INTEGER NOT NULL,
                room_type VARCHAR(100) NOT NULL,
                has_projector BOOLEAN DEFAULT FALSE,
                has_ac BOOLEAN DEFAULT FALSE,
                has_whiteboard BOOLEAN DEFAULT FALSE,
                has_computers BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE
            );
        """)
        conn.commit()
        print(" Success! Your database is now ready for the new UI.")
    except Exception as e:
        print("Error:", e)
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    upgrade_rooms_table()