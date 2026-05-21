import psycopg2

DATABASE_URL = "postgresql://postgres:Nsrg%4033patel@db.rxseblfkhgyzuimejnmu.supabase.co:5432/postgres"

def create_batches_table():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        print("Creating new Batches table...")
        
        # We use IF NOT EXISTS so it doesn't crash if you run it twice
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                id SERIAL PRIMARY KEY,
                department_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                student_count INTEGER NOT NULL,
                mentor_name VARCHAR(255)
            );
        """)
        
        conn.commit()
        print(" Success! Your database is now ready for Student Batches.")
        
    except Exception as e:
        print("--- ERROR CREATING TABLE ---")
        print(e)
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    create_batches_table()