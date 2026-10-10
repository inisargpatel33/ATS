-- schema.sql

-- 1. Departments (No dependencies)
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    years INTEGER NOT NULL DEFAULT 3 CHECK (years BETWEEN 1 AND 5)
);

ALTER TABLE departments ADD COLUMN IF NOT EXISTS years INTEGER NOT NULL DEFAULT 3;
ALTER TABLE departments DROP CONSTRAINT IF EXISTS departments_years_check;
ALTER TABLE departments ADD CONSTRAINT departments_years_check CHECK (years BETWEEN 1 AND 5);

-- 2. Subjects (Depends on departments)
CREATE TABLE IF NOT EXISTS subjects (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    subject_type VARCHAR(50) NOT NULL CHECK (subject_type IN ('Theory', 'Practical', 'Seminar')),
    required_sessions INTEGER NOT NULL CHECK (required_sessions > 0 AND required_sessions <= 10),
    semester INTEGER NOT NULL DEFAULT 1 CHECK (semester BETWEEN 1 AND 10)
);

ALTER TABLE subjects ADD COLUMN IF NOT EXISTS semester INTEGER NOT NULL DEFAULT 1;
ALTER TABLE subjects DROP CONSTRAINT IF EXISTS subjects_semester_check;
ALTER TABLE subjects ADD CONSTRAINT subjects_semester_check CHECK (semester BETWEEN 1 AND 10);

-- 3. Faculties (Depends on departments)
CREATE TABLE IF NOT EXISTS faculties (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    max_weekly_hours INTEGER NOT NULL DEFAULT 15 CHECK (max_weekly_hours > 0 AND max_weekly_hours <= 40)
);

-- Academic terms must exist before batches reference them.
CREATE TABLE IF NOT EXISTS semesters (
    id SERIAL PRIMARY KEY,
    department_id INTEGER REFERENCES departments(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    term_number INTEGER NOT NULL
);

-- 4. Batches (Depends on departments & faculties)
CREATE TABLE IF NOT EXISTS batches (
    -- id SERIAL PRIMARY KEY,
    -- department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    -- name VARCHAR(255) NOT NULL,
    -- student_count INTEGER NOT NULL CHECK (student_count > 0),
    -- mentor_id INTEGER REFERENCES faculties(id) ON DELETE SET NULL,
    -- UNIQUE (department_id, name)

    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    semester_id INTEGER REFERENCES semesters(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    student_count INTEGER NOT NULL CHECK (student_count > 0),

    shift VARCHAR(20) NOT NULL DEFAULT 'Morning'
    CHECK (shift IN ('Morning', 'Afternoon')),

    mentor_id INTEGER REFERENCES faculties(id) ON DELETE SET NULL,

    UNIQUE(department_id, semester_id, name)
);

-- Compatibility column for databases created by the earlier batch API.
ALTER TABLE batches ADD COLUMN IF NOT EXISTS semester INTEGER;
UPDATE batches
SET semester = COALESCE(semester, semester_id)
WHERE semester IS NULL;

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


ALTER TABLE batches 
ADD COLUMN shift VARCHAR(20) NOT NULL DEFAULT 'Morning' 
CHECK (shift IN ('Morning', 'Afternoon'));


-- Junction table to link batches and subjects for each semester
CREATE TABLE semester_subjects (
    semester_id INTEGER REFERENCES semesters(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    PRIMARY KEY (semester_id, subject_id)
);

-- Telegram subscriptions are deliberately scoped to one batch or faculty.
-- A chat_id is unique so a Telegram chat can only receive one target's alerts.
CREATE TABLE IF NOT EXISTS telegram_subscriptions (
    chat_id BIGINT PRIMARY KEY,
    role VARCHAR(20) NOT NULL CHECK (role IN ('Student', 'Faculty')),
    target_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_subscriptions_target
    ON telegram_subscriptions (role, target_id);

CREATE TABLE IF NOT EXISTS telegram_handshakes (
    chat_id BIGINT PRIMARY KEY,
    requested_role VARCHAR(20),
    state_data TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE telegram_handshakes
    ADD COLUMN IF NOT EXISTS requested_role VARCHAR(20);
ALTER TABLE telegram_handshakes
    ADD COLUMN IF NOT EXISTS state_data TEXT;

-- Identity records used by the Telegram integration.
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    prn VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE faculties ADD COLUMN IF NOT EXISTS security_pin VARCHAR(4);
ALTER TABLE telegram_subscriptions ADD COLUMN IF NOT EXISTS student_id INTEGER
    REFERENCES students(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS telegram_bounties (
    id SERIAL PRIMARY KEY,
    timetable_id INTEGER NOT NULL REFERENCES timetables(id) ON DELETE CASCADE,
    specific_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'vip'
        CHECK (status IN ('vip', 'open', 'claimed', 'expired')),
    claim_faculty_id INTEGER REFERENCES faculties(id) ON DELETE SET NULL,
    voluntary_overtime BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (timetable_id, specific_date)
);

CREATE INDEX IF NOT EXISTS idx_telegram_bounties_status
    ON telegram_bounties (status, specific_date);
