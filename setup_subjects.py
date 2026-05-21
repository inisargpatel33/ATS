import psycopg2

DATABASE_URL = "postgresql://postgres:Nsrg%4033patel@db.rxseblfkhgyzuimejnmu.supabase.co:5432/postgres"

def create_subjects_table():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    try:
        print("Creating new Subjects table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id SERIAL PRIMARY KEY,
                department_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                subject_type VARCHAR(50) NOT NULL,
                required_sessions INTEGER NOT NULL
            );
        """)
        conn.commit()
        print("✅ Success! Your database is now ready for Subjects.")
    except Exception as e:
        print("--- ERROR CREATING TABLE ---")
        print(e)
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    create_subjects_table()