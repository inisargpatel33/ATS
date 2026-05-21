-- schema.sql

-- 1. Departments (No dependencies)
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE
);

-- 2. Subjects (Depends on departments)
CREATE TABLE IF NOT EXISTS subjects (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    subject_type VARCHAR(50) NOT NULL CHECK (subject_type IN ('Theory', 'Practical', 'Seminar')),
    required_sessions INTEGER NOT NULL CHECK (required_sessions > 0 AND required_sessions <= 10)
);

-- 3. Faculties (Depends on departments)
CREATE TABLE IF NOT EXISTS faculties (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    max_weekly_hours INTEGER NOT NULL DEFAULT 15 CHECK (max_weekly_hours > 0 AND max_weekly_hours <= 40)
);

-- 4. Batches (Depends on departments & faculties)
CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    student_count INTEGER NOT NULL CHECK (student_count > 0),
    mentor_id INTEGER REFERENCES faculties(id) ON DELETE SET NULL,
    UNIQUE (department_id, name)
);

-- 5. Rooms (Depends on departments)
CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL UNIQUE,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    room_type VARCHAR(100) NOT NULL CHECK (room_type IN ('Lecture Hall', 'Laboratory', 'Seminar Room', 'Auditorium')),
    has_projector BOOLEAN NOT NULL DEFAULT FALSE,
    has_ac BOOLEAN NOT NULL DEFAULT FALSE,
    has_whiteboard BOOLEAN NOT NULL DEFAULT FALSE,
    has_computers BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 6. Faculty Expertise (Junction Table)
CREATE TABLE IF NOT EXISTS faculty_expertise (
    faculty_id INTEGER REFERENCES faculties(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    competency_tier DECIMAL(2,1) NOT NULL DEFAULT 1.0 CHECK (competency_tier IN (1.0, 0.5)),
    PRIMARY KEY (faculty_id, subject_id)
);

-- 7. Timetables (Output Table with Safety Nets)
CREATE TABLE IF NOT EXISTS timetables (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    day_of_week VARCHAR(10) NOT NULL CHECK (day_of_week IN ('Mon', 'Tue', 'Wed', 'Thu', 'Fri')),
    timeslot VARCHAR(20) NOT NULL,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    faculty_id INTEGER NOT NULL REFERENCES faculties(id) ON DELETE CASCADE,
    UNIQUE (day_of_week, timeslot, room_id),
    UNIQUE (day_of_week, timeslot, faculty_id),
    UNIQUE (day_of_week, timeslot, batch_id)
);