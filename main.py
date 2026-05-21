from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from ortools.sat.python import cp_model
from pydantic import BaseModel
from typing import List

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

# ==========================================
# ROOMS API
# ==========================================
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
        
    except Exception as e:
        print("--- DATABASE INSERT ERROR ---")
        print(e)
        print("-----------------------------")
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
        print("--- FETCH ROOMS ERROR ---")
        print(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
        
# ==========================================
# UPDATE ROOM API
# ==========================================
@app.put("/edit-room/{room_id}")
def edit_room(room_id: int, room: RoomCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Convert the list of amenities into Boolean values for the database
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
            raise HTTPException(status_code=404, detail="Room not found")
            
        conn.commit()
        return {"success": True, "message": f"Room '{room.name}' updated successfully!"}
        
    except Exception as e:
        print("--- DATABASE UPDATE ERROR ---")
        print(e)
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==========================================
# DELETE ROOM API
# ==========================================
@app.delete("/delete-room/{room_id}")
def delete_room(room_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Note: If a room is already scheduled in a timetable, PostgreSQL might block this 
        # delete if you have Foreign Key constraints. For now, this will delete the room.
        cursor.execute("DELETE FROM rooms WHERE id = %s RETURNING id;", (room_id,))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Room not found")
            
        conn.commit()
        return {"success": True, "message": "Room deleted successfully!"}
        
    except Exception as e:
        print("--- DATABASE DELETE ERROR ---")
        print(e)
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


# ==========================================
# BATCHES API
# ==========================================
class BatchCreate(BaseModel):
    name: str
    student_count: int
    mentor_name: str
    department_id: int

@app.post("/add-batch/")
def add_batch(batch: BatchCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO batches (name, student_count, mentor_name, department_id)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (batch.name, batch.student_count, batch.mentor_name, batch.department_id))
        conn.commit()
        return {"success": True, "message": f"Batch '{batch.name}' added successfully!"}
    except Exception as e:
        print("--- DATABASE INSERT ERROR ---")
        print(e)
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
        cursor.execute("SELECT * FROM batches WHERE department_id = %s ORDER BY name ASC", (department_id,))
        return {"data": cursor.fetchall()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()
        

# ==========================================
# UPDATE BATCH API
# ==========================================
@app.put("/edit-batch/{batch_id}")
def edit_batch(batch_id: int, batch: BatchCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE batches 
            SET name = %s, student_count = %s, mentor_name = %s, department_id = %s
            WHERE id = %s RETURNING id;
        """, (batch.name, batch.student_count, batch.mentor_name, batch.department_id, batch_id))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Batch not found")
            
        conn.commit()
        return {"success": True, "message": f"Batch '{batch.name}' updated successfully!"}
    except Exception as e:
        print("--- DATABASE UPDATE ERROR ---")
        print(e)
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==========================================
# DELETE BATCH API
# ==========================================
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
        print("--- DATABASE DELETE ERROR ---")
        print(e)
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
        cursor.execute("SELECT * FROM subjects WHERE department_id = %s ORDER BY name ASC", (department_id,))
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
# TIMETABLE API
# ==========================================
@app.post("/generate-timetable/{department_id}")
def generate_timetable(department_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM faculties WHERE department_id = %s", (department_id,))
        faculties = cursor.fetchall()
        
        cursor.execute("SELECT * FROM subjects WHERE department_id = %s", (department_id,))
        subjects = cursor.fetchall()
        
        # We also need to fetch rooms for the timetable generation
        cursor.execute("SELECT * FROM rooms WHERE department_id = %s", (department_id,))
        rooms = cursor.fetchall()
        
        cursor.execute("SELECT * FROM batches WHERE department_id = %s", (department_id,))
        batches = cursor.fetchall()
        
        cursor.execute("""
            SELECT fe.* FROM faculty_expertise fe
            JOIN faculties f ON fe.faculty_id = f.id
            WHERE f.department_id = %s
        """, (department_id,))
        expertise = cursor.fetchall() 
        
        if not faculties or not subjects or not batches:
            return {"success": False, "message": "No data found for this department."}

        expertise_map = {}
        for exp in expertise:
            f_id = exp['faculty_id']
            s_id = exp['subject_id']
            if f_id not in expertise_map:
                expertise_map[f_id] = {}
            expertise_map[f_id][s_id] = float(exp['competency_tier'])

        model = cp_model.CpModel()
        
        days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        slots = ["Slot1", "Slot2", "Slot3"]
        
        x = {}
        for f in faculties:
            f_id = f['id']
            if f_id not in expertise_map: continue 
            for s in subjects:
                s_id = s['id']
                if s_id in expertise_map[f_id]:
                    for r in rooms:
                        r_id = r['id']
                        for d in days:
                            for t in slots:
                                for b in batches:
                                    b_id = b['id']
                                    x[(f_id, s_id, r_id, d, t, b_id)] = model.NewBoolVar(f'x_{f_id}_{s_id}_{r_id}_{d}_{t}_{b_id}')

        for f in faculties:
            f_id = f['id']
            for d in days:
                for t in slots:
                    model.AddAtMostOne(x[(f_id, s['id'], r['id'], d, t, b['id'])] for s in subjects for r in rooms for b in batches if (f_id, s['id'], r['id'], d, t, b['id']) in x)

        for r in rooms:
            r_id = r['id']
            for d in days:
                for t in slots:
                    model.AddAtMostOne(x[(f['id'], s['id'], r_id, d, t, b['id'])] for f in faculties for s in subjects for b in batches if (f['id'], s['id'], r_id, d, t, b['id']) in x)

        for b in batches:
            b_id = b['id']
            for d in days:
                for t in slots:
                    model.AddAtMostOne(x[(f['id'], s['id'], r['id'], d, t, b_id)] for f in faculties for s in subjects for r in rooms if (f['id'], s['id'], r['id'], d, t, b_id) in x)

        for b in batches:
            b_id = b['id']
            for s in subjects:
                if s['subject_type'] == 'Practical':
                    s_id = s['id']
                    for f in faculties:
                        f_id = f['id']
                        for r in rooms:
                            r_id = r['id']
                            for d in days:
                                if (f_id, s_id, r_id, d, 'Slot1', b_id) in x and (f_id, s_id, r_id, d, 'Slot2', b_id) in x:
                                    model.Add(x[(f_id, s_id, r_id, d, 'Slot1', b_id)] == x[(f_id, s_id, r_id, d, 'Slot2', b_id)])

        for b in batches:
            b_id = b['id']
            for s in subjects:
                s_id = s['id']
                
                subject_vars = [
                    x[(f['id'], s_id, r['id'], d, t, b_id)] 
                    for f in faculties for r in rooms for d in days for t in slots 
                    if (f['id'], s_id, r['id'], d, t, b_id) in x
                ]
                
                if not subject_vars:
                    continue
                    
                if s['subject_type'] == 'Theory':
                    model.Add(sum(subject_vars) == s['required_sessions'])
                else:
                    model.Add(sum(subject_vars) == s['required_sessions'] * 2)

        for f in faculties:
            f_id = f['id']
            model.Add(sum(x[(f_id, s['id'], r['id'], d, t, b['id'])] for s in subjects for r in rooms for d in days for t in slots for b in batches if (f_id, s['id'], r['id'], d, t, b['id']) in x) <= f['max_weekly_hours'])

        objective_terms = []
        for (f_id, s_id, r_id, d, t, b_id), var in x.items():
            weight = int(expertise_map[f_id][s_id] * 10)
            objective_terms.append(var * weight)
            
        model.Maximize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 15.0
        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            cursor.execute("DELETE FROM timetables WHERE department_id = %s;", (department_id,))
            
            classes_scheduled = 0
            for (f_id, s_id, r_id, d, t, b_id) in x:
                if solver.Value(x[(f_id, s_id, r_id, d, t, b_id)]) == 1:
                    cursor.execute("""
                        INSERT INTO timetables (department_id, day_of_week, timeslot, room_id, batch_id, subject_id, faculty_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (department_id, d, t, r_id, b_id, s_id, f_id))
                    classes_scheduled += 1
            
            conn.commit()
            return {"success": True, "message": "Timetable generated!", "total_lectures_scheduled": classes_scheduled}
        else:
            return {"success": False, "message": "System could not find a mathematical solution."}

    except Exception as e:
        print("--- SERVER ERROR DETECTED ---")
        print(e)
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/view-timetable/")
def view_timetable():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT 
                t.day_of_week, t.timeslot, 
                r.name AS room, b.name AS batch, 
                s.name AS subject, f.name AS faculty
            FROM timetables t
            JOIN rooms r ON t.room_id = r.id
            JOIN batches b ON t.batch_id = b.id
            JOIN subjects s ON t.subject_id = s.id
            JOIN faculties f ON t.faculty_id = f.id
            ORDER BY t.day_of_week, t.timeslot;
        """
        cursor.execute(query)
        schedule = cursor.fetchall()
        return {"data": schedule}
    finally:
        cursor.close()
        conn.close()