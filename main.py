from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors
from ortools.sat.python import cp_model
from psycopg2 import pool # NEW: Import the pool module
# from contextlib import contextmanager # NEW: For safe connection handling

# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(title="Timetable SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#  =========================================================
# DATABASE CONNECTION POOL
# =========================================================
DATABASE_URL = "postgresql://postgres:Nsrg%4033patel@db.rxseblfkhgyzuimejnmu.supabase.co:5432/postgres"

# Initialize a Threaded Connection Pool (Min 1, Max 20 connections)
# This keeps connections "warm" and ready for instant use across FastAPI threads.
try:
    db_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=20,
        dsn=DATABASE_URL,
        cursor_factory=RealDictCursor
    )
    print("✅ Database Connection Pool initialized successfully!")
except Exception as e:
    print("❌ Failed to initialize connection pool:", e)
    db_pool = None
    
def get_db_connection():
    if db_pool is None:
        raise HTTPException("Database connection pool is not available")
    return db_pool.getconn()

def release_db_connection(conn):
    if db_pool and conn:
        db_pool.putconn(conn)
        

# =========================================================
# CONSTANTS
# =========================================================

# CHANGE:
# Centralized shift slot configuration.
SHIFT_SLOTS = {
    "Morning": [
        "08:00 AM - 09:00 AM",
        "09:00 AM - 10:00 AM",
        "10:00 AM - 11:00 AM",
        "12:00 PM - 01:00 PM",
        "01:00 PM - 02:00 PM"
    ],
    "Afternoon": [
        "12:00 PM - 01:00 PM",
        "01:00 PM - 02:00 PM",
        "02:00 PM - 03:00 PM",
        "04:00 PM - 05:00 PM",
        "05:00 PM - 06:00 PM"
    ]
}

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


# =========================================================
# MODELS
# =========================================================

class DeptCreate(BaseModel):
    name: str


class FacultyCreate(BaseModel):
    department_id: int
    name: str
    max_weekly_hours: int = 15

class RoomCreate(BaseModel):
    name: str
    capacity: int
    room_type: str
    amenities: List[str]
    extra_features: Optional[str] = ""  # <-- Added this
    is_active: bool = True
    # department_id: int <-- REMOVED THIS


class BatchCreate(BaseModel):
    name: str
    student_count: int
    mentor_id: Optional[int] = None
    department_id: int
    shift: str = "Morning"

    # CHANGE:
    # Added shift validation.
    @field_validator("shift")
    @classmethod
    def validate_shift(cls, v):
        if v not in ["Morning", "Afternoon"]:
            raise ValueError("Shift must be Morning or Afternoon")
        return v


class SubjectCreate(BaseModel):
    name: str
    subject_type: str
    required_sessions: int
    department_id: int


class ExpertiseCreate(BaseModel):
    faculty_id: int
    subject_id: int
    competency_tier: float


# class GenerateRequest(BaseModel):
#     constraints: List[str] = []
#     batch_id: str = "all"

class GenerateRequest(BaseModel):
    constraints: List[str] = []
    batch_id: str = "all"
    start_hour: int = 8
    end_hour: int = 16
    break_hour: int = 12



class TimetableRecord(BaseModel):
    department_id: int
    day_of_week: str
    timeslot: str
    room_id: int
    batch_id: int
    subject_id: int
    faculty_id: int
    # faculty: Optional[str] = None
    # subject: Optional[str] = None
    # room: Optional[str] = None
    # batch: Optional[str] = None

class SaveTimetableRequest(BaseModel):
    records: List[TimetableRecord]
    notes: str = ""

# =========================================================
# DEPARTMENT API
# =========================================================

@app.post("/add-department/")
def add_department(dept: DeptCreate):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO departments (name) VALUES (%s)",
            (dept.name,)
        )

        conn.commit()

        return {
            "success": True,
            "message": "Department added successfully"
        }

    except errors.UniqueViolation:
        conn.rollback()

        raise HTTPException(
            status_code=400,
            detail="Department already exists"
        )

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


