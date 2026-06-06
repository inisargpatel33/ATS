from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors
from ortools.sat.python import cp_model
from collections import defaultdict
import math
import random
# from celery import Celery
# from celery.result import AsyncResult
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
# DATABASE_URL = "postgresql://postgres:Nsrg%4033patel@db.rxseblfkhgyzuimejnmu.supabase.co:5432/postgres"
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
    
# def get_db_connection():
#     if db_pool is None:
#         raise HTTPException("Database connection pool is not available")
#     return db_pool.getconn()


def get_db_connection():
    if db_pool is None:
        raise HTTPException(status_code=500, detail="Database connection pool is not available")
    
    # Try up to 3 times to find or create a living connection
    for _ in range(3):
        conn = None
        try:
            conn = db_pool.getconn()
            
            # --- THE SELF-HEALING HEALTH CHECK ---
            # Execute a dummy query to verify Supabase hasn't closed the socket
            with conn.cursor() as test_cursor:
                test_cursor.execute("SELECT 1;")
                
            return conn # Connection is alive and healthy!
            
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            print("⚠️ Production Warning: Detected a dead connection socket from pool. Discarding...")
            if conn:
                try:
                    # Evict the dead socket completely from the pool so it isn't used again
                    db_pool.putconn(conn, close=True)
                except Exception:
                    pass
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database extraction failure: {str(e)}")
            
    raise HTTPException(status_code=500, detail="Could not obtain a stable database stream from the pool after retries.")

def release_db_connection(conn):
    if db_pool and conn:
        db_pool.putconn(conn)
        
        
# =========================================================
# CELERY BACKGROUND WORKER SETUP
# =========================================================
# Redis acts as the message broker and the result backend
# celery_app = Celery(
#     "timetable_worker",
#     broker="redis://localhost:6379/0",
#     backend="redis://localhost:6379/0"
# )

# celery_app.conf.update(
#     task_track_started=True,
#     result_expires=3600
# )
        

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


class SwapValidationRequest(BaseModel):
    batch_id: int
    faculty_id: int
    room_id: int
    new_day: str
    new_timeslot: str


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
    semester: int = 1  # <-- NEW

class SubjectCreate(BaseModel):
    name: str
    subject_type: str
    required_sessions: int
    department_id: int
    semester: int = 1  # <-- NEW
    # shift: str = "Morning"

    # CHANGE:
    # Added shift validation.
    # @field_validator("shift")
    # @classmethod
    # def validate_shift(cls, v):
    #     if v not in ["Morning", "Afternoon"]:
    #         raise ValueError("Shift must be Morning or Afternoon")
    #     return v


# class SubjectCreate(BaseModel):
#     name: str
#     subject_type: str
#     required_sessions: int
#     department_id: int



class AutoFixRequest(BaseModel):
    department_id: int
    faculty_id: int
    room_id: int
    target_day: str
    target_timeslot: str
    original_day: str
    original_timeslot: str

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

