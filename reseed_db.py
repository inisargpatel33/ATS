import psycopg2

DATABASE_URL = "postgresql://neondb_owner:npg_lbou6CwMK1sD@ep-raspy-star-aq0939md.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require"

def build_enterprise_schema():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # 1. Wipe the old database clean
    print("Clearing old tables...")
    cursor.execute("DROP TABLE IF EXISTS timetables, faculty_expertise, faculties, subjects, batches, rooms, departments CASCADE;")

    # 2. Create the new Enterprise Tables
    schema = """
    -- The Master Bucket: Departments
    CREATE TABLE departments (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) UNIQUE NOT NULL
    );

    -- Rooms (Now linked to a department, with a flag for shared resources like Auditoriums)
    CREATE TABLE rooms (
        id SERIAL PRIMARY KEY,
        department_id INT REFERENCES departments(id),
        name VARCHAR(50) NOT NULL,
        room_type VARCHAR(50) NOT NULL, -- 'Lecture' or 'Lab'
        is_shared BOOLEAN DEFAULT FALSE 
    );

    -- Batches (Linked to a department)
    CREATE TABLE batches (
        id SERIAL PRIMARY KEY,
        department_id INT REFERENCES departments(id),
        name VARCHAR(50) NOT NULL
    );

    -- Subjects (Now supports L-T-P structure)
    CREATE TABLE subjects (
        id SERIAL PRIMARY KEY,
        department_id INT REFERENCES departments(id),
        name VARCHAR(100) NOT NULL,
        subject_type VARCHAR(20) NOT NULL, -- 'Theory' or 'Practical'
        required_sessions INT NOT NULL 
    );

    -- Faculty (Linked to a department, tracking UGC max hours)
    CREATE TABLE faculties (
        id SERIAL PRIMARY KEY,
        department_id INT REFERENCES departments(id),
        name VARCHAR(100) NOT NULL,
        max_weekly_hours INT NOT NULL 
    );

    -- The Expertise Matrix (unchanged)
    CREATE TABLE faculty_expertise (
        faculty_id INT REFERENCES faculties(id) ON DELETE CASCADE,
        subject_id INT REFERENCES subjects(id) ON DELETE CASCADE,
        competency_tier DECIMAL(2,1) NOT NULL,
        PRIMARY KEY (faculty_id, subject_id)
    );

    -- Timetables (Now stores which department this schedule belongs to)
    CREATE TABLE timetables (
        id SERIAL PRIMARY KEY,
        department_id INT REFERENCES departments(id),
        day_of_week VARCHAR(10) NOT NULL,
        timeslot VARCHAR(20) NOT NULL,
        room_id INT REFERENCES rooms(id),
        batch_id INT REFERENCES batches(id),
        subject_id INT REFERENCES subjects(id),
        faculty_id INT REFERENCES faculties(id)
    );
    """
    cursor.execute(schema)

    # 3. Inject Test Data specifically for "Computer Science Dept"
    print("Injecting Computer Science Department Data...")
    
    # Create the department and get its ID
    cursor.execute("INSERT INTO departments (name) VALUES ('Computer Science Dept.') RETURNING id;")
    cs_dept_id = cursor.fetchone()[0]

    # Insert data tagged with the cs_dept_id
    cursor.execute(f"INSERT INTO rooms (department_id, name, room_type) VALUES ({cs_dept_id}, 'Rm 101', 'Lecture'), ({cs_dept_id}, 'Mac Lab', 'Lab');")
    cursor.execute(f"INSERT INTO batches (department_id, name) VALUES ({cs_dept_id}, 'MCA Sem 2');")
    cursor.execute(f"INSERT INTO subjects (department_id, name, subject_type, required_sessions) VALUES ({cs_dept_id}, 'Java', 'Theory', 3);")
    cursor.execute(f"INSERT INTO faculties (department_id, name, max_weekly_hours) VALUES ({cs_dept_id}, 'Dr. Thorne', 16);")
    
    # Map the expertise
    cursor.execute("INSERT INTO faculty_expertise (faculty_id, subject_id, competency_tier) VALUES (1, 1, 1.0);")

    conn.commit()
    cursor.close()
    conn.close()
    print("Enterprise Schema successfully deployed to the cloud!")

if __name__ == "__main__":
    build_enterprise_schema()