@app.get("/get-departments/")
def get_departments():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT *
            FROM departments
            ORDER BY id ASC
        """)

        return {
            "data": cursor.fetchall()
        }

    finally:
        cursor.close()
        release_db_connection(conn)


@app.delete("/delete-department/{dept_id}")
def delete_department(dept_id: int):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            DELETE FROM departments
            WHERE id = %s
            RETURNING id
        """, (dept_id,))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Department not found"
            )

        conn.commit()

        return {
            "success": True,
            "message": "Department deleted"
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


# =========================================================
# FACULTY API
# =========================================================

@app.post("/add-faculty/")
def add_faculty(faculty: FacultyCreate):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO faculties (
                department_id,
                name,
                max_weekly_hours
            )
            VALUES (%s, %s, %s)
        """, (
            faculty.department_id,
            faculty.name,
            faculty.max_weekly_hours
        ))

        conn.commit()

        return {
            "success": True,
            "message": "Faculty added successfully"
        }

    except errors.CheckViolation:
        conn.rollback()

        raise HTTPException(
            status_code=400,
            detail="Weekly hours must be between 1 and 40"
        )

    except errors.UniqueViolation:
        conn.rollback()

        raise HTTPException(
            status_code=400,
            detail="Faculty already exists"
        )

    except errors.ForeignKeyViolation:
        conn.rollback()

        raise HTTPException(
            status_code=400,
            detail="Invalid department"
        )

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


@app.get("/get-faculties/")
def get_faculties():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                f.id,
                f.name,
                f.max_weekly_hours,
                f.department_id,
                d.name AS department_name
            FROM faculties f
            JOIN departments d
            ON f.department_id = d.id
            ORDER BY f.id ASC
        """)

        faculties = cursor.fetchall()

        cursor.execute("""
            SELECT
                fe.faculty_id,
                s.name AS subject_name,
                fe.competency_tier
            FROM faculty_expertise fe
            JOIN subjects s
            ON fe.subject_id = s.id
        """)

        expertise = cursor.fetchall()

        exp_map = {}

        for exp in expertise:

            fid = exp["faculty_id"]

            if fid not in exp_map:
                exp_map[fid] = {
                    "primary": [],
                    "secondary": []
                }

            if float(exp["competency_tier"]) == 1.0:
                exp_map[fid]["primary"].append(exp["subject_name"])
            else:
                exp_map[fid]["secondary"].append(exp["subject_name"])

        for faculty in faculties:

            fid = faculty["id"]

            faculty["primary_subjects"] = exp_map.get(
                fid,
                {}
            ).get("primary", [])

            faculty["secondary_subjects"] = exp_map.get(
                fid,
                {}
            ).get("secondary", [])

        return {
            "data": faculties
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


@app.delete("/delete-faculty/{faculty_id}")
def delete_faculty(faculty_id: int):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            DELETE FROM faculties
            WHERE id = %s
            RETURNING id
        """, (faculty_id,))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Faculty not found"
            )

        conn.commit()

        return {
            "success": True,
            "message": "Faculty deleted"
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


# =========================================================
# ROOM API
# =========================================================

@app.post("/add-room/")
def add_room(room: RoomCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        has_projector = "Projector" in room.amenities
        has_ac = "AC" in room.amenities
        has_whiteboard = "Whiteboard" in room.amenities
        has_computers = "Computers" in room.amenities

        cursor.execute("""
            INSERT INTO rooms (
                name, capacity, room_type, has_projector, has_ac, 
                has_whiteboard, has_computers, extra_features, is_active
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            room.name, room.capacity, room.room_type, has_projector, has_ac,
            has_whiteboard, has_computers, room.extra_features, room.is_active
        ))
        conn.commit()
        return {"success": True, "message": "Room added successfully"}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


#
@app.get("/get-rooms/")
def get_rooms():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch ALL rooms, no WHERE clause needed anymore
        cursor.execute("SELECT * FROM rooms ORDER BY name ASC")
        return {"data": cursor.fetchall()}
    finally:
        cursor.close()
        release_db_connection(conn)


# =========================================================
# BATCH API
# =========================================================

@app.post("/add-batch/")
def add_batch(batch: BatchCreate):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # CHANGE:
        # Added shift insertion.
        cursor.execute("""
            INSERT INTO batches (
                name,
                student_count,
                mentor_id,
                department_id,
                shift
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            batch.name,
            batch.student_count,
            batch.mentor_id,
            batch.department_id,
            batch.shift
        ))

        conn.commit()

        return {
            "success": True,
            "message": "Batch added successfully"
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


# CHANGE:
# Removed duplicate /get-batches route.
@app.get("/get-batches/{department_id}")
def get_batches(department_id: int):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                b.id,
                b.name,
                b.student_count,
                b.shift,
                b.department_id,
                b.mentor_id,
                f.name AS mentor_name
            FROM batches b
            LEFT JOIN faculties f
            ON b.mentor_id = f.id
            WHERE b.department_id = %s
            ORDER BY b.name ASC
        """, (department_id,))

        return {
            "data": cursor.fetchall()
        }

    finally:
        cursor.close()
        release_db_connection(conn)