class UpdateSlotRequest(BaseModel):
    record_id: int
    new_day: str
    new_timeslot: str

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
        # Correctly insert into the 'departments' table using 'dept.name'
        cursor.execute("""
            INSERT INTO departments (name)
            VALUES (%s)
        """, (dept.name,))

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
            SELECT id, name
            FROM departments
            ORDER BY name ASC
        """)

        return {
            "data": cursor.fetchall()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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


# =========================================================
# SAFELY DELETE FACULTY
# =========================================================
@app.delete("/delete-faculty/{faculty_id}")
def delete_faculty(faculty_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM faculties WHERE id = %s RETURNING id", (faculty_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Faculty not found")
        conn.commit()
        return {"success": True, "message": "Faculty deleted successfully"}
        
    except errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete this Professor. They are currently assigned to teach classes in a published Timetable."
        )
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

    mentor_val = batch.mentor_id if batch.mentor_id and batch.mentor_id > 0 else None
    
    try:

        # CHANGE:
        # Added shift insertion.
        cursor.execute("""
                       insert into batches (name, student_count, mentor_id, department_id, semester)
                          values (%s, %s, %s, %s, %s)
        """, (batch.name, batch.student_count, batch.mentor_id, batch.department_id, batch.semester))

        conn.commit()

        return {
            "success": True,
            "message": "Batch added successfully"
        }
    except errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(
            status_code=400, 
            detail="A batch with this name already exists in this department."
        )

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
                b.department_id,
                b.mentor_id,
                b.semester,
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


@app.put("/edit-batch/{batch_id}")
def edit_batch(batch_id: int, batch: BatchCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    mentor_val = batch.mentor_id if batch.mentor_id and batch.mentor_id > 0 else None

    try:
        cursor.execute("""
            UPDATE batches SET name = %s, student_count = %s, mentor_id = %s, department_id = %s, semester = %s
            WHERE id = %s RETURNING id
        """, (batch.name, batch.student_count, batch.mentor_id, batch.department_id, batch.semester, batch_id))
        

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Batch not found in the database"
            )

        conn.commit()

        return {
            "success": True,
            "message": "Batch updated successfully"
        }
    
    except errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Another batch with this name already exists.")

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)
        
        
# =========================================================
# SAFELY DELETE BATCH
# =========================================================
@app.delete("/delete-batch/{batch_id}")
def delete_batch(batch_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM batches WHERE id = %s RETURNING id", (batch_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Batch not found")
        conn.commit()
        return {"success": True, "message": "Batch deleted successfully"}
        
    except errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete this Batch. It is currently being used in a published Timetable. Please delete its timetable first."
        )
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)
# =========================================================
# MISSING ROOM ROUTES (UPDATE & DELETE)
# =========================================================
@app.put("/edit-room/{room_id}")
def edit_room(room_id: int, room: RoomCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        has_projector = "Projector" in room.amenities
        has_ac = "AC" in room.amenities
        has_whiteboard = "Whiteboard" in room.amenities
        has_computers = "Computers" in room.amenities

        cursor.execute("""
            UPDATE rooms SET
                name = %s, capacity = %s, room_type = %s, has_projector = %s,
                has_ac = %s, has_whiteboard = %s, has_computers = %s, 
                extra_features = %s, is_active = %s
            WHERE id = %s RETURNING id
        """, (
            room.name, room.capacity, room.room_type, has_projector, has_ac,
            has_whiteboard, has_computers, room.extra_features, room.is_active,
            room_id
        ))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()
        return {"success": True, "message": "Room updated successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)

# =========================================================
# SAFELY DELETE ROOM
# =========================================================
@app.delete("/delete-room/{room_id}")
def delete_room(room_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM rooms WHERE id = %s RETURNING id", (room_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()
        return {"success": True, "message": "Room deleted successfully"}
        
    except errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete this Room. It is currently assigned to classes in a published Timetable."
        )
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)

# =========================================================
# MISSING FACULTY ROUTES (UPDATE)
# =========================================================
@app.put("/edit-faculty/{faculty_id}")
def edit_faculty(faculty_id: int, faculty: FacultyCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE faculties SET name = %s, max_weekly_hours = %s, department_id = %s
            WHERE id = %s RETURNING id
        """, (faculty.name, faculty.max_weekly_hours, faculty.department_id, faculty_id))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Faculty not found")
        conn.commit()
        return {"success": True, "message": "Faculty updated successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)

# =========================================================
# MISSING SUBJECT ROUTES (UPDATE & DELETE)
# =========================================================
@app.put("/edit-subject/{subject_id}")
def edit_subject(subject_id: int, subject: SubjectCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        
        cursor.execute("""
            UPDATE subjects SET name = %s, subject_type = %s, required_sessions = %s, department_id = %s, semester = %s
            WHERE id = %s RETURNING id
        """, (subject.name, subject.subject_type, subject.required_sessions, subject.department_id, subject.semester, subject_id))
        
        
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Subject not found")
        conn.commit()
        return {"success": True, "message": "Subject updated successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)

# =========================================================
# SAFELY DELETE SUBJECT
# =========================================================
@app.delete("/delete-subject/{subject_id}")
def delete_subject(subject_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM subjects WHERE id = %s RETURNING id", (subject_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Subject not found")
        conn.commit()
        return {"success": True, "message": "Subject deleted successfully"}
        
    except errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete this Subject. It is currently scheduled in a published Timetable."
        )
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
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
            INSERT INTO subjects (name, subject_type, required_sessions, department_id, semester)
            VALUES (%s, %s, %s, %s, %s)
        """, (subject.name, subject.subject_type, subject.required_sessions, subject.department_id, subject.semester))
        

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
                s.semester,
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
        
        
        # If generating for a specific batch, ONLY pull subjects for that batch's semester!
        if payload.batch_id != "all":
            cursor.execute("SELECT * FROM batches WHERE department_id = %s AND id = %s", (department_id, int(payload.batch_id)))
            batches = cursor.fetchall()
            
            # NEW: Only fetch subjects matching this batch's semester
            target_semester = batches[0]["semester"]
            cursor.execute("SELECT * FROM subjects WHERE department_id = %s AND semester = %s", (department_id, target_semester))
            subjects = cursor.fetchall()
        else:
            # If generating for the whole department, you have to group them by semester later in the math loop
            pass

        
        cursor.execute("SELECT * FROM rooms WHERE is_active = TRUE")
        rooms = cursor.fetchall()

        if payload.batch_id != "all":
            cursor.execute("SELECT * FROM batches WHERE department_id = %s AND id = %s", (department_id, int(payload.batch_id)))
            batches = cursor.fetchall()
            
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
            return {"success": False, "message": "Missing required data in this department."}

        # =====================================================
        # 2. DYNAMIC SLOTS CONFIGURATION
        # =====================================================
        dynamic_slots = []
        slot_hours = [] 
        for h in range(payload.start_hour, payload.end_hour):
            if h == payload.break_hour:
                continue 
            
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
        # 3. ENTERPRISE PRE-FLIGHT DIAGNOSTICS & HEURISTICS
        # =====================================================
        exp_map = {(exp["faculty_id"], exp["subject_id"]): float(exp["competency_tier"]) for exp in expertise}
        
        # ---> FIX: Accurately calculate workload by matching batch semester to subject semester
        total_req_hours = 0
        for batch in batches:
            batch_req_hours = sum(s["required_sessions"] for s in subjects if s["semester"] == batch["semester"])
            total_req_hours += batch_req_hours

        total_fac_capacity = sum(f["max_weekly_hours"] for f in faculties)
        if total_req_hours > total_fac_capacity:
            return {"success": False, "message": f"MATH ERROR: Department requires {total_req_hours} teaching hours, but your staff can only teach {total_fac_capacity} hours combined!"}
        # Diagnostic B: Batch Slot Limit Check
        total_weekly_slots = len(DAYS) * len(dynamic_slots)
        batch_req_hours = sum(s["required_sessions"] for s in subjects)
        if batch_req_hours > total_weekly_slots:
            return {"success": False, "message": f"MATH ERROR: Subjects require {batch_req_hours} hours/week, but your configured shift only has {total_weekly_slots} available slots!"}

        # ---> FIX: Dynamic Room Buffer (Scales up for Global Generation)
        room_buffer = 4 if payload.batch_id != "all" else max(4, len(batches) * 2)

        eligible_rooms = {}
        for batch in batches:
            for subject in subjects:
                # ---> CRITICAL FIX: Matrix Bloat Prevention! <---
                # If the subject doesn't belong to the batch's semester, SKIP IT.
                if subject["semester"] != batch["semester"]: 
                    continue
                    
                valid_rooms = []
                for room in rooms:
                    if room["capacity"] >= batch["student_count"]:
                        if subject["subject_type"] == "Practical" and room["room_type"] == "Laboratory":
                            valid_rooms.append(room)
                        elif subject["subject_type"] != "Practical" and room["room_type"] != "Laboratory":
                            valid_rooms.append(room)
                            
                valid_rooms.sort(key=lambda r: r["capacity"])
                eligible_rooms[(subject["id"], batch["id"])] = valid_rooms[:room_buffer]

        # =====================================================
        # 4. THE 3-OPTION GENERATOR LOOP
        # =====================================================
        scenarios = [
            {"name": "Option 1: Balanced", "w_exp": 10, "w_room": 20},
            {"name": "Option 2: Minimum Movement", "w_exp": 5, "w_room": 100},
            {"name": "Option 3: Faculty Expertise Focus", "w_exp": 50, "w_room": 5}
        ]

        generated_options = []
        previous_solution_keys = []
        sub_dict = {s['id']: s['name'] for s in subjects}
        room_dict = {r['id']: r['name'] for r in rooms}
        fac_dict = {f['id']: f['name'] for f in faculties}
        batch_dict = {b['id']: b['name'] for b in batches}

        for scenario in scenarios:
            model = cp_model.CpModel()
            x = {}

            # --- 4A. O(1) LIGHTNING INDEXING ---
            fac_day_slot = defaultdict(list)
            room_day_slot = defaultdict(list)
            batch_day_slot = defaultdict(list)
            batch_subject = defaultdict(list)
            fac_weekly = defaultdict(list)
            fac_day = defaultdict(list)
            batch_day_sub = defaultdict(list)
            batch_day_slot_sub = defaultdict(list)
            batch_day_slot_room = defaultdict(list)

            for faculty in faculties:
                fac_id = faculty["id"]
                for subject in subjects:
                    sub_id = subject["id"]
                    if (fac_id, sub_id) not in exp_map: continue 
                    
                    for batch in batches:
                        b_id = batch["id"]
                        if subject["semester"] != batch["semester"]:
                            continue
                        for room in eligible_rooms.get((sub_id, b_id), []):
                            r_id = room["id"]
                            for day in DAYS:
                                for slot in dynamic_slots:
                                    key = (fac_id, sub_id, r_id, day, slot, b_id)
                                    var = model.NewBoolVar(f"x_{key}")
                                    x[key] = var
                                    
                                    fac_day_slot[(fac_id, day, slot)].append(var)
                                    room_day_slot[(r_id, day, slot)].append(var)
                                    batch_day_slot[(b_id, day, slot)].append(var)
                                    batch_subject[(b_id, sub_id)].append(var)
                                    fac_weekly[fac_id].append(var)
                                    fac_day[(fac_id, day)].append(var)
                                    batch_day_sub[(b_id, day, sub_id)].append(var)
                                    batch_day_slot_sub[(b_id, day, slot, sub_id)].append(var)
                                    batch_day_slot_room[(b_id, day, slot, r_id)].append(var)

            # --- 4B. HARD CONFLICTS ---
            for vars_list in fac_day_slot.values():
                if len(vars_list) > 1: model.AddAtMostOne(vars_list)
            for vars_list in room_day_slot.values():
                if len(vars_list) > 1: model.AddAtMostOne(vars_list)
            for vars_list in batch_day_slot.values():
                if len(vars_list) > 1: model.AddAtMostOne(vars_list)

            for fac_id, vars_list in fac_weekly.items():
                max_hrs = next((f["max_weekly_hours"] for f in faculties if f["id"] == fac_id), 40)
                if vars_list: model.Add(sum(vars_list) <= max_hrs)

            # --- 4C. SESSIONS & LAB STACKING ---
            for batch in batches:
                for subject in subjects:
                    sub_id = subject["id"]
                    b_id = batch["id"]
                    req = subject["required_sessions"]
                    
                    sub_vars = batch_subject.get((b_id, sub_id), [])
                    
                    if subject["subject_type"] == "Practical":
                        block_vars = []
                        for fac in faculties:
                            if (fac["id"], sub_id) not in exp_map: continue
                            for room in eligible_rooms.get((sub_id, b_id), []):
                                for day in DAYS:
                                    for i in range(len(dynamic_slots) - req + 1):
                                        if slot_hours[i + req - 1] - slot_hours[i] != req - 1: continue 
                                        
                                        valid_block = True
                                        block_sub_vars = []
                                        for j in range(req):
                                            var_k = (fac["id"], sub_id, room["id"], day, dynamic_slots[i+j], b_id)
                                            if var_k in x: block_sub_vars.append(x[var_k])
                                            else: valid_block = False; break
                                                
                                        if valid_block:
                                            block_var = model.NewBoolVar(f"blk_{b_id}_{sub_id}_{fac['id']}_{room['id']}_{day}_{i}")
                                            block_vars.append(block_var)
                                            for var in block_sub_vars:
                                                model.AddImplication(block_var, var)
                                                
                        if block_vars: model.AddExactlyOne(block_vars)
                        if sub_vars: model.Add(sum(sub_vars) == req)
                    else:
                       # =====================================================
                        # FIX B: PREVENT CONSECUTIVE SAME-SUBJECT STACKING
                        # =====================================================
                        # The engine can schedule this subject multiple times a day, 
                        # but NEVER back-to-back in consecutive slots.
                        for day in DAYS:
                            for i in range(len(dynamic_slots) - 1):
                                slot1 = dynamic_slots[i]
                                slot2 = dynamic_slots[i+1]
                                
                                # Get the variables for this subject at slot t and t+1
                                s1_vars = batch_day_slot_sub.get((b_id, day, slot1, sub_id), [])
                                s2_vars = batch_day_slot_sub.get((b_id, day, slot2, sub_id), [])
                                
                                if s1_vars and s2_vars:
                                    # Hard rule: The sum of these two consecutive slots cannot exceed 1
                                    model.Add(sum(s1_vars) + sum(s2_vars) <= 1)
            # --- 4D. DATABASE LOCK ---
            for booking in existing_bookings:
                d, t = booking["day_of_week"], booking["timeslot"]
                for var in fac_day_slot.get((booking["faculty_id"], d, t), []): model.Add(var == 0)
                for var in room_day_slot.get((booking["room_id"], d, t), []): model.Add(var == 0)

            # --- 4E. DYNAMIC UI CONSTRAINTS ---
            if "no_consecutive" in payload.constraints:
                for batch in batches:
                    b_id = batch["id"]
                    for day in DAYS:
                        for subject in subjects:
                            if subject["subject_type"] == "Practical": continue
                            sub_id = subject["id"]
                            for i in range(len(dynamic_slots) - 1):
                                vars_s1 = batch_day_slot_sub.get((b_id, day, dynamic_slots[i], sub_id), [])
                                vars_s2 = batch_day_slot_sub.get((b_id, day, dynamic_slots[i+1], sub_id), [])
                                if vars_s1 and vars_s2: model.Add(sum(vars_s1) + sum(vars_s2) <= 1)

            if "strict_faculty_load" in payload.constraints:
                for faculty in faculties:
                    # Dynamically calculate a healthy daily limit for THIS specific professor
                    max_fac_daily = math.ceil(faculty["max_weekly_hours"] / len(DAYS)) + 1
                    
                    for day in DAYS:
                        vars_day = fac_day.get((faculty["id"], day), [])
                        if vars_day: 
                            model.Add(sum(vars_day) <= max_fac_daily)
            # --- 4F. OBJECTIVE SCORING & GAP MINIMIZERS ---
            objective_terms = []
            for key, var in x.items():
                score = int(exp_map[(key[0], key[1])] * scenario["w_exp"])
                objective_terms.append(var * score)
                
            for batch in batches:
                b_id = batch["id"]
                for day in DAYS:
                    for i in range(len(dynamic_slots) - 1):
                        if slot_hours[i+1] - slot_hours[i] != 1: continue 
                        for room in rooms:
                            r_id = room["id"]
                            b_r_s1 = batch_day_slot_room.get((b_id, day, dynamic_slots[i], r_id), [])
                            b_r_s2 = batch_day_slot_room.get((b_id, day, dynamic_slots[i+1], r_id), [])
                            if b_r_s1 and b_r_s2:
                                b_in_r1 = model.NewBoolVar(f"r1_{b_id}_{r_id}_{day}_{i}")
                                b_in_r2 = model.NewBoolVar(f"r2_{b_id}_{r_id}_{day}_{i+1}")
                                same_rm = model.NewBoolVar(f"srm_{b_id}_{r_id}_{day}_{i}")
                                model.Add(b_in_r1 == sum(b_r_s1))
                                model.Add(b_in_r2 == sum(b_r_s2))
                                model.AddBoolAnd([b_in_r1, b_in_r2]).OnlyEnforceIf(same_rm)
                                objective_terms.append(same_rm * scenario["w_room"])

            if "minimize_student_gaps" in payload.constraints:
                for batch in batches:
                    b_id = batch["id"]
                    for day in DAYS:
                        y = []
                        for i, slot in enumerate(dynamic_slots):
                            slot_vars = batch_day_slot.get((b_id, day, slot), [])
                            is_active = model.NewBoolVar(f"b_act_{b_id}_{day}_{i}")
                            if slot_vars: model.Add(is_active == sum(slot_vars))
                            else: model.Add(is_active == 0)
                            y.append(is_active)
                            
                        for i in range(1, len(dynamic_slots) - 1):
                            has_before = model.NewBoolVar(f"hb_{b_id}_{day}_{i}")
                            has_after = model.NewBoolVar(f"ha_{b_id}_{day}_{i}")
                            is_gap = model.NewBoolVar(f"gap_{b_id}_{day}_{i}")
                            
                            model.Add(sum(y[:i]) >= 1).OnlyEnforceIf(has_before)
                            model.Add(sum(y[:i]) == 0).OnlyEnforceIf(has_before.Not())
                            model.Add(sum(y[i+1:]) >= 1).OnlyEnforceIf(has_after)
                            model.Add(sum(y[i+1:]) == 0).OnlyEnforceIf(has_after.Not())
                            
                            model.AddBoolOr([y[i], has_before.Not(), has_after.Not(), is_gap])
                            objective_terms.append(is_gap * -30)

            if "minimize_faculty_gaps" in payload.constraints:
                for faculty in faculties:
                    fac_id = faculty["id"]
                    for day in DAYS:
                        y = []
                        for i, slot in enumerate(dynamic_slots):
                            slot_vars = fac_day_slot.get((fac_id, day, slot), [])
                            is_active = model.NewBoolVar(f"f_act_{fac_id}_{day}_{i}")
                            if slot_vars: model.Add(is_active == sum(slot_vars))
                            else: model.Add(is_active == 0)
                            y.append(is_active)
                            
                        for i in range(1, len(dynamic_slots) - 1):
                            has_before = model.NewBoolVar(f"fhb_{fac_id}_{day}_{i}")
                            has_after = model.NewBoolVar(f"fha_{fac_id}_{day}_{i}")
                            is_gap = model.NewBoolVar(f"fgap_{fac_id}_{day}_{i}")
                            
                            model.Add(sum(y[:i]) >= 1).OnlyEnforceIf(has_before)
                            model.Add(sum(y[:i]) == 0).OnlyEnforceIf(has_before.Not())
                            model.Add(sum(y[i+1:]) >= 1).OnlyEnforceIf(has_after)
                            model.Add(sum(y[i+1:]) == 0).OnlyEnforceIf(has_after.Not())
                            
                            model.AddBoolOr([y[i], has_before.Not(), has_after.Not(), is_gap])
                            objective_terms.append(is_gap * -30)
                            
                            
            # --- 4G. ENTERPRISE SOLUTION BANNING (FORCE DIVERGENCE) ---
            # If the engine already generated Option 1, we force it to change 
            # at least 15% of the schedule for Option 2 and Option 3!
            for prev_keys in previous_solution_keys:
                matching_vars = [x[k] for k in prev_keys if k in x]
                if matching_vars:
                    classes_to_move = max(2, len(matching_vars) // 6) # Force ~15% difference
                    model.Add(sum(matching_vars) <= len(matching_vars) - classes_to_move)
                    
           # =====================================================
            # FIX: DYNAMIC DAILY WORKLOAD LIMITS
            # =====================================================
            for batch in batches:
                b_id = batch["id"]
                
                # Dynamically calculate the maximum daily hours based on THIS batch's actual workload
                weekly_load = sum(s["required_sessions"] for s in subjects if s["semester"] == batch["semester"])
                # e.g., 25 hours / 5 days = 5. Add 1 hour buffer = 6 hours max per day.
                max_daily = math.ceil(weekly_load / len(DAYS)) + 1 
                
                for day in DAYS:
                    day_vars = []
                    for slot in dynamic_slots:
                        day_vars.extend(batch_day_slot.get((b_id, day, slot), []))
                    
                    if not day_vars: continue
                    
                    is_active_day = model.NewBoolVar(f"act_day_{b_id}_{day}")
                    
                    model.Add(sum(day_vars) > 0).OnlyEnforceIf(is_active_day)
                    model.Add(sum(day_vars) == 0).OnlyEnforceIf(is_active_day.Not())
                    
                    # THE NEW RULE: Minimum 2 hours, Maximum scales dynamically!
                    model.Add(sum(day_vars) >= 2).OnlyEnforceIf(is_active_day)
                    model.Add(sum(day_vars) <= max_daily).OnlyEnforceIf(is_active_day)


            # =====================================================
            # NEW: 2. STANDARDIZED ANCHOR PENALTY (START AT 8/9 AM)
            # =====================================================
            # Identifies the 8 AM and 9 AM slots dynamically
            anchor_slots = [dynamic_slots[i] for i, h in enumerate(slot_hours) if h in [8, 9]]
            
            for batch in batches:
                b_id = batch["id"]
                for day in DAYS:
                    day_vars = []
                    for slot in dynamic_slots:
                        day_vars.extend(batch_day_slot.get((b_id, day, slot), []))
                    
                    if not day_vars: continue
                    
                    is_active_day = model.NewBoolVar(f"anc_act_{b_id}_{day}")
                    model.Add(sum(day_vars) > 0).OnlyEnforceIf(is_active_day)
                    model.Add(sum(day_vars) == 0).OnlyEnforceIf(is_active_day.Not())
                    
                    # Check if 8 AM or 9 AM slots are used
                    early_vars = []
                    for a_slot in anchor_slots:
                        early_vars.extend(batch_day_slot.get((b_id, day, a_slot), []))
                        
                    has_early = model.NewBoolVar(f"has_early_{b_id}_{day}")
                    if early_vars:
                        model.Add(sum(early_vars) > 0).OnlyEnforceIf(has_early)
                        model.Add(sum(early_vars) == 0).OnlyEnforceIf(has_early.Not())
                    else:
                        model.Add(has_early == 0)
                        
                    # If the day is active but NO early class exists, apply a massive penalty
                    bad_anchor = model.NewBoolVar(f"bad_anchor_{b_id}_{day}")
                    model.AddBoolAnd([is_active_day, has_early.Not()]).OnlyEnforceIf(bad_anchor)
                    model.AddBoolOr([is_active_day.Not(), has_early]).OnlyEnforceIf(bad_anchor.Not())
                    
                    # Massive -50 point penalty for starting the day late
                    objective_terms.append(bad_anchor * -50)

            model.Maximize(sum(objective_terms))

            # --- 4G. SOLVE (WITH RANDOMIZED DIVERGENCE) ---
            solver = cp_model.CpSolver()
            
            # Reduce to 3 seconds per option so the browser doesn't time out (9s total limit)
            solver.parameters.max_time_in_seconds = 5
            
            # THE ENTERPRISE FIX: Force the math engine to explore completely different 
            # mathematical branches for each scenario so you get 3 UNIQUE options!
            if "Balanced" in scenario["name"]:
                solver.parameters.random_seed = 1
            elif "Movement" in scenario["name"]:
                solver.parameters.random_seed = 42
            else:
                solver.parameters.random_seed = 999

            status = solver.Solve(model)

            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                draft_records = []
                current_solution_keys = [] # <-- NEW: Track this specific run
                
                for key, var in x.items():
                    if solver.Value(var) == 1:
                        current_solution_keys.append(key) # <-- NEW: Save the boolean key
                        draft_records.append({
                            "department_id": department_id, "faculty_id": key[0], "subject_id": key[1],
                            "room_id": key[2], "day_of_week": key[3], "timeslot": key[4], "batch_id": key[5],
                            "faculty": fac_dict[key[0]], "subject": sub_dict[key[1]], "room": room_dict[key[2]], "batch": batch_dict[key[5]]
                        })
                        
                previous_solution_keys.append(current_solution_keys) # <-- NEW: Add to ban list for next loop!
                generated_options.append({"option_name": scenario["name"], "records": draft_records})

        if generated_options:
            return {
                "success": True, 
                "message": f"Successfully generated {len(generated_options)} optimization options!",
                "draft_options": generated_options 
            }
        else:
            return {"success": False, "message": "The math is too tight! No feasible timetable could be found under these strict constraints."}       
         
    except Exception as e:
        print("--- SCHEDULER ENGINE CRASHED ---")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        cursor.close()
        release_db_connection(conn)
# CHANGE:safe timetable saving with transaction and batch deletion/insertion    

# =========================================================
# two new, extremely fast API routes. One to start the job, and one to check its status.
# =========================================================

@app.post("/generate-timetable/{department_id}")
def dispatch_timetable_generation(department_id: int, payload: GenerateRequest):
    # Send the heavy math to the background worker instantly
    task = generate_timetable_task.delay(department_id, payload.model_dump())
    
    # Return immediately to the UI so the browser doesn't freeze!
    return {"success": True, "task_id": task.id, "message": "Generation started in background."}

@app.get("/task-status/{task_id}")
def get_task_status(task_id: str):
    task_result = AsyncResult(task_id, app=celery_app)
    
    if task_result.state == 'PENDING':
        return {"state": task_result.state, "message": "Waiting in queue..."}
    elif task_result.state == 'PROGRESS':
        return {"state": task_result.state, "message": task_result.info.get('message', '')}
    elif task_result.state == 'SUCCESS':
        return {"state": task_result.state, "result": task_result.result}
    else:
        return {"state": task_result.state, "message": str(task_result.info)}
    
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
# TIMETABLE SWAP VALIDATION
# =========================================================
        
        
@app.post("/validate-swap/")
def validate_timetable_swap(payload: SwapValidationRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check 1: Is the Faculty already teaching another batch at this new time?
        cursor.execute("""
            SELECT id FROM timetables 
            WHERE faculty_id = %s AND day_of_week = %s AND timeslot = %s
        """, (payload.faculty_id, payload.new_day, payload.new_timeslot))
        if cursor.fetchone():
            return {"valid": False, "message": "Conflict: This Professor is already teaching another class at this time."}

        # Check 2: Is the Room already occupied by another batch?
        cursor.execute("""
            SELECT id FROM timetables 
            WHERE room_id = %s AND day_of_week = %s AND timeslot = %s
        """, (payload.room_id, payload.new_day, payload.new_timeslot))
        if cursor.fetchone():
            return {"valid": False, "message": "Conflict: This Room is already booked by another class at this time."}

        # If it passes all checks, the move is legal!
        return {"valid": True, "message": "Move is valid!"}
        
    finally:
        cursor.close()
        release_db_connection(conn)




@app.post("/suggest-auto-fix/")
def suggest_auto_fix(payload: AutoFixRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Find exactly WHAT is causing the conflict
        cursor.execute("""
            SELECT id, subject_id, batch_id, faculty_id, room_id, day_of_week, timeslot 
            FROM timetables 
            WHERE department_id = %s AND day_of_week = %s AND timeslot = %s
            AND (faculty_id = %s OR room_id = %s)
        """, (payload.department_id, payload.target_day, payload.target_timeslot, payload.faculty_id, payload.room_id))
        
        conflict_class = cursor.fetchone()
        
        if not conflict_class:
            return {"can_fix": True, "message": "No conflict detected. Move is valid."}

        # 2. Try the easiest swap: Can the conflicting class just move to the empty slot we are leaving behind?
        cursor.execute("""
            SELECT id FROM timetables 
            WHERE day_of_week = %s AND timeslot = %s AND (faculty_id = %s OR room_id = %s)
        """, (payload.original_day, payload.original_timeslot, conflict_class["faculty_id"], conflict_class["room_id"]))
        
        reverse_conflict = cursor.fetchone()
        
        if not reverse_conflict:
            return {
                "can_fix": True, 
                "type": "Direct Swap",
                "message": f"Swap Suggested: Move this class here, and move the conflicting class to {payload.original_day} at {payload.original_timeslot}.",
                "displaced_class_id": conflict_class["id"],
                "new_day": payload.original_day,
                "new_time": payload.original_timeslot
            }
            
        # 3. If a direct swap fails, the Mini-Solver would trigger here to search all days.
        # For now, return a failure if the simple swap doesn't work.
        return {"can_fix": False, "message": "Complex conflict. Manual intervention required."}

    finally:
        cursor.close()
        release_db_connection(conn)



# =========================================================
# LIVE DRAG & DROP SAVE API
# =========================================================
@app.put("/update-timetable-slot/")
def update_timetable_slot(payload: UpdateSlotRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Update the database with the new day and time
        cursor.execute("""
            UPDATE timetables 
            SET day_of_week = %s, timeslot = %s 
            WHERE id = %s
        """, (payload.new_day, payload.new_timeslot, payload.record_id))
        
        conn.commit()
        return {"success": True, "message": "Timetable updated permanently!"}
        
    except Exception as e:
        conn.rollback()
        # If the database throws a Unique Constraint error (conflict), catch it safely!
        if "unique constraint" in str(e).lower():
            return {"success": False, "message": "Database Conflict: Room or Faculty is occupied."}
        return {"success": False, "message": str(e)}
        
    finally:
        cursor.close()
        release_db_connection(conn)

# =========================================================
# VIEW TIMETABLE
# =========================================================

@app.get("/view-timetable/")
def view_timetable(department_id: int = None, batch_id: int = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # THE FIX: Added t.id, t.batch_id, t.faculty_id, t.room_id, t.notes
        query = """
            SELECT 
                t.id, t.batch_id, t.faculty_id, t.room_id, t.notes,
                t.day_of_week, t.timeslot, b.name AS batch, s.name AS subject, 
                r.name AS room, f.name AS faculty
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
            "success": True,
            "data": cursor.fetchall()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cursor.close()
        release_db_connection(conn)
        
# =========================================================
# DELETE TIMETABLE (FOR RE-GENERATION)
# ========================================================= 
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
        
        
        
 # =========================================================
# GLOBAL ANALYTICS DASHBOARD API (NEXT-LEVEL SAAS)
# =========================================================
@app.get("/dashboard-stats/global")
def get_global_dashboard_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    import math
    try:
        # 1. Executive Stats
        cursor.execute("SELECT COUNT(*) as count FROM faculties")
        fac_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM batches")
        batch_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COALESCE(SUM(student_count), 0) as count FROM batches")
        student_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM departments")
        dept_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM subjects")
        subject_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM rooms WHERE is_active = TRUE")
        room_count = cursor.fetchone()["count"]
        
        total_possible_slots = room_count * 35 
        cursor.execute("SELECT COUNT(*) as count FROM timetables")
        booked_slots = cursor.fetchone()["count"]
        utilization = round((booked_slots / total_possible_slots) * 100) if total_possible_slots > 0 else 0

       # 2. Faculty Workload & Overload Calculation
        cursor.execute("""
            SELECT f.id, f.name, COUNT(t.id) as assigned_hours, f.max_weekly_hours, f.department_id 
            FROM faculties f
            LEFT JOIN timetables t ON f.id = t.faculty_id
            GROUP BY f.id, f.name, f.max_weekly_hours, f.department_id
            ORDER BY assigned_hours DESC
        """)
        faculty_load = cursor.fetchall()
        
        overworked_count = sum(1 for f in faculty_load if f["max_weekly_hours"] > 0 and (f["assigned_hours"] / f["max_weekly_hours"]) >= 0.9)
        underused_rooms_count = math.ceil(room_count * (1 - (utilization / 100))) if utilization < 60 else 0

        # 3. System Issues (Unscheduled & Unmapped)
        cursor.execute("SELECT COUNT(*) as c FROM (SELECT b.id FROM batches b LEFT JOIN timetables t ON b.id = t.batch_id GROUP BY b.id HAVING COUNT(t.id) = 0) as sub")
        unscheduled_batches = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) as c FROM (SELECT s.id FROM subjects s LEFT JOIN faculty_expertise fe ON s.id = fe.subject_id GROUP BY s.id HAVING COUNT(fe.faculty_id) = 0) as sub")
        unmapped_subjects = cursor.fetchone()["c"]

        total_issues = unscheduled_batches + unmapped_subjects + overworked_count

        # =========================================================
        # 4. TIMETABLE HEALTH SCORE ENGINE
        # =========================================================
        health_score = 100
        health_checklist = []

        # Check Faculty
        if overworked_count == 0:
            health_checklist.append({"status": "pass", "text": "No overloaded faculty"})
        else:
            health_score -= (overworked_count * 3)
            health_checklist.append({"status": "warn", "text": f"{overworked_count} faculty overloaded"})

        # Check Rooms
        if utilization <= 85:
            health_checklist.append({"status": "pass", "text": "Healthy room utilization"})
        else:
            health_score -= 10
            health_checklist.append({"status": "warn", "text": "High room clashes/usage"})
            
        if underused_rooms_count > 0:
            health_checklist.append({"status": "info", "text": f"{underused_rooms_count} underutilized rooms"})

        # Check Batches
        if unscheduled_batches == 0:
            health_checklist.append({"status": "pass", "text": "All batches scheduled"})
        else:
            health_score -= (unscheduled_batches * 5)
            health_checklist.append({"status": "fail", "text": f"{unscheduled_batches} unscheduled batches"})

        # Check Subjects
        if unmapped_subjects > 0:
            health_score -= (unmapped_subjects * 2)
            health_checklist.append({"status": "fail", "text": f"{unmapped_subjects} unmapped subjects"})

        health_score = max(0, min(100, health_score)) # Clamp between 0-100

        # =========================================================
        # 5. PREDICTIVE ANALYTICS ENGINE
        # =========================================================
        exp_fac_shortage = math.ceil(overworked_count * 0.5) + (2 if utilization > 90 else 0)
        exp_room_shortage = math.ceil((utilization - 85) / 100 * room_count) if utilization > 85 else 0
        
        risk_level = "Low"
        if health_score < 70 or exp_fac_shortage > 2: risk_level = "High"
        elif health_score < 85 or exp_fac_shortage > 0: risk_level = "Medium"

        predictive = {
            "sufficient": "YES" if exp_fac_shortage == 0 and exp_room_shortage <= 0 else "NO",
            "faculty_shortage": exp_fac_shortage,
            "room_shortage": f"{exp_room_shortage} Labs/Rooms" if exp_room_shortage > 0 else "None",
            "next_sem_risk": risk_level
        }

        # =========================================================
        # 6. AI RECOMMENDATIONS (Dynamic)
        # =========================================================
        recommendations = []
        if exp_fac_shortage > 0:
            recommendations.append({"type": "warning", "icon": "person_add", "title": "Hire New Faculty", "message": f"Predictive models suggest hiring {exp_fac_shortage} new professors to maintain health next semester."})
        if exp_room_shortage > 0:
            recommendations.append({"type": "error", "icon": "domain_disabled", "title": "Room Shortage Predicted", "message": f"You will need {exp_room_shortage} additional rooms to comfortably house next semester's batches."})
        if unmapped_subjects > 0:
            recommendations.append({"type": "action", "icon": "menu_book", "title": "Map Expertise", "message": f"{unmapped_subjects} subjects are unteachable right now. Map faculty to them immediately."})
        if not recommendations:
            recommendations.append({"type": "success", "icon": "auto_awesome", "title": "Perfect Harmony", "message": "No predictive risks detected. Current resources are perfectly balanced."})

        return {
            "success": True,
            "stats": {
                "departments": dept_count, "faculty": fac_count, "students": student_count,
                "rooms": room_count, "subjects": subject_count, "issues": total_issues,
                "utilization": utilization, "version": "v3.1 (Live)"
            },
            "health": { "score": health_score, "checklist": health_checklist },
            "predictive": predictive,
            "faculty_load": faculty_load[:15], # Top 15 for Chart
            "recommendations": recommendations 
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)
        
        
        