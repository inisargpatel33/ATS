import psycopg2

# PASTE YOUR NEON CONNECTION STRING HERE
DATABASE_URL = "postgresql://neondb_owner:npg_lbou6CwMK1sD@ep-raspy-star-aq0939md.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require"

def seed_database():
    print("Connecting to database to inject test data...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # 1. Clear existing data to ensure a clean slate for testing
        print("Clearing old data...")
        cursor.execute("TRUNCATE TABLE timetables, faculty_expertise, faculties, subjects, batches, rooms RESTART IDENTITY CASCADE;")

        # 2. Insert Rooms
        print("Inserting Rooms...")
        cursor.execute("INSERT INTO rooms (name, room_type) VALUES ('Room_301', 'regular'), ('Room_302', 'regular');")

        # 3. Insert Batches
        print("Inserting Batches...")
        cursor.execute("INSERT INTO batches (name) VALUES ('MCA_Sem2'), ('BCA_Sem4'), ('MCA_Sem4');")

        # 4. Insert Subjects
        print("Inserting Subjects...")
        cursor.execute("""
            INSERT INTO subjects (name, required_hours, room_type) VALUES 
            ('Java', 2, 'regular'), 
            ('Python', 2, 'regular'), 
            ('Web_Sec', 2, 'regular');
        """)

        # 5. Insert Faculty (Expanded Max Hours for solver to work)
        print("Inserting Faculty...")
        cursor.execute("""
            INSERT INTO faculties (name, max_weekly_hours) VALUES 
            ('Prof_Sharma', 8), 
            ('Prof_Verma', 8), 
            ('Prof_Mehta', 8);
        """)

        # 6. Insert Expertise Matrix
        # Note: In a fresh DB, IDs will be 1, 2, 3 based on insertion order.
        print("Mapping Faculty Expertise...")
        cursor.execute("""
            INSERT INTO faculty_expertise (faculty_id, subject_id, competency_tier) VALUES 
            (1, 1, 1.0), -- Sharma: Java (Primary)
            (1, 2, 0.5), -- Sharma: Python (Backup)
            (2, 2, 1.0), -- Verma: Python (Primary)
            (2, 3, 0.5), -- Verma: Web_Sec (Backup)
            (3, 3, 1.0), -- Mehta: Web_Sec (Primary)
            (3, 1, 0.5); -- Mehta: Java (Backup)
        """)

        conn.commit()
        print("Success! Database fully seeded with test data.")

    except Exception as e:
        print(f"An error occurred: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    seed_database()