# =========================================================
# SUBJECT API
# =========================================================

@app.post("/add-subject/")
def add_subject(subject: SubjectCreate):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO subjects (
                name,
                subject_type,
                required_sessions,
                department_id
            )
            VALUES (%s,%s,%s,%s)
        """, (
            subject.name,
            subject.subject_type,
            subject.required_sessions,
            subject.department_id
        ))

        conn.commit()

        return {
            "success": True,
            "message": "Subject added successfully"
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)


@app.get("/get-subjects/{department_id}")
def get_subjects(department_id: int):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                s.id,
                s.name,
                s.subject_type,
                s.required_sessions,
                d.name AS department_name
            FROM subjects s
            JOIN departments d
            ON s.department_id = d.id
            WHERE s.department_id = %s
            ORDER BY s.name ASC
        """, (department_id,))

        return {
            "data": cursor.fetchall()
        }

    finally:
        cursor.close()
        release_db_connection(conn)


# =========================================================
# EXPERTISE API
# =========================================================

@app.post("/add-expertise/")
def add_expertise(exp: ExpertiseCreate):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO faculty_expertise (
                faculty_id,
                subject_id,
                competency_tier
            )
            VALUES (%s,%s,%s)
            ON CONFLICT (faculty_id, subject_id)
            DO UPDATE SET
            competency_tier = EXCLUDED.competency_tier
        """, (
            exp.faculty_id,
            exp.subject_id,
            exp.competency_tier
        ))

        conn.commit()

        return {
            "success": True,
            "message": "Expertise added successfully"
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)

@app.get("/get-expertise/{faculty_id}")
def get_expertise(faculty_id: int):
    """Fetches a specific faculty member's mapped subjects and competency tiers."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # We use 'AS id' to match what your frontend JavaScript is expecting
        cursor.execute("""
            SELECT 
                subject_id AS id, 
                competency_tier
            FROM faculty_expertise
            WHERE faculty_id = %s
        """, (faculty_id,))
        
        return {
            "data": cursor.fetchall()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)

# =========================================================
# TIMETABLE GENERATION (MASTER ENGINE)
# =========================================================

