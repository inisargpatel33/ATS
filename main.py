from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from ortools.sat.python import cp_model
from pydantic import BaseModel
from typing import List
from typing import Optional
import psycopg2.errors
app = FastAPI(title="Timetable SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "postgresql://postgres:Nsrg%4033patel@db.rxseblfkhgyzuimejnmu.supabase.co:5432/postgres"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ==========================================
# DATA MODELS
# ==========================================
class RoomCreate(BaseModel):
    name: str
    capacity: int
    room_type: str
    amenities: List[str]
    is_active: bool = True
    department_id: int
    
    
    
    
class DeptCreate(BaseModel):
    name: str

# --- DEPARTMENT API ROUTES ---

@app.post("/add-department/")
def add_department(dept: DeptCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id;", (dept.name,))
        conn.commit()
        return {"success": True, "message": "Added successfully!"}
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Department already exists.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/get-departments/")
def get_departments():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM departments ORDER BY id ASC;")
        return {"data": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()

@app.delete("/delete-department/{dept_id}")
def delete_department(dept_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM departments WHERE id = %s RETURNING id;", (dept_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Department not found.")
        conn.commit()
        return {"success": True, "message": "Deleted"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==========================================
# FACULTY API
# ==========================================
class FacultyCreate(BaseModel):
    department_id: int
    name: str
    max_weekly_hours: int = 15

@app.post("/add-faculty/")
def add_faculty(faculty: FacultyCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO faculties (department_id, name, max_weekly_hours)
            VALUES (%s, %s, %s) RETURNING id;
        """, (faculty.department_id, faculty.name, faculty.max_weekly_hours))
        conn.commit()
        return {"success": True, "message": "Faculty added successfully!"}
        
    except psycopg2.errors.CheckViolation:
        # Catches the (max_weekly_hours > 0 AND <= 40) constraint
        conn.rollback()
        raise HTTPException(status_code=400, detail="Weekly hours must be between 1 and 40.")
    except psycopg2.errors.UniqueViolation:
        # Catches the UNIQUE (department_id, name) constraint
        conn.rollback()
        raise HTTPException(status_code=400, detail="This faculty member already exists in this department.")
    except psycopg2.errors.ForeignKeyViolation:
        # Catches if the department ID doesn't exist
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# @app.get("/get-faculties/")
# def get_faculties():
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     try:
#         # JOIN with departments so we can display the actual department name in the UI
#         cursor.execute("""
#             SELECT f.id, f.name, f.max_weekly_hours, d.name as department_name 
#             FROM faculties f
#             JOIN departments d ON f.department_id = d.id
#             ORDER BY f.id ASC;
#         """)
#         return {"data": cursor.fetchall()}
#     finally:
#         cursor.close()
#         conn.close()

@app.get("/get-faculties/")
def get_faculties():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Get all faculties and their departments
        cursor.execute("""
            SELECT f.id, f.name, f.max_weekly_hours, f.department_id, d.name as department_name 
            FROM faculties f
            JOIN departments d ON f.department_id = d.id
            ORDER BY f.id ASC;
        """)
        faculties = cursor.fetchall()
        
        # 2. Get all expertise mappings and subject names
        cursor.execute("""
            SELECT fe.faculty_id, s.name as subject_name, fe.competency_tier
            FROM faculty_expertise fe
            JOIN subjects s ON fe.subject_id = s.id;
        """)
        expertise_records = cursor.fetchall()
        
        # 3. Group the subjects by faculty_id
        exp_map = {}
        for exp in expertise_records:
            fid = exp['faculty_id']
            if fid not in exp_map:
                exp_map[fid] = {'primary': [], 'secondary': []}
                
            if float(exp['competency_tier']) == 1.0:
                exp_map[fid]['primary'].append(exp['subject_name'])
            else:
                exp_map[fid]['secondary'].append(exp['subject_name'])
                
        # 4. Attach the grouped subjects to the faculty data
        for f in faculties:
            fid = f['id']
            f['primary_subjects'] = exp_map.get(fid, {}).get('primary', [])
            f['secondary_subjects'] = exp_map.get(fid, {}).get('secondary', [])
            
        return {"data": faculties}
    except Exception as e:
        print("--- FETCH FACULTIES ERROR ---")
        print(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
        

@app.delete("/delete-faculty/{faculty_id}")
def delete_faculty(faculty_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM faculties WHERE id = %s RETURNING id;", (faculty_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Faculty not found.")
        conn.commit()
        return {"success": True, "message": "Deleted"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
        
        
# ==========================================
# ROOMS API
# ==========================================
# ==========================================
# ROOMS API
# ==========================================
class RoomCreate(BaseModel):
    name: str
    capacity: int
    room_type: str
    amenities: List[str]
    is_active: bool = True
    department_id: int

@app.post("/add-room/")
def add_room(room: RoomCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        has_proj = "Projector" in room.amenities
        has_ac = "AC" in room.amenities
        has_wb = "Whiteboard" in room.amenities
        has_comp = "Computers" in room.amenities

        cursor.execute("""
            INSERT INTO rooms (
                name, capacity, room_type, department_id,
                has_projector, has_ac, has_whiteboard, has_computers, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """, (
            room.name, room.capacity, room.room_type, room.department_id,
            has_proj, has_ac, has_wb, has_comp, room.is_active
        ))
        conn.commit()
        return {"success": True, "message": f"Room '{room.name}' added successfully!"}
        
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="A room with this exact name already exists.")
    except psycopg2.errors.CheckViolation as e:
        conn.rollback()
        err_str = str(e).lower()
        if "capacity" in err_str:
            detail = "Room capacity must be greater than 0."
        else:
            detail = "Invalid room type selected."
        raise HTTPException(status_code=400, detail=detail)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/get-rooms/{department_id}")
def get_rooms(department_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM rooms WHERE department_id = %s ORDER BY name ASC", (department_id,))
        return {"data": cursor.fetchall()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/edit-room/{room_id}")
def edit_room(room_id: int, room: RoomCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        has_proj = "Projector" in room.amenities
        has_ac = "AC" in room.amenities
        has_wb = "Whiteboard" in room.amenities
        has_comp = "Computers" in room.amenities

        cursor.execute("""
            UPDATE rooms 
            SET name = %s, capacity = %s, room_type = %s, department_id = %s,
                has_projector = %s, has_ac = %s, has_whiteboard = %s, has_computers = %s, is_active = %s
            WHERE id = %s RETURNING id;
        """, (
            room.name, room.capacity, room.room_type, room.department_id,
            has_proj, has_ac, has_wb, has_comp, room.is_active, room_id
        ))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Room not found.")
            
        conn.commit()
        return {"success": True, "message": "Room updated successfully!"}
        
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="A room with this exact name already exists.")
    except psycopg2.errors.CheckViolation as e:
        conn.rollback()
        err_str = str(e).lower()
        if "capacity" in err_str:
            detail = "Room capacity must be greater than 0."
        else:
            detail = "Invalid room type selected."
        raise HTTPException(status_code=400, detail=detail)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.delete("/delete-room/{room_id}")
def delete_room(room_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM rooms WHERE id = %s RETURNING id;", (room_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Room not found.")
        conn.commit()
        return {"success": True, "message": "Room deleted successfully!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

class BatchCreate(BaseModel):
    name: str
    student_count: int
    mentor_id: Optional[int] = None
    department_id: int
    shift: str = "Morning"  # Add this line


@app.post("/add-batch/")
def add_batch(batch: BatchCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO batches (name, student_count, mentor_id, department_id)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (batch.name, batch.student_count, batch.mentor_id, batch.department_id))
        conn.commit()
        return {"success": True, "message": f"Batch '{batch.name}' added successfully!"}
        
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="A batch with this name already exists in this department.")
    except psycopg2.errors.CheckViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Student count must be greater than 0.")
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department or Mentor selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/get-batches/{department_id}")
def get_batches(department_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Use LEFT JOIN because mentor_id can be NULL
        cursor.execute("""
           SELECT b.id, b.name, b.student_count, b.shift, b.department_id, b.mentor_id, f.name AS mentor_name
           FROM batches b
            LEFT JOIN faculties f ON b.mentor_id = f.id
            WHERE b.department_id = %s 
            ORDER BY b.name ASC;
        """, (department_id,))
        return {"data": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()

@app.put("/edit-batch/{batch_id}")
def edit_batch(batch_id: int, batch: BatchCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE batches 
            SET name = %s, student_count = %s, mentor_id = %s, department_id = %s
            WHERE id = %s RETURNING id;
        """, (batch.name, batch.student_count, batch.mentor_id, batch.department_id, batch_id))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Batch not found.")
            
        conn.commit()
        return {"success": True, "message": f"Batch '{batch.name}' updated successfully!"}
        
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="A batch with this name already exists in this department.")
    except psycopg2.errors.CheckViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Student count must be greater than 0.")
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department or Mentor selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.delete("/delete-batch/{batch_id}")
def delete_batch(batch_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM batches WHERE id = %s RETURNING id;", (batch_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Batch not found")
        conn.commit()
        return {"success": True, "message": "Batch deleted successfully!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==========================================
# SUBJECTS API
# ==========================================
class SubjectCreate(BaseModel):
    name: str
    subject_type: str
    required_sessions: int
    department_id: int

@app.post("/add-subject/")
def add_subject(subject: SubjectCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO subjects (name, subject_type, required_sessions, department_id)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (subject.name, subject.subject_type, subject.required_sessions, subject.department_id))
        conn.commit()
        return {"success": True, "message": f"Subject '{subject.name}' added successfully!"}
        
    except psycopg2.errors.CheckViolation as e:
        conn.rollback()
        error_msg = str(e).lower()
        if "subject_type" in error_msg:
            detail = "Invalid subject type. Must be 'Theory', 'Practical', or 'Seminar'."
        else:
            detail = "Required sessions must be between 1 and 10."
        raise HTTPException(status_code=400, detail=detail)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/get-subjects/{department_id}")
def get_subjects(department_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # We join with departments so the UI can display the department name
        cursor.execute("""
            SELECT s.id, s.name, s.subject_type, s.required_sessions, s.department_id, d.name AS department_name
            FROM subjects s
            JOIN departments d ON s.department_id = d.id
            WHERE s.department_id = %s 
            ORDER BY s.name ASC;
        """, (department_id,))
        return {"data": cursor.fetchall()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/edit-subject/{subject_id}")
def edit_subject(subject_id: int, subject: SubjectCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE subjects 
            SET name = %s, subject_type = %s, required_sessions = %s, department_id = %s
            WHERE id = %s RETURNING id;
        """, (subject.name, subject.subject_type, subject.required_sessions, subject.department_id, subject_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Subject not found")
        conn.commit()
        return {"success": True, "message": "Subject updated successfully!"}
        
    except psycopg2.errors.CheckViolation as e:
        conn.rollback()
        error_msg = str(e).lower()
        if "subject_type" in error_msg:
            detail = "Invalid subject type. Must be 'Theory', 'Practical', or 'Seminar'."
        else:
            detail = "Required sessions must be between 1 and 10."
        raise HTTPException(status_code=400, detail=detail)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid Department selected.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.delete("/delete-subject/{subject_id}")
def delete_subject(subject_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM subjects WHERE id = %s RETURNING id;", (subject_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Subject not found")
        conn.commit()
        return {"success": True, "message": "Subject deleted successfully!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


# ==========================================
# FACULTY EXPERTISE API
# ==========================================
class ExpertiseCreate(BaseModel):
    faculty_id: int
    subject_id: int
    competency_tier: float

@app.post("/add-expertise/")
def add_expertise(exp: ExpertiseCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO faculty_expertise (faculty_id, subject_id, competency_tier)
            VALUES (%s, %s, %s)
            ON CONFLICT (faculty_id, subject_id) 
            DO UPDATE SET competency_tier = EXCLUDED.competency_tier;
        """, (exp.faculty_id, exp.subject_id, exp.competency_tier))
        conn.commit()
        return {"success": True, "message": "Expertise mapped successfully!"}
    except psycopg2.errors.CheckViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Competency tier must be 1.0 or 0.5.")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/get-expertise/{faculty_id}")
def get_faculty_expertise(faculty_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT s.id, s.name, fe.competency_tier 
            FROM faculty_expertise fe
            JOIN subjects s ON fe.subject_id = s.id
            WHERE fe.faculty_id = %s;
        """, (faculty_id,))
        return {"data": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()













class GenerateRequest(BaseModel):
    constraints: List[str] = []

@app.post("/generate-timetable/{department_id}")
def generate_timetable(department_id: int, payload: GenerateRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Fetch All Relational Entities
        cursor.execute("SELECT * FROM faculties WHERE department_id = %s", (department_id,))
        faculties = cursor.fetchall()
        
        cursor.execute("SELECT * FROM subjects WHERE department_id = %s", (department_id,))
        subjects = cursor.fetchall()
        
        cursor.execute("SELECT * FROM rooms WHERE department_id = %s AND is_active = TRUE", (department_id,))
        rooms = cursor.fetchall()
        
        cursor.execute("SELECT * FROM batches WHERE department_id = %s", (department_id,))
        batches = cursor.fetchall()
        
        cursor.execute("""
            SELECT fe.faculty_id, fe.subject_id, fe.competency_tier 
            FROM faculty_expertise fe
            JOIN faculties f ON fe.faculty_id = f.id
            WHERE f.department_id = %s
        """, (department_id,))
        expertise = cursor.fetchall() 
        
        if not faculties or not subjects or not batches or not rooms:
            return {"success": False, "message": "Missing necessary data to run the engine."}

        exp_map = {(exp['faculty_id'], exp['subject_id']): float(exp['competency_tier']) for exp in expertise}

        model = cp_model.CpModel()
        days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        
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
        
        # Create a unique list of all possible timeslots across all shifts
        all_slots = list(dict.fromkeys(SHIFT_SLOTS["Morning"] + SHIFT_SLOTS["Afternoon"]))
        
        # 2. Define Variables
        x = {}
        for f in faculties:
            f_id = f['id']
            for s in subjects:
                s_id = s['id']
                
                # Check faculty expertise
                if (f_id, s_id) not in exp_map: 
                    continue 
                    
                for r in rooms:
                    r_id = r['id']
                    
                    # Check room type matching
                    if s['subject_type'] == 'Practical' and r['room_type'] != 'Laboratory':
                        continue
                    if s['subject_type'] in ['Theory', 'Seminar'] and r['room_type'] == 'Laboratory':
                        continue

                    for d in days:
                        for b in batches:
                            b_id = b['id']
                            batch_shift = b.get('shift', 'Morning')
                            
                            for t in SHIFT_SLOTS[batch_shift]:
                                x[(f_id, s_id, r_id, d, t, b_id)] = model.NewBoolVar(f'x_{f_id}_{s_id}_{r_id}_{d}_{t}_{b_id}')
                                
        # 3. Base Hard Constraints (Always applied)
        for f in faculties:
            for d in days:
                for t in all_slots:
                    faculty_vars = [x[k] for k in x if k[0] == f['id'] and k[3] == d and k[4] == t]
                    if faculty_vars:
                        model.AddAtMostOne(faculty_vars)

        for r in rooms:
            for d in days:
                for t in all_slots:
                    room_vars = [x[k] for k in x if k[2] == r['id'] and k[3] == d and k[4] == t]
                    if room_vars:
                        model.AddAtMostOne(room_vars)

        for b in batches:
            for d in days:
                for t in all_slots:
                    batch_vars = [x[k] for k in x if k[5] == b['id'] and k[3] == d and k[4] == t]
                    if batch_vars:
                        model.AddAtMostOne(batch_vars)

        for b in batches:
            for s in subjects:
                subject_vars = [x[k] for k in x if k[1] == s['id'] and k[5] == b['id']]
                if subject_vars:
                    model.Add(sum(subject_vars) == s['required_sessions'])
                elif s['required_sessions'] > 0:
                    model.Add(0 == 1)

        for f in faculties:
            faculty_total_vars = [x[k] for k in x if k[0] == f['id']]
            if faculty_total_vars:
                model.Add(sum(faculty_total_vars) <= f['max_weekly_hours'])

        # ==================================================
        # 4. OPTIONAL DYNAMIC CONSTRAINTS (From UI)
        # ==================================================
        
        # Rule 1: No Consecutive Same Subject for a Batch
        if "no_consecutive" in payload.constraints:
            for b in batches:
                batch_shift = b.get('shift', 'Morning')
                shift_times = SHIFT_SLOTS[batch_shift]
                
                for s in subjects:
                    for d in days:
                        for i in range(len(shift_times) - 1):
                            t1, t2 = shift_times[i], shift_times[i+1]
                            var_t1 = [x[k] for k in x if k[5] == b['id'] and k[1] == s['id'] and k[3] == d and k[4] == t1]
                            var_t2 = [x[k] for k in x if k[5] == b['id'] and k[1] == s['id'] and k[3] == d and k[4] == t2]
                            
                            if var_t1 and var_t2:
                                model.Add(sum(var_t1) + sum(var_t2) <= 1)

        # Rule 2: Strict Faculty Load (Max 2 classes per day per faculty)
        if "strict_faculty_load" in payload.constraints:
            for f in faculties:
                for d in days:
                    daily_faculty_vars = [x[k] for k in x if k[0] == f['id'] and k[3] == d]
                    if daily_faculty_vars:
                        model.Add(sum(daily_faculty_vars) <= 2)

        # Rule 3: Faculty gets at least one day off per week
        if "faculty_day_off" in payload.constraints:
            for f in faculties:
                day_active_vars = []
                for d in days:
                    active = model.NewBoolVar(f'active_{f["id"]}_{d}')
                    day_vars = [x[k] for k in x if k[0] == f['id'] and k[3] == d]
                    if day_vars:
                        model.AddMaxEquality(active, day_vars)
                    else:
                        model.Add(active == 0)
                    day_active_vars.append(active)
                model.Add(sum(day_active_vars) <= 4)

        # ==================================================
        
        # 5. Objective: Maximize Expertise Match (+ optional Morning Heavy rule)
        objective_terms = []
        for k, var in x.items():
            f_id, s_id, t = k[0], k[1], k[4]
            weight = int(exp_map[(f_id, s_id)] * 10)
            
            # Rule 4: Morning Heavy (Penalize afternoon slots to pack mornings)
            if "morning_heavy" in payload.constraints:
                if "PM" in t and "12:00" not in t:
                    weight -= 2 
                    
            objective_terms.append(var * weight)
            
        model.Maximize(sum(objective_terms))

        # 6. Run Solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 8.0 
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            cursor.execute("DELETE FROM timetables WHERE department_id = %s;", (department_id,))
            
            records_to_insert = []
            for k, var in x.items():
                if solver.Value(var) == 1:
                    f_id, s_id, r_id, d, t, b_id = k
                    records_to_insert.append((department_id, d, t, r_id, b_id, s_id, f_id))
            
            if records_to_insert:
                cursor.executemany("""
                    INSERT INTO timetables (department_id, day_of_week, timeslot, room_id, batch_id, subject_id, faculty_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, records_to_insert)
            
            conn.commit()
            return {"success": True, "message": "Optimal Flow Reached", "total_lectures_scheduled": len(records_to_insert)}
        else:
            return {"success": False, "message": "Engine failed. The combined constraints are too tight."}

    except Exception as e:
        conn.rollback()
        import traceback
        traceback.print_exc() # This will print the exact line of failure to your terminal if it crashes again
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
        
        
@app.get("/view-timetable/")
def view_timetable(department_id: Optional[int] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Join tables to get actual names instead of just IDs
        query = """
            SELECT 
                t.day_of_week,
                t.timeslot,
                b.name AS batch,
                s.name AS subject,
                r.name AS room,
                f.name AS faculty
            FROM timetables t
            JOIN batches b ON t.batch_id = b.id
            JOIN subjects s ON t.subject_id = s.id
            JOIN rooms r ON t.room_id = r.id
            JOIN faculties f ON t.faculty_id = f.id
        """
        
        # Optional filter if you want to support department-specific fetching later
        if department_id:
            query += f" WHERE t.department_id = {department_id}"
            
        cursor.execute(query)
        records = cursor.fetchall()
        
        return {"data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close() 



@app.get("/get-batches/{department_id}")
def get_batches_by_department(department_id: int):
    conn = get_db_connection()
    # Assuming your database connection uses a dictionary cursor based on your generate function
    cursor = conn.cursor() 
    
    try:
        # We explicitly filter the batches WHERE department_id matches the route parameter
        cursor.execute("""
            SELECT id, name 
            FROM batches 
            WHERE department_id = %s
        """, (department_id,))
        
        batches = cursor.fetchall()
        
        # Returns the exact format your frontend JavaScript is expecting: result.data
        return {"data": batches}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch batches.")
    finally:
        cursor.close()
        conn.close()