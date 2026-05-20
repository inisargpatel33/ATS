import psycopg2

# 1. PASTE YOUR NEON CONNECTION STRING HERE
DATABASE_URL = "postgresql://neondb_owner:npg_lbou6CwMK1sD@ep-raspy-star-aq0939md.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require"

# 2. The SQL Blueprint
SQL_SCHEMA = """
-- Create the Rooms Table
CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    room_type VARCHAR(50) NOT NULL
);

-- Create the Batches (Students) Table
CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL
);

-- Create the Subjects Table
CREATE TABLE IF NOT EXISTS subjects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    required_hours INT NOT NULL,
    room_type VARCHAR(50) NOT NULL
);

-- Create the Faculty Table
CREATE TABLE IF NOT EXISTS faculties (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    max_weekly_hours INT NOT NULL
);

-- Create the Expertise Matrix (Many-to-Many Relationship)
CREATE TABLE IF NOT EXISTS faculty_expertise (
    faculty_id INT REFERENCES faculties(id) ON DELETE CASCADE,
    subject_id INT REFERENCES subjects(id) ON DELETE CASCADE,
    competency_tier DECIMAL(2,1) NOT NULL, 
    PRIMARY KEY (faculty_id, subject_id)
);

-- Create the Generated Timetable Output Table
CREATE TABLE IF NOT EXISTS timetables (
    id SERIAL PRIMARY KEY,
    day_of_week VARCHAR(10) NOT NULL,
    timeslot VARCHAR(20) NOT NULL,
    room_id INT REFERENCES rooms(id),
    batch_id INT REFERENCES batches(id),
    subject_id INT REFERENCES subjects(id),
    faculty_id INT REFERENCES faculties(id)
);
"""

def setup_database():
    print("Connecting to the Cloud Database...")
    try:
        # Connect to your Neon database
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        print("Executing SQL Schema...")
        # Run the SQL commands
        cursor.execute(SQL_SCHEMA)
        
        # Commit the changes to the database
        conn.commit()
        print("Success! All tables have been created securely in the cloud.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Always close the connection
        if conn:
            cursor.close()
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    setup_database()