@app.post("/generate-timetable/{department_id}")
def generate_timetable(department_id: int, payload: GenerateRequest):
    conn = get_db_connection()
    cursor = conn.cursor()  
    try:
        # =====================================================
        # 1. FETCH DATA
        # =====================================================
        cursor.execute("SELECT * FROM faculties WHERE department_id = %s", (department_id,))
        faculties = cursor.fetchall()

        cursor.execute("SELECT * FROM subjects WHERE department_id = %s", (department_id,))
        subjects = cursor.fetchall()

        cursor.execute("SELECT * FROM rooms WHERE is_active = TRUE")
        rooms = cursor.fetchall()

        if payload.batch_id != "all":
            cursor.execute("SELECT * FROM batches WHERE department_id = %s AND id = %s", (department_id, int(payload.batch_id)))
            batches = cursor.fetchall()
            
            # NEW: Fetch existing bookings for OTHER batches to prevent double-booking!
            cursor.execute("""
                SELECT faculty_id, room_id, day_of_week, timeslot
                FROM timetables
                WHERE batch_id != %s
            """, (int(payload.batch_id),))
            existing_bookings = cursor.fetchall()
        else:
            cursor.execute("SELECT * FROM batches WHERE department_id = %s", (department_id,))
            batches = cursor.fetchall()
            existing_bookings = []

        cursor.execute("""
                        SELECT fe.faculty_id, fe.subject_id, fe.competency_tier
                        FROM faculty_expertise fe
                        JOIN faculties f ON fe.faculty_id = f.id
                        WHERE f.department_id = %s
                    """, (department_id,))
        expertise = cursor.fetchall()

        if not faculties or not subjects or not rooms or not batches:
         return {"success": False, "message": "Missing required data"}

                    # =====================================================
                    # 2. EXPERTISE & ROOM MAPS
                    # =====================================================
        exp_map = {(exp["faculty_id"], exp["subject_id"]): float(exp["competency_tier"]) for exp in expertise}

        eligible_rooms = {}
        for subject in subjects:
            valid_rooms = []
            for room in rooms:
                if subject["subject_type"] == "Practical" and room["room_type"] == "Laboratory":
                    valid_rooms.append(room)
                elif subject["subject_type"] != "Practical" and room["room_type"] != "Laboratory":
                    valid_rooms.append(room)
            eligible_rooms[subject["id"]] = valid_rooms

                    # =====================================================
                    # 3. DYNAMIC SLOTS CONFIGURATION
                    # =====================================================
        # dynamic_slots = []
        # for h in range(payload.start_hour, payload.end_hour):
        #     if h == payload.break_hour:
        #         continue # Skip the break period
            
        #     am_pm1 = "AM" if h < 12 or h == 24 else "PM"
        #     disp1 = h if h <= 12 else h - 12
        #     if disp1 == 0: disp1 = 12
            
        #     h2 = h + 1
        #     am_pm2 = "AM" if h2 < 12 or h2 == 24 else "PM"
        #     disp2 = h2 if h2 <= 12 else h2 - 12
        #     if disp2 == 0: disp2 = 12
            
        #     dynamic_slots.append(f"{disp1:02d}:00 {am_pm1} - {disp2:02d}:00 {am_pm2}")
        
        # For simplicity, we'll use the centralized SHIFT_SLOTS configuration.
        dynamic_slots = []
        slot_hours = [] # <-- NEW: Track raw hours to detect the lunch break
        for h in range(payload.start_hour, payload.end_hour):
            if h == payload.break_hour:
                continue # Skip the break period
            
            am_pm1 = "AM" if h < 12 or h == 24 else "PM"
            disp1 = h if h <= 12 else h - 12
            if disp1 == 0: disp1 = 12
            
            h2 = h + 1
            am_pm2 = "AM" if h2 < 12 or h2 == 24 else "PM"
            disp2 = h2 if h2 <= 12 else h2 - 12
            if disp2 == 0: disp2 = 12
            
            dynamic_slots.append(f"{disp1:02d}:00 {am_pm1} - {disp2:02d}:00 {am_pm2}")
            slot_hours.append(h)

        

                # =====================================================
                # 4. THE 3-OPTION GENERATOR LOOP
                # =====================================================
        scenarios = [
            {"name": "Option 1: Balanced", "w_exp": 10, "w_room": 20, "w_morn": 3},
            {"name": "Option 2: Minimum Movement", "w_exp": 5, "w_room": 100, "w_morn": 1},
            {"name": "Option 3: Faculty Expertise Focus", "w_exp": 50, "w_room": 5, "w_morn": 1}
        ]

        generated_options = []

        # Create lookup dictionaries for the UI
        sub_dict = {s['id']: s['name'] for s in subjects}
        room_dict = {r['id']: r['name'] for r in rooms}
        fac_dict = {f['id']: f['name'] for f in faculties}
        batch_dict = {b['id']: b['name'] for b in batches}

        for scenario in scenarios:
            model = cp_model.CpModel()
            x = {}

            # --- VARIABLES ---
            for faculty in faculties:
                for subject in subjects:
                    if (faculty["id"], subject["id"]) not in exp_map: continue
                    for room in eligible_rooms[subject["id"]]:
                        for batch in batches:
                            for day in DAYS:
                                for slot in dynamic_slots:
                                    key = (faculty["id"], subject["id"], room["id"], day, slot, batch["id"])
                                    x[key] = model.NewBoolVar(f"x_{key}")

            # --- HARD CONSTRAINTS (Conflicts) ---
            for faculty in faculties:
                for day in DAYS:
                    for slot in dynamic_slots:
                        vars_list = [x[k] for k in x if k[0] == faculty["id"] and k[3] == day and k[4] == slot]
                        if vars_list: model.AddAtMostOne(vars_list)

            for room in rooms:
                for day in DAYS:
                    for slot in dynamic_slots:
                        vars_list = [x[k] for k in x if k[2] == room["id"] and k[3] == day and k[4] == slot]
                        if vars_list: model.AddAtMostOne(vars_list)

            for batch in batches:
                for day in DAYS:
                    for slot in dynamic_slots:
                        vars_list = [x[k] for k in x if k[5] == batch["id"] and k[3] == day and k[4] == slot]
                        if vars_list: model.AddAtMostOne(vars_list)

            # --- HARD CONSTRAINTS (Sessions & Spread) ---
            for batch in batches:
                for subject in subjects:
                    req = subject["required_sessions"]
                    sub_vars = [x[k] for k in x if k[1] == subject["id"] and k[5] == batch["id"]]
                    
                    if subject["subject_type"] == "Practical":
                        block_vars = []
                        for fac in faculties:
                            for room in eligible_rooms[subject["id"]]:
                                if (fac["id"], subject["id"]) not in exp_map: continue
                                for day in DAYS:
                                    for i in range(len(dynamic_slots) - req + 1):
                                        if slot_hours[i + req - 1] - slot_hours[i] != req - 1: continue 
                                        block_var = model.NewBoolVar(f"blk_{batch['id']}_{subject['id']}_{fac['id']}_{room['id']}_{day}_{i}")
                                        block_vars.append(block_var)
                                        for j in range(req):
                                            var_k = (fac["id"], subject["id"], room["id"], day, dynamic_slots[i+j], batch["id"])
                                            if var_k in x: model.AddImplication(block_var, x[var_k])
                        if block_vars: model.AddExactlyOne(block_vars)
                        if sub_vars: model.Add(sum(sub_vars) == req)
                    else:
                        if sub_vars: model.Add(sum(sub_vars) == req)
                        for day in DAYS:
                            day_vars = [x[k] for k in x if k[1] == subject["id"] and k[5] == batch["id"] and k[3] == day]
                            if day_vars: model.Add(sum(day_vars) <= 1)

            for faculty in faculties:
                vars_list = [x[k] for k in x if k[0] == faculty["id"]]
                if vars_list: model.Add(sum(vars_list) <= faculty["max_weekly_hours"])

            # Lock Existing Schedules
            for booking in existing_bookings:
                fac_vars = [x[k] for k in x if k[0] == booking["faculty_id"] and k[3] == booking["day_of_week"] and k[4] == booking["timeslot"]]
                if fac_vars: model.Add(sum(fac_vars) == 0)
                rm_vars = [x[k] for k in x if k[2] == booking["room_id"] and k[3] == booking["day_of_week"] and k[4] == booking["timeslot"]]
                if rm_vars: model.Add(sum(rm_vars) == 0)

            # --- DYNAMIC UI CONSTRAINTS ---
            if "no_consecutive" in payload.constraints:
                for batch in batches:
                    for day in DAYS:
                        for subject in subjects:
                            if subject["subject_type"] == "Practical": continue
                            for i in range(len(dynamic_slots) - 1):
                                vars_s1 = [x[k] for k in x if k[5] == batch["id"] and k[3] == day and k[4] == dynamic_slots[i] and k[1] == subject["id"]]
                                vars_s2 = [x[k] for k in x if k[5] == batch["id"] and k[3] == day and k[4] == dynamic_slots[i+1] and k[1] == subject["id"]]
                                if vars_s1 and vars_s2: model.Add(sum(vars_s1) + sum(vars_s2) <= 1)

            if "strict_faculty_load" in payload.constraints:
                for faculty in faculties:
                    for day in DAYS:
                        vars_day = [x[k] for k in x if k[0] == faculty["id"] and k[3] == day]
                        if vars_day: model.Add(sum(vars_day) <= 2)

            if "faculty_day_off" in payload.constraints:
                for faculty in faculties:
                    worked_days = []
                    for day in DAYS:
                        vars_day = [x[k] for k in x if k[0] == faculty["id"] and k[3] == day]
                        if vars_day:
                            worked_day_var = model.NewBoolVar(f"wk_{faculty['id']}_{day}")
                            model.AddMaxEquality(worked_day_var, vars_day)
                            worked_days.append(worked_day_var)
                    if worked_days: model.Add(sum(worked_days) <= len(DAYS) - 1)

            # --- OBJECTIVE SCORING (Uses dynamic weights from loop) ---
            objective_terms = []
            for key, var in x.items():
                score = int(exp_map[(key[0], key[1])] * scenario["w_exp"])
                if "morning_heavy" in payload.constraints:
                    if "AM" in key[4]: score += (3 * scenario["w_morn"])
                objective_terms.append(var * score)
                
            for batch in batches:
                for day in DAYS:
                    for i in range(len(dynamic_slots) - 1):
                        if slot_hours[i+1] - slot_hours[i] != 1: continue 
                        for room in rooms:
                            b_r_s1 = [x[k] for k in x if k[5] == batch["id"] and k[3] == day and k[4] == dynamic_slots[i] and k[2] == room["id"]]
                            b_r_s2 = [x[k] for k in x if k[5] == batch["id"] and k[3] == day and k[4] == dynamic_slots[i+1] and k[2] == room["id"]]
                            if b_r_s1 and b_r_s2:
                                b_in_r1 = model.NewBoolVar(f"r1_{batch['id']}_{room['id']}_{day}_{i}")
                                b_in_r2 = model.NewBoolVar(f"r2_{batch['id']}_{room['id']}_{day}_{i+1}")
                                same_rm = model.NewBoolVar(f"srm_{batch['id']}_{room['id']}_{day}_{i}")
                                model.Add(b_in_r1 == sum(b_r_s1))
                                model.Add(b_in_r2 == sum(b_r_s2))
                                model.AddBoolAnd([b_in_r1, b_in_r2]).OnlyEnforceIf(same_rm)
                                objective_terms.append(same_rm * scenario["w_room"])

            model.Maximize(sum(objective_terms))

            # --- SOLVE ---
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 7 # 7 seconds per option (21s total)
            status = solver.Solve(model)

            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                draft_records = []
                for key, var in x.items():
                    if solver.Value(var) == 1:
                        draft_records.append({
                            "department_id": department_id, "faculty_id": key[0], "subject_id": key[1],
                            "room_id": key[2], "day_of_week": key[3], "timeslot": key[4], "batch_id": key[5],
                            "faculty": fac_dict[key[0]], "subject": sub_dict[key[1]], "room": room_dict[key[2]], "batch": batch_dict[key[5]]
                        })
                generated_options.append({
                    "option_name": scenario["name"],
                    "records": draft_records
                })

        # If at least one option succeeded
        if generated_options:
            return {
                "success": True, 
                "message": f"Successfully generated {len(generated_options)} optimization options!",
                "draft_options": generated_options # Return all 3 options
            }
        else:
            return {"success": False, "message": "No feasible timetable found under these constraints"}       
         
        
    except Exception as e:
        print("--- SCHEDULER ENGINE CRASHED ---")
        print(e)
        raise HTTPException(status_code=500, detail=str(e))
    
    # 3. Add the finally block at the VERY END to release the connection
    finally:
        cursor.close()
        release_db_connection(conn)

# CHANGE:safe timetable saving with transaction and batch deletion/insertion    
    
@app.post("/save-timetable/")
def save_timetable(payload: SaveTimetableRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if not payload.records:
            return {"success": False, "message": "No records to save."}
            
        # Get the targeted batch and department from the first record
        batch_id = payload.records[0].batch_id
        dept_id = payload.records[0].department_id

        # 1. Safely delete the old timetable for this specific batch
        cursor.execute("DELETE FROM timetables WHERE batch_id = %s", (batch_id,))

        # 2. Insert the new ones with the user's note
        insert_data = [
            (r.department_id, r.day_of_week, r.timeslot, r.room_id, r.batch_id, r.subject_id, r.faculty_id, payload.notes)
            for r in payload.records
        ]
        
        cursor.executemany("""
            INSERT INTO timetables (department_id, day_of_week, timeslot, room_id, batch_id, subject_id, faculty_id, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, insert_data)

        conn.commit()
        return {"success": True, "message": "Timetable securely published to database."}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)   


# =========================================================
# VIEW TIMETABLE
# =========================================================

@app.get("/view-timetable/")
def view_timetable(
    department_id: Optional[int] = None,
    batch_id: Optional[int] = None
):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # Update the query string inside view_timetable:
        query = """
            SELECT
                t.day_of_week,
                t.timeslot,
                t.notes,  -- <-- ADD THIS LINE
                b.name AS batch,
                b.shift AS batch_shift,
                s.name AS subject,
                r.name AS room,
                f.name AS faculty
            FROM timetables t
            JOIN batches b ON t.batch_id = b.id
            JOIN subjects s ON t.subject_id = s.id
            JOIN rooms r ON t.room_id = r.id
            JOIN faculties f ON t.faculty_id = f.id
            WHERE 1=1
        """
        params = []

        if department_id:

            query += " AND t.department_id = %s"
            params.append(department_id)

        if batch_id:

            query += " AND t.batch_id = %s"
            params.append(batch_id)

        cursor.execute(query, tuple(params))

        return {
            "data": cursor.fetchall()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)    
        
        
@app.delete("/delete-timetable/{batch_id}")
def delete_timetable(batch_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM timetables WHERE batch_id = %s", (batch_id,))
        if cursor.rowcount == 0:
            return {"success": False, "message": "No timetable found to delete."}
            
        conn.commit()
        return {"success": True, "message": "Timetable securely deleted."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)